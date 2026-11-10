"""Unit tests: the mock-data seeder must respect the schema constraints.

Both regressions here were found by running `scripts/seed_mock_data.py` against
an empty database: the seeder aborted mid-run on a Postgres constraint, so
nobody ever got a seeded dataset to test the app against.

The seeder writes through psycopg's COPY interface, so these tests substitute a
fake cursor that records the rows instead of talking to a database. That keeps
the test fast and database-free while still exercising the real generation
code.
"""

import random
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from seed_mock_data import PRESETS, Seeder  # noqa: E402


class _FakeCopy:
    """Stands in for psycopg's COPY writer and records the rows."""

    def __init__(self, sink: list) -> None:
        self.sink = sink

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def write_row(self, row) -> None:
        self.sink.append(row)


class _FakeCursor:
    """Captures the rows the seeder would have COPYed into each table."""

    def __init__(self) -> None:
        self.tables: dict[str, list] = {}

    def copy(self, statement: str) -> _FakeCopy:
        table = statement.split()[1]
        sink = self.tables.setdefault(table, [])
        return _FakeCopy(sink)

    def execute(self, *args, **kwargs) -> None:  # pragma: no cover - reset only
        pass

    def fetchall(self) -> list:  # pragma: no cover - reset only
        return []


class _FakeConnection:
    def __init__(self) -> None:
        self._cursor = _FakeCursor()

    def cursor(self) -> _FakeCursor:
        return self._cursor


def _make_seeder(seed: int = 1337) -> tuple[Seeder, _FakeCursor]:
    conn = _FakeConnection()
    cfg = dict(PRESETS["light"])
    seeder = Seeder(conn, random.Random(seed), cfg, "not-a-real-hash")
    return seeder, conn._cursor


def _org_rows(count: int) -> tuple[list, list, list]:
    """Build the (orgs, member_lists, projects_by_org) triple the seeder wants."""
    now = datetime.now(UTC)
    orgs, member_lists, projects_by_org = [], [], []
    for index in range(count):
        org_id = uuid.uuid4()
        org_created = now - timedelta(days=400)
        orgs.append((org_id, f"Org {index}", f"org-{index}", True, None, org_created, None))
        members = [str(uuid.uuid4()) for _ in range(5)]
        member_lists.append(members)
        projects = []
        for project_index in range(4):
            project_id = str(uuid.uuid4())
            projects.append((project_id, (now - timedelta(days=300)).isoformat()))
        projects_by_org.append(projects)
    return orgs, member_lists, projects_by_org


def test_each_project_gets_exactly_one_active_sprint():
    """`uq_sprints_one_active` is UNIQUE(project_id) WHERE state = 'active'.

    The seeder used to draw every sprint's state independently, so a project
    with three sprints regularly produced two 'active' ones and the COPY aborted
    with a UniqueViolation.
    """
    seeder, cursor = _make_seeder()
    orgs, member_lists, projects_by_org = _org_rows(3)

    seeder.load_sprints_releases(orgs, member_lists, projects_by_org)

    sprints = cursor.tables["sprints"]
    assert sprints, "expected the seeder to generate sprints"

    # column order: id, organization_id, project_id, name, goal, state, ...
    by_project: dict[str, list[str]] = {}
    for sprint in sprints:
        by_project.setdefault(sprint[2], []).append(sprint[5])

    for project_id, states in by_project.items():
        active = [state for state in states if state == "active"]
        assert len(active) == 1, (
            f"project {project_id} has {len(active)} active sprints, expected exactly 1 "
            f"(states={states})"
        )


def test_comment_root_id_points_at_the_thread_root():
    """`comments.root_id` is a uuid FK to the thread's top-level comment.

    The seeder used to unpack a (comment_id, created_at) tuple into
    (parent_id, root_id), writing the comment's timestamp into the uuid column
    and aborting the COPY with an InvalidTextRepresentation.

    Several seeds are used because a task only gets a reply when the seeder
    draws more than one comment for it; a single seed can produce no replies
    at all and would pass vacuously.
    """
    replies_seen = 0
    for seed in (1, 42, 999, 2024, 1337, 31337, 777):
        seeder, cursor = _make_seeder(seed)
        orgs, member_lists, projects_by_org = _org_rows(2)
        now = datetime.now(UTC)

        tasks_meta = []
        org_index_by_id = {}
        for index, org in enumerate(orgs):
            org_index_by_id[org[0]] = index
            for project_id, _created_iso in projects_by_org[index]:
                task_id = str(uuid.uuid4())
                tasks_meta.append(
                    (task_id, org[0], project_id, now - timedelta(days=100), None, None, None, None, None)
                )

        seeder.load_comments(tasks_meta, member_lists, org_index_by_id)

        comments = cursor.tables["comments"]
        assert comments, "expected the seeder to generate comments"

        ids = {str(comment[0]) for comment in comments}
        for comment in comments:
            # column order: id, organization_id, task_id, author_id, body,
            #               parent_id, root_id, created_at, updated_at
            comment_id, _org_id, _task_id, _author_id, _body, parent_id, root_id = comment[:7]

            if root_id is None:
                assert parent_id is None, f"comment {comment_id} has a parent but no root"
                continue

            replies_seen += 1
            # psycopg accepts a uuid column as a UUID or its string form; what
            # must never appear here is a timestamp.
            assert not isinstance(root_id, datetime), (
                f"seed {seed}: comment {comment_id} wrote a timestamp into the "
                f"uuid root_id column: {root_id!r}"
            )
            assert str(uuid.UUID(str(root_id))) == str(root_id), (
                f"seed {seed}: comment {comment_id} has a malformed root_id {root_id!r}"
            )
            assert str(root_id) in ids, (
                f"seed {seed}: comment {comment_id} points at an unknown root {root_id}"
            )
            assert str(parent_id) == str(root_id), (
                f"seed {seed}: comment {comment_id} replies to {parent_id} "
                f"but points at root {root_id}"
            )

    assert replies_seen > 0, "no replies were generated, so the root_id check was vacuous"


def test_seeder_runs_without_a_database_for_many_seeds():
    """The generation paths must never raise, whatever the RNG draws."""
    for seed in (1, 42, 999, 2024, 31337):
        seeder, cursor = _make_seeder(seed)
        orgs, member_lists, projects_by_org = _org_rows(2)
        seeder.load_sprints_releases(orgs, member_lists, projects_by_org)

        sprints = cursor.tables["sprints"]
        by_project: dict[str, list[str]] = {}
        for sprint in sprints:
            by_project.setdefault(sprint[2], []).append(sprint[5])
        for project_id, states in by_project.items():
            assert len([s for s in states if s == "active"]) == 1, (seed, project_id, states)
