"""Heavy, deterministic mock-data seeder for TeamFlow development.

Loads the configured sync database (DATABASE_URL_SYNC, else DATABASE_URL with a
psycopg driver) using PostgreSQL COPY, so ~1M rows land in well under a minute.

Examples:
    docker compose exec api uv run python scripts/seed_mock_data.py
    docker compose exec api uv run python scripts/seed_mock_data.py --preset extreme
    docker compose exec api uv run python scripts/seed_mock_data.py --reset
    docker compose exec api uv run python scripts/seed_mock_data.py --orgs 5 --tasks-per-org 200

Every generated user has the same password (default: Password123!) which is
printed at the end together with a sample login.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import psycopg

from app.core.config import settings
from app.core.security import hash_password

PRESETS: dict[str, dict] = {
    "light": {
        "users": 200,
        "orgs": 10,
        "members": (6, 25),
        "projects": (3, 8),
        "tasks_per_org": 400,
        "comment_rate": 0.35,
        "attachment_rate": 0.15,
        "audit_multiplier": 2.0,
        "notifications_per_user": (0, 6),
    },
    "heavy": {
        "users": 2000,
        "orgs": 40,
        "members": (15, 80),
        "projects": (6, 18),
        "tasks_per_org": 2500,
        "comment_rate": 0.6,
        "attachment_rate": 0.2,
        "audit_multiplier": 2.5,
        "notifications_per_user": (2, 12),
    },
    "extreme": {
        "users": 5000,
        "orgs": 100,
        "members": (20, 120),
        "projects": (8, 25),
        "tasks_per_org": 6000,
        "comment_rate": 0.7,
        "attachment_rate": 0.25,
        "audit_multiplier": 3.0,
        "notifications_per_user": (3, 20),
    },
}

FIRST_NAMES = [
    "Ada", "Alan", "Alice", "Amir", "Ana", "Aria", "Arman", "Ava", "Ben", "Bianca",
    "Carla", "Chris", "Clara", "Dan", "Dana", "David", "Elena", "Eli", "Elsa", "Emma",
    "Farah", "Felix", "Grace", "Hana", "Hassan", "Helen", "Ida", "Ivan", "Jack", "Jana",
    "Jonas", "Julia", "Kai", "Kara", "Leo", "Lina", "Lucas", "Maya", "Mia", "Nadia",
    "Noah", "Nora", "Omar", "Oscar", "Parisa", "Paul", "Rana", "Reza", "Rosa", "Ryan",
    "Sara", "Sina", "Sofia", "Tara", "Tom", "Uma", "Victor", "Wendy", "Yara", "Zoe",
]

LAST_NAMES = [
    "Adams", "Ahmadi", "Alvarez", "Baker", "Bennett", "Brown", "Carter", "Chen", "Clark",
    "Davis", "Diaz", "Evans", "Fischer", "Garcia", "Ghani", "Green", "Hall", "Harris",
    "Hosseini", "Ivanov", "Jackson", "Johnson", "Karimi", "Kelly", "Khan", "Kim", "Lee",
    "Lewis", "Lopez", "Martin", "Miller", "Mohammadi", "Moore", "Moradi", "Morgan",
    "Nelson", "Nguyen", "Novak", "Okafor", "Olsen", "Park", "Patel", "Petrov", "Rahimi",
    "Reed", "Rostami", "Russo", "Sadeghi", "Sato", "Schmidt", "Silva", "Smith", "Taylor",
    "Thompson", "Turner", "Walker", "Wang", "White", "Wilson", "Young",
]

COMPANIES = [
    "Northwind", "Acme", "Globex", "Umbrella", "Initech", "Hooli", "Stark", "Wayne",
    "Wonka", "Tyrell", "Cyberdyne", "Soylent", "Massive Dynamic", "Vandelay", "Dunder",
    "Pied Piper", "Aperture", "Black Mesa", "Gringotts", "Monarch", "Blue Origin",
    "Vertex", "Nimbus", "Quanta", "Helix", "Orbit", "Lumen", "Cobalt", "Zephyr", "Atlas",
]

COMPANY_SUFFIXES = ["Labs", "Systems", "Studio", "Works", "Group", "Collective", "Digital", "Partners", "Industries"]

PROJECT_ADJECTIVES = [
    "Website", "Mobile", "Platform", "Data", "API", "Design", "Growth", "Infra",
    "Security", "Analytics", "Billing", "Onboarding", "Search", "Billing", "Support",
    "Payments", "Reporting", "Notifications",
]

PROJECT_NOUNS = [
    "Redesign", "Migration", "Revamp", "Rollout", "MVP", "Hardening", "Automation",
    "Dashboard", "Integration", "Launch", "Overhaul", "Cleanup",
]

EMOJIS = ["👍", "👎", "❤️", "🎉", "😄", "🚀", "✅", "👀", "🔥", "🙏"]

TASK_VERBS = [
    "Fix", "Add", "Refactor", "Document", "Investigate", "Optimize", "Implement",
    "Review", "Migrate", "Test", "Deploy", "Design", "Update", "Remove", "Harden",
    "Benchmark", "Clarify", "Polish",
]

TASK_OBJECTS = [
    "login redirect loop", "pagination on task lists", "webhook retry logic",
    "dashboard caching", "CSV export", "rate limiter edge cases", "email templates",
    "tenant isolation tests", "S3 presigned URLs", "audit log retention",
    "refresh token rotation", "kanban drag and drop", "notification inbox",
    "role hierarchy checks", "CI pipeline", "database indexes", "error reporting",
    "search filters", "attachment size limits", "API documentation", "onboarding flow",
    "timezone handling", "soft-delete semantics", "idempotency keys", "realtime fan-out",
    "cache invalidation", "N+1 queries", "health probes", "structured logging",
    "password reset flow", "label colors", "due-date reminders", "mention parsing",
]

TASK_CONTEXTS = [
    "before the next release", "per customer feedback", "as part of the platform work",
    "to unblock QA", "after the security review", "for the enterprise rollout",
    "to reduce p95 latency", "because staging keeps flaking", "ahead of the demo",
    "to comply with the audit", "while we still have context", "for the migration window",
]

COMMENT_PHRASES = [
    "Picked this up, will update by EOD.",
    "Reproduced on staging — steps in the description.",
    "Blocked on the API change, moving it back.",
    "Nice catch, I had missed the empty state.",
    "Should we split this into two tasks?",
    "Added a regression test for this.",
    "Deployed behind a flag, looks good so far.",
    "Can you share the request ID from the logs?",
    "I think the root cause is the cache TTL.",
    "Updated the acceptance criteria.",
    "This is closer to a config issue than a bug.",
    "Moved to review — screenshots attached.",
    "Let's keep the scope to the happy path for now.",
    "The p95 dropped from 800ms to 120ms after this.",
    "Please don't forget the migration note.",
    "Merged, will verify in production tomorrow.",
    "Do we need a follow-up for the docs?",
    "I left a couple of comments on the PR.",
    "Works locally, re-running CI.",
    "Assigning to you since you own this area.",
]

LABEL_POOL = [
    ("bug", "#ef4444"),
    ("feature", "#6366f1"),
    ("design", "#ec4899"),
    ("backend", "#0ea5e9"),
    ("frontend", "#f97316"),
    ("infra", "#64748b"),
    ("security", "#dc2626"),
    ("urgent", "#f59e0b"),
    ("docs", "#10b981"),
    ("customer", "#8b5cf6"),
    ("performance", "#14b8a6"),
    ("tech-debt", "#a855f7"),
    ("regression", "#e11d48"),
    ("good-first-issue", "#22c55e"),
    ("blocked", "#78716c"),
]

ATTACHMENT_FILES = [
    ("screenshot.png", "image/png"),
    ("spec.pdf", "application/pdf"),
    ("notes.md", "text/markdown"),
    ("data.csv", "text/csv"),
    ("report.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ("diagram.jpg", "image/jpeg"),
    ("release-notes.txt", "text/plain"),
    ("bundle.zip", "application/zip"),
    ("wireframe.webp", "image/webp"),
    ("metrics.json", "application/json"),
]

AUDIT_ACTIONS = [
    ("task.created", "task", 30),
    ("task.updated", "task", 22),
    ("task.assigned", "task", 10),
    ("task.completed", "task", 12),
    ("comment.created", "comment", 12),
    ("project.created", "project", 2),
    ("project.updated", "project", 2),
    ("member.role_changed", "membership", 1),
    ("member.removed", "membership", 1),
    ("user.login", "user", 5),
    ("attachment.uploaded", "attachment", 2),
    ("webhook.created", "webhook", 1),
]

WEBHOOK_URLS = [
    "https://hooks.slack.com/services/T000/B000/{token}",
    "https://discord.com/api/webhooks/0000/{token}",
    "https://api.example.com/teamflow/events/{token}",
    "https://ci.example.com/hooks/teamflow/{token}",
    "https://automation.example.net/inbound/{token}",
]

STATUS_WEIGHTS = [("todo", 0.35), ("in_progress", 0.25), ("in_review", 0.15), ("done", 0.25)]
PRIORITY_WEIGHTS = [("low", 0.25), ("medium", 0.45), ("high", 0.20), ("urgent", 0.10)]


def weighted(rng: random.Random, pairs: list[tuple[str, float]]) -> str:
    return rng.choices([p[0] for p in pairs], weights=[p[1] for p in pairs], k=1)[0]


def new_uuid(rng: random.Random) -> uuid.UUID:
    return uuid.UUID(int=rng.getrandbits(128), version=4)


def rand_dt(rng: random.Random, end: datetime, max_days: float, min_days: float = 0.0) -> datetime:
    offset = timedelta(days=rng.uniform(min_days, max_days), seconds=rng.randint(0, 86_399))
    return end - offset


def rand_between(rng: random.Random, start: datetime, end: datetime) -> datetime:
    if end <= start:
        return start
    span = (end - start).total_seconds()
    return start + timedelta(seconds=rng.uniform(0, span))


def slugify(value: str) -> str:
    out = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")


def copy_rows(cur: psycopg.Cursor, table: str, columns: tuple[str, ...], rows) -> int:
    count = 0
    statement = f"COPY {table} ({', '.join(columns)}) FROM STDIN"
    with cur.copy(statement) as copy:
        for row in rows:
            copy.write_row(row)
            count += 1
    return count


class Seeder:
    def __init__(self, conn: psycopg.Connection, rng: random.Random, cfg: dict, password_hash: str):
        self.conn = conn
        self.cur = conn.cursor()
        self.rng = rng
        self.cfg = cfg
        self.password_hash = password_hash
        self.now = datetime.now(UTC)
        self.counts: dict[str, int] = {}
        self.sample_email = ""

    def reset(self) -> None:
        self.cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        tables = [row[0] for row in self.cur.fetchall() if row[0] != "alembic_version"]
        if tables:
            self.cur.execute(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE")
            print(f"  truncated {len(tables)} tables", flush=True)

    def load_users(self) -> list[tuple]:
        rng = self.rng
        rows = []
        for index in range(self.cfg["users"]):
            first = rng.choice(FIRST_NAMES)
            last = rng.choice(LAST_NAMES)
            email = f"{first.lower()}.{last.lower()}.{index:05d}@mock.teamflow.dev"
            created = rand_dt(rng, self.now, 720, 1)
            rows.append(
                (
                    new_uuid(rng),
                    email,
                    self.password_hash,
                    f"{first} {last}",
                    rng.random() > 0.04,
                    False,
                    created,
                    None,
                )
            )
        self.counts["users"] = copy_rows(
            self.cur,
            "users",
            ("id", "email", "hashed_password", "full_name", "is_active", "is_superuser", "created_at", "updated_at"),
            rows,
        )
        if rows:
            self.sample_email = rows[0][1]
        return rows

    def load_orgs_members(
        self, users: list[tuple]
    ) -> tuple[list[tuple], list[tuple], list[list[str]], dict]:
        rng = self.rng
        cfg = self.cfg
        active_users = [u for u in users if u[4]]
        orgs = []
        memberships = []
        member_lists: list[list[str]] = []
        user_orgs: dict[str, list[int]] = {}

        for index in range(cfg["orgs"]):
            company = rng.choice(COMPANIES)
            suffix = rng.choice(COMPANY_SUFFIXES)
            name = f"{company} {suffix}"
            slug = f"mock-{slugify(name)}-{index:03d}"
            created = rand_dt(rng, self.now, 700, 10)
            owner = rng.choice(active_users)
            org_id = new_uuid(rng)
            orgs.append((org_id, name, slug, True, owner[0], created, None))

            size = min(len(active_users), rng.randint(*cfg["members"]))
            chosen = rng.sample(active_users, size)
            if owner not in chosen:
                chosen[0] = owner
            roles = ["owner"] + [
                weighted(rng, [("member", 0.78), ("manager", 0.16), ("admin", 0.06)])
                for _ in range(size - 1)
            ]
            org_members = []
            for user_row, role in zip(chosen, roles, strict=True):
                joined = rand_between(rng, created, self.now)
                memberships.append(
                    (
                        new_uuid(rng),
                        user_row[0],
                        org_id,
                        role,
                        rng.random() > 0.05,
                        joined,
                        None,
                    )
                )
                org_members.append(str(user_row[0]))
                user_orgs.setdefault(str(user_row[0]), []).append(index)
            member_lists.append(org_members)

        self.counts["organizations"] = copy_rows(
            self.cur,
            "organizations",
            ("id", "name", "slug", "is_active", "created_by_id", "created_at", "updated_at"),
            orgs,
        )
        self.counts["memberships"] = copy_rows(
            self.cur,
            "memberships",
            ("id", "user_id", "organization_id", "role", "is_active", "created_at", "updated_at"),
            memberships,
        )
        return orgs, memberships, member_lists, user_orgs

    def load_projects_labels(
        self, orgs: list[tuple], member_lists: list[list[str]]
    ) -> tuple[dict[int, list[tuple]], dict[int, list[str]]]:
        rng = self.rng
        cfg = self.cfg
        project_rows = []
        label_rows = []
        projects_by_org: dict[int, list[tuple]] = {}
        labels_by_org: dict[int, list[str]] = {}

        for index, org in enumerate(orgs):
            org_id, _, _, _, _, org_created, _ = org
            members = member_lists[index]

            project_count = rng.randint(*cfg["projects"])
            projects = []
            for _ in range(project_count):
                name = f"{rng.choice(PROJECT_ADJECTIVES)} {rng.choice(PROJECT_NOUNS)}"
                created = rand_between(rng, org_created, self.now)
                project_id = new_uuid(rng)
                status = "archived" if rng.random() < 0.12 else "active"
                projects.append((project_id, str(created)))
                project_rows.append(
                    (
                        project_id,
                        org_id,
                        name,
                        f"{name} workstream. Owners keep the board up to date.",
                        status,
                        rng.choice(members),
                        created,
                        None,
                    )
                )
            projects_by_org[index] = projects

            label_count = rng.randint(6, min(len(LABEL_POOL), 15))
            labels = []
            for label_name, color in rng.sample(LABEL_POOL, label_count):
                label_id = new_uuid(rng)
                labels.append(str(label_id))
                label_rows.append((label_id, label_name, color, org_id, org_created, None))
            labels_by_org[index] = labels

        self.counts["projects"] = copy_rows(
            self.cur,
            "projects",
            ("id", "organization_id", "name", "description", "status", "owner_id", "created_at", "updated_at"),
            project_rows,
        )
        self.counts["labels"] = copy_rows(
            self.cur,
            "labels",
            ("id", "name", "color", "organization_id", "created_at", "updated_at"),
            label_rows,
        )
        return projects_by_org, labels_by_org

    def load_sprints_releases(
        self,
        orgs: list[tuple],
        member_lists: list[list[str]],
        projects_by_org: dict[int, list[tuple]],
    ) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
        """M1 sprints + M3 releases so reports/roadmap/calendar have real data."""
        rng = self.rng
        sprint_rows = []
        release_rows = []
        sprints_by_project: dict[str, list[str]] = {}
        releases_by_project: dict[str, list[str]] = {}

        for index, org in enumerate(orgs):
            org_id = org[0]
            org_created = org[5]
            members = member_lists[index]
            for project_id, project_created_iso in projects_by_org[index]:
                created = datetime.fromisoformat(project_created_iso)
                sprint_ids = []
                for seq in range(rng.randint(2, 4)):
                    sprint_id = new_uuid(rng)
                    start = rand_between(rng, max(created, org_created), self.now)
                    end = min(start + timedelta(days=14), self.now + timedelta(days=21))
                    state = rng.choices(["planned", "active", "completed"], weights=[0.45, 0.2, 0.35], k=1)[0]
                    completed_at = end if state == "completed" else None
                    sprint_rows.append(
                        (
                            sprint_id, org_id, project_id, f"Sprint {seq + 1}",
                            "Keep the board moving.", state, start, end, completed_at,
                            rng.choice(members), created, None,
                        )
                    )
                    sprint_ids.append(str(sprint_id))
                sprints_by_project[str(project_id)] = sprint_ids

                release_ids = []
                for seq in range(rng.randint(1, 3)):
                    release_id = new_uuid(rng)
                    window_start = rand_between(rng, max(created, org_created), self.now)
                    release_date = min(window_start + timedelta(days=rng.randint(20, 120)), self.now + timedelta(days=60))
                    status = rng.choices(
                        ["planned", "in_progress", "released", "cancelled"],
                        weights=[0.35, 0.3, 0.3, 0.05],
                        k=1,
                    )[0]
                    released_at = release_date if status == "released" else None
                    release_rows.append(
                        (
                            release_id, org_id, project_id, f"v0.{seq + 1}.0", "Release scope.",
                            f"0.{seq + 1}.0", status, window_start, release_date, released_at,
                            rng.choice(members), created, None,
                        )
                    )
                    release_ids.append(str(release_id))
                releases_by_project[str(project_id)] = release_ids

        self.counts["sprints"] = copy_rows(
            self.cur,
            "sprints",
            (
                "id", "organization_id", "project_id", "name", "goal", "state",
                "start_date", "end_date", "completed_at", "created_by_id", "created_at",
                "updated_at",
            ),
            sprint_rows,
        )
        self.counts["releases"] = copy_rows(
            self.cur,
            "releases",
            (
                "id", "organization_id", "project_id", "name", "description", "version",
                "status", "start_date", "release_date", "released_at", "created_by_id",
                "created_at", "updated_at",
            ),
            release_rows,
        )
        return sprints_by_project, releases_by_project

    def load_tasks(
        self,
        orgs: list[tuple],
        member_lists: list[list[str]],
        projects_by_org: dict[int, list[tuple]],
        labels_by_org: dict[int, list[str]],
        sprints_by_project: dict[str, list[str]],
        releases_by_project: dict[str, list[str]],
    ) -> tuple[list[tuple], dict[int, list[tuple]]]:
        rng = self.rng
        cfg = self.cfg
        columns = (
            "id", "organization_id", "project_id", "title", "description", "status",
            "status_category", "priority", "type", "key", "number", "due_date",
            "created_by_id", "assignee_id", "completed_at", "sprint_id", "release_id",
            "created_at", "updated_at",
        )
        tasks_meta: list[tuple] = []
        tasks_by_org: dict[int, list[tuple]] = {index: [] for index in range(len(orgs))}

        with self.cur.copy(f"COPY tasks ({', '.join(columns)}) FROM STDIN") as copy:
            for index, org in enumerate(orgs):
                org_id = org[0]
                org_created = org[5]
                members = member_lists[index]
                projects = projects_by_org[index]
                labels = labels_by_org[index]
                numbers: dict[str, int] = {}
                for _ in range(cfg["tasks_per_org"]):
                    project_id, project_created_iso = rng.choice(projects)
                    project_key = str(project_id)
                    number = numbers.get(project_key, 0) + 1
                    numbers[project_key] = number
                    prefix = f"P{str(project_id).replace('-', '')[:3].upper()}"
                    issue_key = f"{prefix}-{number}"
                    project_created = datetime.fromisoformat(project_created_iso)
                    created = rand_between(rng, max(project_created, org_created), self.now)
                    status = weighted(rng, STATUS_WEIGHTS)
                    priority = weighted(rng, PRIORITY_WEIGHTS)
                    task_type = rng.choices(["task", "story", "epic"], weights=[0.72, 0.24, 0.04], k=1)[0]
                    title = f"{rng.choice(TASK_VERBS)} {rng.choice(TASK_OBJECTS)}"
                    description = (
                        f"{title.capitalize()} {rng.choice(TASK_CONTEXTS)}.\n\n"
                        f"Acceptance criteria:\n- works for all tenants\n- covered by tests\n- documented"
                    )
                    creator = rng.choice(members)
                    assignee = None if rng.random() < 0.3 else rng.choice(members)
                    due_date = None
                    if rng.random() < 0.75:
                        due_date = created + timedelta(days=rng.randint(-20, 60), seconds=rng.randint(0, 86_399))
                    completed_at = None
                    if status == "done":
                        completed_at = min(created + timedelta(days=rng.uniform(0.5, 25)), self.now)
                    updated_at = None
                    if rng.random() < 0.65:
                        updated_at = min(created + timedelta(days=rng.uniform(0.1, 20)), self.now)
                    sprint_id = None
                    if rng.random() < 0.55:
                        sprint_id = rng.choice(sprints_by_project.get(project_key, [None]))
                    release_id = None
                    if rng.random() < 0.5:
                        release_id = rng.choice(releases_by_project.get(project_key, [None]))
                    task_id = new_uuid(rng)
                    copy.write_row(
                        (
                            task_id, org_id, project_id, title, description, status,
                            status, priority, task_type, issue_key, number, due_date,
                            creator, assignee, completed_at, sprint_id, release_id,
                            created, updated_at,
                        )
                    )
                    meta = (
                        str(task_id), str(org_id), str(project_id), created, status,
                        creator, assignee, title, labels,
                    )
                    tasks_meta.append(meta)
                    tasks_by_org[index].append(meta)

        self.counts["tasks"] = len(tasks_meta)
        return tasks_meta, tasks_by_org

    def load_task_labels(self, tasks_meta: list[tuple]) -> None:
        rng = self.rng
        rows = []
        for meta in tasks_meta:
            task_id = meta[0]
            labels = meta[8]
            for label_id in rng.sample(labels, rng.randint(0, 3)):
                rows.append((task_id, label_id))
        self.counts["task_labels"] = copy_rows(self.cur, "task_labels", ("task_id", "label_id"), rows)

    def load_watchers(self, tasks_meta: list[tuple], member_lists: list[list[str]], org_index_by_id: dict[str, int]) -> None:
        rng = self.rng
        rows = []
        for meta in tasks_meta:
            task_id, org_id, _, _, _, creator, assignee = meta[:7]
            members = member_lists[org_index_by_id[org_id]]
            watchers = {creator}
            if assignee:
                watchers.add(assignee)
            watchers.update(rng.sample(members, min(len(members), rng.randint(0, 3))))
            rows.extend((task_id, user_id) for user_id in watchers)
        self.counts["task_watchers"] = copy_rows(self.cur, "task_watchers", ("task_id", "user_id"), rows)

    def load_comments(
        self, tasks_meta: list[tuple], member_lists: list[list[str]], org_index_by_id: dict[str, int]
    ) -> list[tuple]:
        """Threaded comments (root + one reply level) with reaction candidates.

        Returns a bounded sample of comments so `load_reactions` can attach
        emoji reactions without holding every comment in memory.
        """
        rng = self.rng
        columns = (
            "id", "organization_id", "task_id", "author_id", "body",
            "parent_id", "root_id", "created_at", "updated_at",
        )
        reaction_candidates: list[tuple] = []

        def rows():
            for meta in tasks_meta:
                if rng.random() > self.cfg["comment_rate"]:
                    continue
                task_id, org_id, _, created, _, _, _, _, _ = meta
                if isinstance(created, str):
                    created = datetime.fromisoformat(created)
                members = member_lists[org_index_by_id[org_id]]
                thread_root: tuple[str, datetime] | None = None
                for _ in range(rng.randint(1, 5)):
                    comment_id = new_uuid(rng)
                    comment_created = rand_between(rng, created, self.now)
                    updated = None
                    if rng.random() < 0.1:
                        updated = min(comment_created + timedelta(days=rng.uniform(0.01, 2)), self.now)
                    body = " ".join(rng.sample(COMMENT_PHRASES, rng.randint(1, 2)))
                    author = rng.choice(members)
                    parent_id = root_id = None
                    if thread_root is not None and rng.random() < 0.5:
                        parent_id, root_id = thread_root
                    else:
                        thread_root = (str(comment_id), comment_created)
                    if len(reaction_candidates) < 50_000 and rng.random() < 0.25:
                        reaction_candidates.append((org_id, str(comment_id), author, comment_created))
                    yield (
                        comment_id, org_id, task_id, author, body,
                        parent_id, root_id, comment_created, updated,
                    )

        self.counts["comments"] = copy_rows(self.cur, "comments", columns, rows())
        return reaction_candidates

    def load_reactions(self, candidates: list[tuple]) -> None:
        rng = self.rng
        rows = []
        for org_id, comment_id, author, created in candidates:
            for emoji in rng.sample(EMOJIS, rng.randint(1, 2)):
                rows.append(
                    (new_uuid(rng), org_id, comment_id, rng.choice([author, author]), emoji, created, None)
                )
        self.counts["comment_reactions"] = copy_rows(
            self.cur,
            "comment_reactions",
            ("id", "organization_id", "comment_id", "user_id", "emoji", "created_at", "updated_at"),
            rows,
        )

    def load_activities(
        self, tasks_meta: list[tuple], member_lists: list[list[str]], org_index_by_id: dict[str, int]
    ) -> None:
        """One `task_created` activity per task + a slices of status changes."""
        rng = self.rng
        columns = (
            "id", "organization_id", "project_id", "task_id", "actor_id", "verb",
            "summary", "data", "created_at", "updated_at",
        )

        def rows():
            for meta in tasks_meta:
                task_id, org_id, project_id, created, status, creator, _, title, _ = meta
                if isinstance(created, str):
                    created = datetime.fromisoformat(created)
                yield (
                    new_uuid(rng), org_id, project_id, task_id, creator, "task_created",
                    f"created {title}", json.dumps({"title": title}), created, None,
                )
                if rng.random() < 0.35:
                    changed = rand_between(rng, created, self.now)
                    members = member_lists[org_index_by_id[org_id]]
                    yield (
                        new_uuid(rng), org_id, project_id, task_id, rng.choice(members),
                        "status_changed", f"moved {title} to {status}",
                        json.dumps({"to": status}), changed, None,
                    )

        self.counts["activities"] = copy_rows(self.cur, "activities", columns, rows())

    def load_attachments(self, tasks_meta: list[tuple], member_lists: list[list[str]], org_index_by_id: dict[str, int]) -> None:
        rng = self.rng
        columns = (
            "id", "organization_id", "task_id", "uploader_id", "filename", "content_type",
            "size", "storage_key", "status", "created_at", "updated_at",
        )

        def rows():
            for meta in tasks_meta:
                if rng.random() > self.cfg["attachment_rate"]:
                    continue
                task_id, org_id, _, created, _, _, _, _, _ = meta
                if isinstance(created, str):
                    created = datetime.fromisoformat(created)
                members = member_lists[org_index_by_id[org_id]]
                for _ in range(rng.randint(1, 2)):
                    filename, content_type = rng.choice(ATTACHMENT_FILES)
                    attachment_id = new_uuid(rng)
                    storage_key = f"{org_id}/{task_id}/{uuid.uuid4().hex}-{filename}"
                    status = rng.choices(["available", "pending", "failed"], weights=[0.85, 0.1, 0.05], k=1)[0]
                    attachment_created = rand_between(rng, created, self.now)
                    yield (
                        attachment_id, org_id, task_id, rng.choice(members), filename, content_type,
                        rng.randint(12_000, 9_500_000), storage_key, status, attachment_created, None,
                    )

        self.counts["attachments"] = copy_rows(self.cur, "attachments", columns, rows())

    def load_notifications(self, users: list[tuple], tasks_by_org: dict[int, list[tuple]], user_orgs: dict[str, list[int]]) -> None:
        rng = self.rng
        columns = (
            "id", "user_id", "organization_id", "project_id", "task_id", "type",
            "title", "body", "data", "read_at", "created_at", "updated_at",
        )
        types = ["task_assigned", "task_completed", "comment_created", "mention", "task_due_soon"]

        def rows():
            for user in users:
                org_indexes = user_orgs.get(str(user[0]), [])
                if not org_indexes:
                    continue
                for _ in range(rng.randint(*self.cfg["notifications_per_user"])):
                    org_index = rng.choice(org_indexes)
                    tasks = tasks_by_org[org_index]
                    if not tasks:
                        continue
                    task = rng.choice(tasks)
                    task_id, org_id, project_id, _, _, _, _, title, _ = task
                    created = rand_dt(rng, self.now, 45, 0)
                    read_at = created + timedelta(hours=rng.uniform(0.2, 48)) if rng.random() < 0.6 else None
                    if read_at and read_at > self.now:
                        read_at = None
                    notification_type = rng.choice(types)
                    yield (
                        new_uuid(rng),
                        user[0],
                        org_id,
                        project_id,
                        task_id,
                        notification_type,
                        f"{notification_type.replace('_', ' ').title()}: {title}",
                        rng.choice(COMMENT_PHRASES),
                        json.dumps({"task_id": task_id, "project_id": project_id}),
                        read_at,
                        created,
                        None,
                    )

        self.counts["notifications"] = copy_rows(self.cur, "notifications", columns, rows())

    def load_audit_logs(self, tasks_meta: list[tuple], member_lists: list[list[str]], org_index_by_id: dict[str, int]) -> None:
        rng = self.rng
        columns = ("id", "actor_id", "organization_id", "action", "target_type", "target_id", "ip", "meta", "created_at", "updated_at")
        actions = [a[0] for a in AUDIT_ACTIONS]
        weights = [a[2] for a in AUDIT_ACTIONS]
        target_types = {a[0]: a[1] for a in AUDIT_ACTIONS}
        multiplier = self.cfg["audit_multiplier"]

        def rows():
            for meta in tasks_meta:
                task_id, org_id, project_id, created, status, creator, assignee, title, _ = meta
                if isinstance(created, str):
                    created = datetime.fromisoformat(created)
                members = member_lists[org_index_by_id[org_id]]
                for _ in range(1 + int(rng.random() * multiplier)):
                    action = rng.choices(actions, weights=weights, k=1)[0]
                    actor = creator if action in ("task.created", "task.assigned") else rng.choice(members)
                    event_at = rand_between(rng, created, self.now)
                    payload = {"title": title, "project_id": project_id}
                    if action == "comment.created":
                        target_id = str(new_uuid(rng))
                    else:
                        target_id = task_id
                    yield (
                        new_uuid(rng),
                        actor,
                        org_id,
                        action,
                        target_types[action],
                        target_id,
                        f"10.{rng.randint(0, 255)}.{rng.randint(0, 255)}.{rng.randint(1, 254)}",
                        json.dumps(payload),
                        event_at,
                        None,
                    )

        self.counts["audit_logs"] = copy_rows(self.cur, "audit_logs", columns, rows())

    def load_invitations(self, orgs: list[tuple], member_lists: list[list[str]]) -> None:
        rng = self.rng
        columns = ("id", "email", "organization_id", "role", "status", "invited_by_id", "created_at", "updated_at")
        rows = []
        for index, org in enumerate(orgs):
            org_id, _, _, _, _, org_created, _ = org
            members = member_lists[index]
            for n in range(rng.randint(0, 4)):
                created = rand_between(rng, org_created, self.now)
                status = rng.choices(["pending", "accepted", "declined", "revoked"], weights=[0.35, 0.4, 0.15, 0.1], k=1)[0]
                rows.append(
                    (
                        new_uuid(rng),
                        f"invitee.{index:03d}.{n}@example.com",
                        org_id,
                        weighted(rng, [("member", 0.7), ("manager", 0.2), ("admin", 0.1)]),
                        status,
                        rng.choice(members),
                        created,
                        None if status == "pending" else created + timedelta(days=rng.uniform(0.1, 5)),
                    )
                )
        self.counts["invitations"] = copy_rows(self.cur, "invitations", columns, rows)

    def load_webhooks(self, orgs: list[tuple], member_lists: list[list[str]]) -> list[str]:
        rng = self.rng
        columns = ("id", "organization_id", "url", "secret", "events", "is_active", "description", "created_by_id", "created_at", "updated_at")
        events_pool = ["task.created", "task.updated", "task.completed", "comment.created", "member.joined"]
        rows = []
        webhook_ids = []
        for index, org in enumerate(orgs):
            org_id, _, _, _, _, org_created, _ = org
            members = member_lists[index]
            for _ in range(rng.choices([0, 1, 2, 3], weights=[0.25, 0.45, 0.2, 0.1], k=1)[0]):
                created = rand_between(rng, org_created, self.now)
                webhook_id = new_uuid(rng)
                webhook_ids.append(str(webhook_id))
                url = rng.choice(WEBHOOK_URLS).format(token=uuid.uuid4().hex)
                rows.append(
                    (
                        webhook_id,
                        org_id,
                        url,
                        uuid.uuid4().hex + uuid.uuid4().hex,
                        json.dumps(rng.sample(events_pool, rng.randint(1, len(events_pool)))),
                        rng.random() > 0.15,
                        rng.choice(["CI notifications", "Slack mirror", "Customer integration", "Analytics pipeline", None]),
                        rng.choice(members),
                        created,
                        None,
                    )
                )
        self.counts["webhooks"] = copy_rows(self.cur, "webhooks", columns, rows)
        return webhook_ids

    def load_deliveries(self, webhook_ids: list[str]) -> None:
        rng = self.rng
        columns = ("id", "webhook_id", "event", "payload", "status", "attempts", "response_status", "last_error", "delivered_at", "created_at", "updated_at")
        events_pool = ["task.created", "task.updated", "task.completed", "comment.created", "member.joined"]

        def rows():
            for webhook_id in webhook_ids:
                for _ in range(rng.randint(20, 150)):
                    created = rand_dt(rng, self.now, 60, 0)
                    event = rng.choice(events_pool)
                    status = rng.choices(["success", "failed", "pending"], weights=[0.78, 0.17, 0.05], k=1)[0]
                    attempts = 1 if status != "failed" else rng.randint(2, 5)
                    response_status = 200 if status == "success" else (500 if status == "failed" else None)
                    last_error = None if status == "success" else ("connect timeout" if status == "failed" else None)
                    delivered_at = created + timedelta(seconds=rng.uniform(0.2, 30)) if status == "success" else None
                    payload = json.dumps(
                        {
                            "id": str(new_uuid(rng)),
                            "event": event,
                            "organization_id": str(new_uuid(rng)),
                            "created_at": created.isoformat(),
                            "data": {"task_id": str(new_uuid(rng)), "title": rng.choice(TASK_OBJECTS)},
                        }
                    )
                    yield (
                        new_uuid(rng), webhook_id, event, payload, status, attempts,
                        response_status, last_error, delivered_at, created, None,
                    )

        self.counts["webhook_deliveries"] = copy_rows(self.cur, "webhook_deliveries", columns, rows())

    def analyze(self) -> None:
        tables = ", ".join(self.counts)
        if tables:
            self.cur.execute(f"ANALYZE {tables}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed TeamFlow with heavy mock data.")
    parser.add_argument("--preset", choices=PRESETS, default="heavy")
    parser.add_argument("--users", type=int)
    parser.add_argument("--orgs", type=int)
    parser.add_argument("--tasks-per-org", type=int)
    parser.add_argument("--reset", action="store_true", help="truncate all tables first")
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--password", default="Password123!")
    parser.add_argument("--dsn", help="override the database URL")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = dict(PRESETS[args.preset])
    if args.users:
        cfg["users"] = args.users
    if args.orgs:
        cfg["orgs"] = args.orgs
    if args.tasks_per_org:
        cfg["tasks_per_org"] = args.tasks_per_org

    dsn = (args.dsn or settings.sync_database_url).replace("postgresql+psycopg", "postgresql").replace(
        "postgresql+asyncpg", "postgresql"
    )

    print(f"preset={args.preset} users={cfg['users']} orgs={cfg['orgs']} tasks/org={cfg['tasks_per_org']}")
    print(f"dsn={dsn.split('@')[-1]} reset={args.reset} seed={args.seed}")

    rng = random.Random(args.seed)
    started = time.perf_counter()
    with psycopg.connect(dsn) as conn:
        conn.execute("SET synchronous_commit = off")
        seeder = Seeder(conn, rng, cfg, hash_password(args.password))

        if args.reset:
            seeder.reset()

        step = time.perf_counter()
        users = seeder.load_users()
        print(f"  users                {seeder.counts['users']:>9,}  ({time.perf_counter() - step:.1f}s)", flush=True)

        step = time.perf_counter()
        orgs, _, member_lists, user_orgs = seeder.load_orgs_members(users)
        print(f"  organizations        {seeder.counts['organizations']:>9,}  ({time.perf_counter() - step:.1f}s)", flush=True)
        print(f"  memberships          {seeder.counts['memberships']:>9,}  ({time.perf_counter() - step:.1f}s)", flush=True)

        step = time.perf_counter()
        projects_by_org, labels_by_org = seeder.load_projects_labels(orgs, member_lists)
        print(f"  projects             {seeder.counts['projects']:>9,}  ({time.perf_counter() - step:.1f}s)", flush=True)
        print(f"  labels               {seeder.counts['labels']:>9,}  ({time.perf_counter() - step:.1f}s)", flush=True)

        step = time.perf_counter()
        sprints_by_project, releases_by_project = seeder.load_sprints_releases(
            orgs, member_lists, projects_by_org
        )
        print(f"  sprints              {seeder.counts['sprints']:>9,}  ({time.perf_counter() - step:.1f}s)", flush=True)
        print(f"  releases             {seeder.counts['releases']:>9,}  ({time.perf_counter() - step:.1f}s)", flush=True)

        step = time.perf_counter()
        tasks_meta, tasks_by_org = seeder.load_tasks(
            orgs, member_lists, projects_by_org, labels_by_org,
            sprints_by_project, releases_by_project,
        )
        print(f"  tasks                {seeder.counts['tasks']:>9,}  ({time.perf_counter() - step:.1f}s)", flush=True)

        org_index_by_id = {str(org[0]): index for index, org in enumerate(orgs)}

        step = time.perf_counter()
        seeder.load_task_labels(tasks_meta)
        seeder.load_watchers(tasks_meta, member_lists, org_index_by_id)
        print(f"  task_labels          {seeder.counts['task_labels']:>9,}  ({time.perf_counter() - step:.1f}s)", flush=True)
        print(f"  task_watchers        {seeder.counts['task_watchers']:>9,}  ({time.perf_counter() - step:.1f}s)", flush=True)

        step = time.perf_counter()
        reaction_candidates = seeder.load_comments(tasks_meta, member_lists, org_index_by_id)
        print(f"  comments             {seeder.counts['comments']:>9,}  ({time.perf_counter() - step:.1f}s)", flush=True)

        step = time.perf_counter()
        seeder.load_reactions(reaction_candidates)
        print(f"  comment_reactions    {seeder.counts['comment_reactions']:>9,}  ({time.perf_counter() - step:.1f}s)", flush=True)

        step = time.perf_counter()
        seeder.load_activities(tasks_meta, member_lists, org_index_by_id)
        print(f"  activities           {seeder.counts['activities']:>9,}  ({time.perf_counter() - step:.1f}s)", flush=True)

        step = time.perf_counter()
        seeder.load_attachments(tasks_meta, member_lists, org_index_by_id)
        print(f"  attachments          {seeder.counts['attachments']:>9,}  ({time.perf_counter() - step:.1f}s)", flush=True)

        step = time.perf_counter()
        seeder.load_notifications(users, tasks_by_org, user_orgs)
        print(f"  notifications        {seeder.counts['notifications']:>9,}  ({time.perf_counter() - step:.1f}s)", flush=True)

        step = time.perf_counter()
        seeder.load_audit_logs(tasks_meta, member_lists, org_index_by_id)
        print(f"  audit_logs           {seeder.counts['audit_logs']:>9,}  ({time.perf_counter() - step:.1f}s)", flush=True)

        step = time.perf_counter()
        seeder.load_invitations(orgs, member_lists)
        print(f"  invitations          {seeder.counts['invitations']:>9,}  ({time.perf_counter() - step:.1f}s)", flush=True)

        step = time.perf_counter()
        webhook_ids = seeder.load_webhooks(orgs, member_lists)
        seeder.load_deliveries(webhook_ids)
        print(f"  webhooks             {seeder.counts['webhooks']:>9,}  ({time.perf_counter() - step:.1f}s)", flush=True)
        print(f"  webhook_deliveries   {seeder.counts['webhook_deliveries']:>9,}  ({time.perf_counter() - step:.1f}s)", flush=True)

        step = time.perf_counter()
        seeder.analyze()
        conn.commit()
        print(f"  ANALYZE + commit     {'':>9}  ({time.perf_counter() - step:.1f}s)", flush=True)

    total = sum(seeder.counts.values())
    print()
    print(f"done: {total:,} rows in {time.perf_counter() - started:.1f}s")
    print(f"sample login: {seeder.sample_email} / {args.password}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
