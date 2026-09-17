"""Integration tests: tasks — CRUD, transitions, queries, watchers, labels."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from tests.utils import auth_headers, make_org, make_project, make_task, make_user

ALICE = "task-alice@example.com"
BOB = "task-bob@example.com"


@pytest.fixture
async def board(client):
    alice = await make_user(client, email=ALICE, full_name="Alice")
    bob = await make_user(client, email=BOB, full_name="Bob")
    org = await make_org(client, alice, name="Task Org", slug="task-org")
    project = await make_project(client, alice, "task-org", name="Board")
    return {"alice": alice, "bob": bob, "org": org, "project": project}


async def _invite(client, owner, email, role="member", slug="task-org"):
    await client.post(
        f"/api/v1/organizations/{slug}/invitations",
        json={"email": email, "role": role},
        headers=await auth_headers(owner),
    )
    invitee = await make_user(client, email=email)
    invs = (await client.get("/api/v1/invitations/me", headers=await auth_headers(invitee))).json()
    r = await client.post(
        f"/api/v1/invitations/{invs[0]['id']}/accept", headers=await auth_headers(invitee)
    )
    assert r.status_code == 200
    return invitee


@pytest.mark.asyncio
async def test_task_crud_with_labels_and_assignee(client, board):
    alice, project = board["alice"], board["project"]
    await _invite(client, alice, BOB)
    bob_id = None
    members = (await client.get(
        "/api/v1/organizations/task-org/members", headers=await auth_headers(alice)
    )).json()
    bob_id = next(m["user_id"] for m in members if m["user"]["email"] == BOB)

    label = (await client.post(
        "/api/v1/organizations/task-org/labels",
        json={"name": "backend", "color": "#00AA00"},
        headers=await auth_headers(alice),
    )).json()

    r = await client.post(
        f"/api/v1/projects/{project['id']}/tasks",
        json={
            "title": "Implement payments",
            "description": "Stripe checkout",
            "priority": "high",
            "assignee_id": bob_id,
            "label_ids": [label["id"]],
            "due_date": datetime.now(UTC).isoformat(),
        },
        headers=await auth_headers(alice),
    )
    assert r.status_code == 201, r.text
    task = r.json()
    assert task["status"] == "todo"
    assert task["priority"] == "high"
    assert task["assignee"]["id"] == bob_id
    assert [lbl["name"] for lbl in task["labels"]] == ["backend"]
    # creator + assignee auto-watch
    assert set(task["watcher_ids"]) == {task["created_by_id"], bob_id}

    # cross-org label id -> 422
    await make_org(client, alice, name="Other", slug="other-org")
    other_project = await make_project(client, alice, "other-org")
    r = await client.post(
        f"/api/v1/projects/{other_project['id']}/tasks",
        json={"title": "x", "label_ids": [label["id"]]},
        headers=await auth_headers(alice),
    )
    assert r.status_code == 422

    # assignee outside org -> 422
    r = await client.post(
        f"/api/v1/projects/{project['id']}/tasks",
        json={"title": "x", "assignee_id": str(uuid.uuid4())},
        headers=await auth_headers(alice),
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_invalid_status_transitions_rejected(client, board):
    alice, project = board["alice"], board["project"]
    task = await make_task(client, alice, project["id"], title="Transition test")
    H = await auth_headers(alice)

    r = await client.post(f"/api/v1/tasks/{task['id']}/move", json={"status": "done"}, headers=H)
    assert r.status_code == 422
    r = await client.post(f"/api/v1/tasks/{task['id']}/move", json={"status": "in_review"}, headers=H)
    assert r.status_code == 422

    # legal path
    for status in ("in_progress", "in_review", "done"):
        r = await client.post(f"/api/v1/tasks/{task['id']}/move", json={"status": status}, headers=H)
        assert r.status_code == 200, r.text
    r = await client.get(f"/api/v1/tasks/{task['id']}", headers=H)
    assert r.json()["status"] == "done"
    assert r.json()["completed_at"] is not None

    # reopen
    r = await client.post(f"/api/v1/tasks/{task['id']}/move", json={"status": "in_progress"}, headers=H)
    assert r.status_code == 200
    r = await client.get(f"/api/v1/tasks/{task['id']}", headers=H)
    assert r.json()["completed_at"] is None


@pytest.mark.asyncio
async def test_task_filters_sort_pagination(client, board):
    alice, project = board["alice"], board["project"]
    H = await auth_headers(alice)
    await make_task(client, alice, project["id"], "Alpha payment", priority="high")
    await make_task(client, alice, project["id"], "Beta refactoring", priority="low")
    await make_task(client, alice, project["id"], "Gamma payments api", priority="urgent")
    t4 = await make_task(client, alice, project["id"], "Delta archived")
    await client.post(f"/api/v1/tasks/{t4['id']}/move", json={"status": "in_progress"}, headers=H)

    r = await client.get(
        "/api/v1/organizations/task-org/tasks?search=payment&sort=-priority", headers=H
    )
    body = r.json()
    assert body["total"] == 2
    titles = [t["title"] for t in body["items"]]
    assert "Alpha payment" in titles and "Gamma payments api" in titles

    r = await client.get("/api/v1/organizations/task-org/tasks?status=todo&status=in_progress", headers=H)
    assert r.json()["total"] == 4

    r = await client.get("/api/v1/organizations/task-org/tasks?priority=low", headers=H)
    assert r.json()["total"] == 1

    r = await client.get("/api/v1/organizations/task-org/tasks?sort=title&offset=1&limit=2", headers=H)
    body = r.json()
    assert body["limit"] == 2 and body["offset"] == 1
    assert [t["title"] for t in body["items"]] == ["Beta refactoring", "Delta archived"]

    # overdue filter
    overdue = await make_task(
        client, alice, project["id"],
        due_date=(datetime.now(UTC) - timedelta(days=2)).isoformat(),
    )
    r = await client.get("/api/v1/organizations/task-org/tasks?overdue=true", headers=H)
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["id"] == overdue["id"]


@pytest.mark.asyncio
async def test_task_tenant_isolation_idor(client, board):
    alice, project = board["alice"], board["project"]
    task = await make_task(client, alice, project["id"], "Secret task")

    outsider = await make_user(client, email="task-outsider@example.com")
    OH = await auth_headers(outsider)
    assert (await client.get(f"/api/v1/tasks/{task['id']}", headers=OH)).status_code == 404
    assert (
        await client.patch(
            f"/api/v1/tasks/{task['id']}", json={"title": "hacked"}, headers=OH
        )
    ).status_code == 404
    assert (
        await client.delete(f"/api/v1/tasks/{task['id']}", headers=OH)
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/tasks/{task['id']}/comments", headers=OH)
    ).status_code == 404
    # random task id -> 404 too
    assert (
        await client.get(
            f"/api/v1/tasks/{uuid.uuid4()}", headers=await auth_headers(alice)
        )
    ).status_code == 404


@pytest.mark.asyncio
async def test_task_delete_permissions(client, board):
    alice, project = board["alice"], board["project"]
    member = await _invite(client, alice, "task-member-del@example.com")
    task = await make_task(client, alice, project["id"], "To be deleted")

    # member cannot delete someone else's task
    r = await client.delete(f"/api/v1/tasks/{task['id']}", headers=await auth_headers(member))
    assert r.status_code == 403

    # member CAN delete their own task
    own = await make_task(client, member, project["id"], "Mine")
    r = await client.delete(f"/api/v1/tasks/{own['id']}", headers=await auth_headers(member))
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_watchers_opt_in_and_out(client, board):
    alice, project = board["alice"], board["project"]
    bob = await _invite(client, alice, BOB)
    task = await make_task(client, alice, project["id"], "Watch me")

    r = await client.post(
        f"/api/v1/tasks/{task['id']}/watchers/me", headers=await auth_headers(bob)
    )
    assert r.status_code == 204
    watchers = (await client.get(
        f"/api/v1/tasks/{task['id']}/watchers", headers=await auth_headers(alice)
    )).json()
    assert BOB in [w["email"] for w in watchers]

    r = await client.delete(
        f"/api/v1/tasks/{task['id']}/watchers/me", headers=await auth_headers(bob)
    )
    assert r.status_code == 204
    watchers = (await client.get(
        f"/api/v1/tasks/{task['id']}/watchers", headers=await auth_headers(alice)
    )).json()
    assert BOB not in [w["email"] for w in watchers]


@pytest.mark.asyncio
async def test_comment_lifecycle_and_mentions(client, board):
    alice, project = board["alice"], board["project"]
    bob = await _invite(client, alice, BOB)
    task = await make_task(client, alice, project["id"], "Comment test")

    r = await client.post(
        f"/api/v1/tasks/{task['id']}/comments",
        json={"body": f"hey {BOB}, take a look"},
        headers=await auth_headers(alice),
    )
    assert r.status_code == 201
    comment = r.json()
    assert comment["author"]["email"] == ALICE

    # bob gets mention + comment notification (he was mentioned AND is not a watcher)
    r = await client.get("/api/v1/notifications", headers=await auth_headers(bob))
    types = [n["type"] for n in r.json()["items"]]
    assert "mention" in types

    # author edits own comment
    r = await client.patch(
        f"/api/v1/comments/{comment['id']}",
        json={"body": "updated body"},
        headers=await auth_headers(alice),
    )
    assert r.status_code == 200

    # bob (not author, plain member) cannot edit
    r = await client.patch(
        f"/api/v1/comments/{comment['id']}",
        json={"body": "vandalized"},
        headers=await auth_headers(bob),
    )
    assert r.status_code == 403

    r = await client.delete(
        f"/api/v1/comments/{comment['id']}", headers=await auth_headers(alice)
    )
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_label_crud_and_uniqueness(client, board):
    alice = board["alice"]
    board_project = board["project"]
    H = await auth_headers(alice)

    label = (await client.post(
        "/api/v1/organizations/task-org/labels",
        json={"name": "urgent"},
        headers=H,
    )).json()
    r = await client.post(
        "/api/v1/organizations/task-org/labels",
        json={"name": "urgent"},
        headers=H,
    )
    assert r.status_code == 409

    r = await client.post(
        "/api/v1/organizations/task-org/labels",
        json={"name": "bad color", "color": "red"},
        headers=H,
    )
    assert r.status_code == 422

    labels = (await client.get("/api/v1/organizations/task-org/labels", headers=H)).json()
    assert {lbl["name"] for lbl in labels} == {"urgent"}

    # assign to a task then unassign
    task = await make_task(client, alice, board_project["id"], "Label me")
    r = await client.post(
        f"/api/v1/tasks/{task['id']}/labels",
        json={"label_id": label["id"]},
        headers=H,
    )
    assert r.status_code == 201, r.text
    assert [lbl["name"] for lbl in r.json()] == ["urgent"]

    r = await client.delete(f"/api/v1/tasks/{task['id']}/labels/{label['id']}", headers=H)
    assert r.status_code == 204

    label_id = label["id"]
    r = await client.patch(f"/api/v1/labels/{label_id}", json={"color": "#123456"}, headers=H)
    assert r.status_code == 200
    r = await client.delete(f"/api/v1/labels/{label_id}", headers=H)
    assert r.status_code == 204
