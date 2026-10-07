"""Performance budgets: SQL-statement counts per hot-path request (M3 #37).

Budgets catch N+1 regressions in review instead of production. They are
deliberately a bit loose (batched projections legitimately issue a handful of
queries) but tight enough that an accidental per-row query fails the test.
"""

import pytest
from sqlalchemy import event

from app.core.db import engine
from tests.utils import auth_headers, make_org, make_project, make_task, make_user

ALICE = "m3p-alice@example.com"
SLUG = "m3p-org"


@pytest.fixture
async def board(client):
    alice = await make_user(client, email=ALICE, full_name="Alice")
    await make_org(client, alice, name="M3 Perf", slug=SLUG)
    project = await make_project(client, alice, SLUG, name="Perf Board")
    epic = await make_task(client, alice, project["id"], title="Epic", type="epic")
    for index in range(12):
        await make_task(
            client,
            alice,
            project["id"],
            title=f"Task {index}",
            parent_id=epic["id"],
            priority="high" if index % 3 == 0 else "medium",
        )
    return {"alice": alice, "project": project, "epic": epic}


class QueryCounter:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def __enter__(self):
        event.listen(engine.sync_engine, "before_cursor_execute", self._on_query)
        return self

    def __exit__(self, *args):
        event.remove(engine.sync_engine, "before_cursor_execute", self._on_query)

    def _on_query(self, conn, cursor, statement, parameters, context, executemany):
        self.statements.append(statement)

    def reset(self) -> None:
        self.statements.clear()

    @property
    def count(self) -> int:
        return len(self.statements)


async def _request(client, method: str, url: str, headers: dict, **kwargs):
    response = await client.request(method, url, headers=headers, **kwargs)
    assert response.status_code == 200, response.text
    return response


@pytest.mark.asyncio
async def test_query_budgets_for_hot_paths(client, board):
    alice, project = board["alice"], board["project"]
    task = await make_task(client, alice, project["id"], title="Budget task")
    HA = await auth_headers(alice)

    with QueryCounter() as counter:
        await _request(client, "GET", f"/api/v1/tasks/{task['id']}", HA)
        task_detail_queries = counter.count

        counter.reset()
        await _request(client, "GET", f"/api/v1/projects/{project['id']}/tasks/tree", HA)
        tree_queries = counter.count

        counter.reset()
        await _request(
            client,
            "GET",
            f"/api/v1/organizations/{SLUG}/tasks?project_id={project['id']}&limit=25",
            HA,
        )
        list_queries = counter.count

        counter.reset()
        await _request(
            client,
            "GET",
            f"/api/v1/organizations/{SLUG}/tasks/cursor?project_id={project['id']}&limit=25",
            HA,
        )
        cursor_queries = counter.count

        counter.reset()
        await _request(client, "GET", f"/api/v1/projects/{project['id']}/roadmap", HA)
        roadmap_queries = counter.count

        counter.reset()
        await _request(
            client,
            "GET",
            f"/api/v1/organizations/{SLUG}/calendar?project_id={project['id']}",
            HA,
        )
        calendar_queries = counter.count

    budgets = {
        "task_detail": (task_detail_queries, 30),
        "tree": (tree_queries, 15),
        "list": (list_queries, 30),
        "cursor": (cursor_queries, 25),
        "roadmap": (roadmap_queries, 20),
        "calendar": (calendar_queries, 8),
    }
    exceeded = {
        name: actual for name, (actual, budget) in budgets.items() if actual > budget
    }
    assert not exceeded, f"Query budgets exceeded: {exceeded} (budgets: {budgets})"
