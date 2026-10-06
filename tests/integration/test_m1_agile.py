"""Integration tests for M1: issue keys, estimates, sprints/backlog, TeamQL,
saved filters, global search, bulk operations, notification preferences,
member.joined webhooks and task.completed notifications."""

import pytest

from tests.utils import auth_headers, make_org, make_project, make_task, make_user

ALICE = "m1-alice@example.com"
BOB = "m1-bob@example.com"
SLUG = "m1-org"


@pytest.fixture
async def board(client):
    alice = await make_user(client, email=ALICE, full_name="Alice")
    bob = await make_user(client, email=BOB, full_name="Bob")
    org = await make_org(client, alice, name="M1 Org", slug=SLUG)
    project = await make_project(client, alice, SLUG, name="M1 Board")
    return {"alice": alice, "bob": bob, "org": org, "project": project}


async def _add_bob(client, alice, slug=SLUG) -> str:
    r = await client.post(
        f"/api/v1/organizations/{slug}/members",
        json={"user_email": BOB, "role": "member"},
        headers=await auth_headers(alice),
    )
    assert r.status_code == 201, r.text
    return r.json()["user_id"]


@pytest.mark.asyncio
async def test_issue_keys_are_sequential_and_stable(client, board):
    alice, project = board["alice"], board["project"]
    assert project["key"] == "M1BO"

    first = await make_task(client, alice, project["id"], title="First")
    second = await make_task(client, alice, project["id"], title="Second")
    assert first["key"] == "M1BO-1"
    assert second["key"] == "M1BO-2"

    r = await client.post(
        f"/api/v1/organizations/{SLUG}/tasks/bulk",
        json={"task_ids": [first["id"]], "action": "clone"},
        headers=await auth_headers(alice),
    )
    assert r.status_code == 200, r.text
    clone_id = r.json()["created_ids"][0]
    clone = (await client.get(f"/api/v1/tasks/{clone_id}", headers=await auth_headers(alice))).json()
    assert clone["key"] == "M1BO-3"
    assert clone["title"] == "First (copy)"

    # Renaming the key prefix only affects new issues.
    r = await client.patch(
        f"/api/v1/projects/{project['id']}",
        json={"key": "ENG"},
        headers=await auth_headers(alice),
    )
    assert r.status_code == 200, r.text
    third = await make_task(client, alice, project["id"], title="Third")
    assert third["key"] == "ENG-4"
    assert (await client.get(f"/api/v1/tasks/{first['id']}", headers=await auth_headers(alice))).json()[
        "key"
    ] == "M1BO-1"


@pytest.mark.asyncio
async def test_estimates_surface_on_tasks_and_sprints(client, board):
    alice, project = board["alice"], board["project"]
    task = await make_task(
        client, alice, project["id"], title="Sized", estimate=5, remaining_estimate=3
    )
    assert task["estimate"] == 5
    assert task["remaining_estimate"] == 3

    sprint = (
        await client.post(
            f"/api/v1/projects/{project['id']}/sprints",
            json={"name": "Sprint 1", "goal": "Ship estimates"},
            headers=await auth_headers(alice),
        )
    ).json()
    r = await client.patch(
        f"/api/v1/tasks/{task['id']}",
        json={"sprint_id": sprint["id"], "actual_estimate": 2},
        headers=await auth_headers(alice),
    )
    assert r.status_code == 200, r.text

    sprints = (
        await client.get(
            f"/api/v1/projects/{project['id']}/sprints",
            headers=await auth_headers(alice),
        )
    ).json()
    assert sprints[0]["total_estimate"] == 5

    # Configurable estimation unit at project level.
    r = await client.patch(
        f"/api/v1/projects/{project['id']}",
        json={"estimation_unit": "hours"},
        headers=await auth_headers(alice),
    )
    assert r.status_code == 200 and r.json()["estimation_unit"] == "hours"

    # TeamQL aggregates are queryable.
    r = await client.get(
        f"/api/v1/organizations/{SLUG}/tasks/query",
        params={"q": "estimate >= 5"},
        headers=await auth_headers(alice),
    )
    assert r.status_code == 200, r.text
    assert [item["id"] for item in r.json()["items"]] == [task["id"]]


@pytest.mark.asyncio
async def test_sprint_lifecycle_and_carry_over(client, board):
    alice, project = board["alice"], board["project"]
    H = await auth_headers(alice)
    sprint_a = (
        await client.post(
            f"/api/v1/projects/{project['id']}/sprints", json={"name": "A"}, headers=H
        )
    ).json()
    sprint_b = (
        await client.post(
            f"/api/v1/projects/{project['id']}/sprints", json={"name": "B"}, headers=H
        )
    ).json()
    unfinished = await make_task(client, alice, project["id"], title="Carry me")
    finished = await make_task(client, alice, project["id"], title="Finish me")
    backlog_task = await make_task(client, alice, project["id"], title="No sprint")
    for task in (unfinished, finished):
        r = await client.patch(
            f"/api/v1/tasks/{task['id']}",
            json={"sprint_id": sprint_a["id"]},
            headers=H,
        )
        assert r.status_code == 200, r.text
    for status in ("in_progress", "in_review", "done"):
        r = await client.post(f"/api/v1/tasks/{finished['id']}/move", json={"status": status}, headers=H)
        assert r.status_code == 200, r.text

    # Board sprint filter.
    r = await client.get(
        f"/api/v1/organizations/{SLUG}/tasks",
        params={"project_id": project["id"], "sprint_id": sprint_a["id"]},
        headers=H,
    )
    assert r.json()["total"] == 2

    # Backlog excludes sprinted tasks and keeps manual order.
    r = await client.get(f"/api/v1/projects/{project['id']}/sprints/backlog", headers=H)
    assert [item["id"] for item in r.json()["items"]] == [backlog_task["id"]]

    r = await client.post(f"/api/v1/sprints/{sprint_a['id']}/start", headers=H)
    assert r.status_code == 200 and r.json()["state"] == "active"

    # Only one active sprint per project.
    sprint_c = (
        await client.post(
            f"/api/v1/projects/{project['id']}/sprints", json={"name": "C"}, headers=H
        )
    ).json()
    r = await client.post(f"/api/v1/sprints/{sprint_c['id']}/start", headers=H)
    assert r.status_code == 422

    r = await client.post(
        f"/api/v1/sprints/{sprint_a['id']}/complete",
        json={"carry_over_sprint_id": sprint_b["id"]},
        headers=H,
    )
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "completed"
    assert r.json()["carried_over_count"] == 1

    moved = (await client.get(f"/api/v1/tasks/{unfinished['id']}", headers=H)).json()
    assert moved["sprint_id"] == sprint_b["id"]
    kept = (await client.get(f"/api/v1/tasks/{finished['id']}", headers=H)).json()
    assert kept["sprint_id"] == sprint_a["id"]


@pytest.mark.asyncio
async def test_teamql_saved_filters(client, board):
    alice, project = board["alice"], board["project"]
    H = await auth_headers(alice)
    await make_task(client, alice, project["id"], title="Urgent", priority="high")
    await make_task(client, alice, project["id"], title="Chill", priority="low")

    r = await client.get(
        f"/api/v1/organizations/{SLUG}/tasks/query",
        params={"q": "status = todo AND priority = high ORDER BY title"},
        headers=H,
    )
    assert r.status_code == 200, r.text
    assert [item["title"] for item in r.json()["items"]] == ["Urgent"]

    r = await client.post(
        f"/api/v1/organizations/{SLUG}/saved-filters",
        json={"name": "High todo", "query": "status = todo AND priority = high"},
        headers=H,
    )
    assert r.status_code == 201, r.text
    saved = r.json()

    r = await client.post(
        f"/api/v1/organizations/{SLUG}/saved-filters",
        json={"name": "High todo", "query": "status = todo"},
        headers=H,
    )
    assert r.status_code == 409

    r = await client.post(
        f"/api/v1/organizations/{SLUG}/saved-filters",
        json={"name": "Broken", "query": "nonsense = 1"},
        headers=H,
    )
    assert r.status_code == 422

    r = await client.get(f"/api/v1/organizations/{SLUG}/saved-filters", headers=H)
    assert [entry["name"] for entry in r.json()] == ["High todo"]

    r = await client.patch(
        f"/api/v1/organizations/{SLUG}/saved-filters/{saved['id']}",
        json={"is_shared": True},
        headers=H,
    )
    assert r.status_code == 200 and r.json()["is_shared"] is True

    r = await client.delete(
        f"/api/v1/organizations/{SLUG}/saved-filters/{saved['id']}", headers=H
    )
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_global_search_covers_tasks_comments_projects(client, board):
    alice, project = board["alice"], board["project"]
    H = await auth_headers(alice)
    task = await make_task(
        client, alice, project["id"], title="Migration", description="flamingo rollout plan"
    )
    await client.post(
        f"/api/v1/tasks/{task['id']}/comments",
        json={"body": "penguin spotted in the logs"},
        headers=H,
    )

    r = await client.get(
        f"/api/v1/organizations/{SLUG}/search", params={"q": "flamingo"}, headers=H
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert [hit["id"] for hit in body["tasks"]] == [task["id"]]

    r = await client.get(
        f"/api/v1/organizations/{SLUG}/search", params={"q": "penguin"}, headers=H
    )
    assert [hit["task_id"] for hit in r.json()["comments"]] == [task["id"]]

    r = await client.get(
        f"/api/v1/organizations/{SLUG}/search", params={"q": "M1 Board"}, headers=H
    )
    assert [hit["id"] for hit in r.json()["projects"]] == [project["id"]]


@pytest.mark.asyncio
async def test_bulk_operations(client, board):
    alice, project = board["alice"], board["project"]
    H = await auth_headers(alice)
    tasks = [await make_task(client, alice, project["id"], title=f"Bulk {i}") for i in range(3)]
    ids = [task["id"] for task in tasks]

    r = await client.post(
        f"/api/v1/organizations/{SLUG}/tasks/bulk",
        json={"task_ids": ids, "action": "update", "priority": "high", "estimate": 2},
        headers=H,
    )
    assert r.status_code == 200 and r.json()["updated"] == 3

    r = await client.post(
        f"/api/v1/organizations/{SLUG}/tasks/bulk",
        json={"task_ids": ids, "action": "move", "status": "in_progress"},
        headers=H,
    )
    assert r.json()["updated"] == 3

    r = await client.post(
        f"/api/v1/organizations/{SLUG}/tasks/bulk",
        json={"task_ids": ids, "action": "archive"},
        headers=H,
    )
    assert r.json()["updated"] == 3
    r = await client.get(
        f"/api/v1/organizations/{SLUG}/tasks", params={"project_id": project["id"]}, headers=H
    )
    assert r.json()["total"] == 0
    r = await client.get(
        f"/api/v1/organizations/{SLUG}/tasks",
        params={"project_id": project["id"], "archived_only": True},
        headers=H,
    )
    assert r.json()["total"] == 3

    r = await client.post(
        f"/api/v1/organizations/{SLUG}/tasks/bulk",
        json={"task_ids": ids, "action": "restore"},
        headers=H,
    )
    assert r.json()["updated"] == 3

    other = await make_project(client, alice, SLUG, name="Other Board")
    r = await client.post(
        f"/api/v1/organizations/{SLUG}/tasks/bulk",
        json={"task_ids": ids, "action": "move_project", "project_id": other["id"]},
        headers=H,
    )
    assert r.status_code == 200 and r.json()["updated"] == 3
    moved = (await client.get(f"/api/v1/tasks/{ids[0]}", headers=H)).json()
    assert moved["project_id"] == other["id"]
    assert moved["key"].startswith(f"{other['key']}-")

    r = await client.post(
        f"/api/v1/organizations/{SLUG}/tasks/bulk",
        json={"task_ids": ids, "action": "delete"},
        headers=H,
    )
    assert r.json()["updated"] == 3
    assert (await client.get(f"/api/v1/tasks/{ids[0]}", headers=H)).status_code == 404


@pytest.mark.asyncio
async def test_notification_preferences_and_unsubscribe(client, board):
    alice = board["alice"]
    H = await auth_headers(alice)

    r = await client.get("/api/v1/auth/me/notification-preferences", headers=H)
    assert r.status_code == 200, r.text
    prefs = r.json()
    assert prefs["assigned"] is True and prefs["comments"] is False
    token = prefs["unsubscribe_url"].split("token=")[-1]

    r = await client.put(
        "/api/v1/auth/me/notification-preferences",
        json={"comments": True, "digest": "daily"},
        headers=H,
    )
    assert r.status_code == 200 and r.json()["comments"] is True
    assert r.json()["digest"] == "daily"

    r = await client.post(f"/api/v1/auth/unsubscribe?token={token}")
    assert r.status_code == 200
    r = await client.get("/api/v1/auth/me/notification-preferences", headers=H)
    assert r.json()["email_enabled"] is False


@pytest.mark.asyncio
async def test_member_joined_webhook_is_dispatched(client, board):
    alice = board["alice"]
    H = await auth_headers(alice)
    webhook = (
        await client.post(
            f"/api/v1/organizations/{SLUG}/webhooks",
            json={"url": "http://localhost:9/hook", "events": ["member.joined"]},
            headers=H,
        )
    ).json()

    await _add_bob(client, alice)

    deliveries = (
        await client.get(
            f"/api/v1/organizations/{SLUG}/webhooks/{webhook['id']}/deliveries",
            headers=H,
        )
    ).json()
    assert [entry["event"] for entry in deliveries] == ["member.joined"]


@pytest.mark.asyncio
async def test_task_completed_notification_is_emitted(client, board):
    alice, project = board["alice"], board["project"]
    bob_id = await _add_bob(client, alice)
    H = await auth_headers(alice)
    task = await make_task(
        client, alice, project["id"], title="Complete me", assignee_id=bob_id
    )
    for status in ("in_progress", "in_review", "done"):
        r = await client.post(f"/api/v1/tasks/{task['id']}/move", json={"status": status}, headers=H)
        assert r.status_code == 200, r.text

    bob = board["bob"]
    r = await client.get("/api/v1/notifications", headers=await auth_headers(bob))
    types = [entry["type"] for entry in r.json()["items"]]
    assert "task_completed" in types
