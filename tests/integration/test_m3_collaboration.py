"""Integration tests for M3 collaboration: threaded comments, reactions,
activity feeds and notification mutes (#21, #25)."""

import pytest

from tests.utils import auth_headers, make_org, make_project, make_task, make_user

ALICE = "m3c-alice@example.com"
BEN = "m3c-ben@example.com"
SLUG = "m3c-org"


@pytest.fixture
async def board(client):
    alice = await make_user(client, email=ALICE, full_name="Alice")
    ben = await make_user(client, email=BEN, full_name="Ben")
    await make_org(client, alice, name="M3 Collab", slug=SLUG)
    project = await make_project(client, alice, SLUG, name="Collab Board")
    r = await client.post(
        f"/api/v1/organizations/{SLUG}/members",
        json={"user_email": BEN, "role": "member"},
        headers=await auth_headers(alice),
    )
    assert r.status_code == 201, r.text
    return {"alice": alice, "ben": ben, "project": project}


async def _add_member(client, actor, email, role="member") -> str:
    r = await client.post(
        f"/api/v1/organizations/{SLUG}/members",
        json={"user_email": email, "role": role},
        headers=await auth_headers(actor),
    )
    assert r.status_code == 201, r.text
    return r.json()["user_id"]


@pytest.mark.asyncio
async def test_threaded_comments_and_reactions(client, board):
    alice, ben, project = board["alice"], board["ben"], board["project"]
    task = await make_task(client, alice, project["id"], title="Threaded task")
    HA, HB = await auth_headers(alice), await auth_headers(ben)

    root = (
        await client.post(
            f"/api/v1/tasks/{task['id']}/comments",
            json={"body": "Kick-off notes"},
            headers=HB,
        )
    ).json()
    reply = (
        await client.post(
            f"/api/v1/tasks/{task['id']}/comments",
            json={"body": "Looks good", "parent_id": root["id"]},
            headers=HA,
        )
    ).json()
    nested = (
        await client.post(
            f"/api/v1/tasks/{task['id']}/comments",
            json={"body": "Agreed", "parent_id": reply["id"]},
            headers=HB,
        )
    ).json()

    # Deep replies flatten onto the thread root.
    assert nested["root_id"] == root["id"]
    assert nested["parent_id"] == reply["id"]

    comments = (
        await client.get(f"/api/v1/tasks/{task['id']}/comments", headers=HA)
    ).json()
    assert len(comments) == 3
    by_id = {entry["id"]: entry for entry in comments}
    assert by_id[root["id"]]["reply_count"] == 2
    assert by_id[root["id"]]["root_id"] is None

    # parent must belong to the same task
    other = await make_task(client, alice, project["id"], title="Other task")
    r = await client.post(
        f"/api/v1/tasks/{other['id']}/comments",
        json={"body": "cross-task reply", "parent_id": root["id"]},
        headers=HA,
    )
    assert r.status_code == 422

    # --- reactions -------------------------------------------------------
    r = await client.post(
        f"/api/v1/comments/{root['id']}/reactions", json={"emoji": "👍"}, headers=HA
    )
    assert r.status_code == 201, r.text
    assert r.json()["count"] == 1
    r = await client.post(
        f"/api/v1/comments/{root['id']}/reactions", json={"emoji": "👍"}, headers=HB
    )
    assert r.json()["count"] == 2

    comments = (
        await client.get(f"/api/v1/tasks/{task['id']}/comments", headers=HA)
    ).json()
    root_read = next(entry for entry in comments if entry["id"] == root["id"])
    summary = next(entry for entry in root_read["reactions"] if entry["emoji"] == "👍")
    assert summary["count"] == 2 and len(summary["user_ids"]) == 2

    r = await client.delete(
        f"/api/v1/comments/{root['id']}/reactions/%F0%9F%91%8D", headers=HA
    )
    assert r.status_code == 204, r.text
    comments = (
        await client.get(f"/api/v1/tasks/{task['id']}/comments", headers=HB)
    ).json()
    root_read = next(entry for entry in comments if entry["id"] == root["id"])
    assert next(e for e in root_read["reactions"] if e["emoji"] == "👍")["count"] == 1

    r = await client.post(
        f"/api/v1/comments/{root['id']}/reactions", json={"emoji": "🎲"}, headers=HA
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_task_and_project_activity_feeds(client, board):
    alice, ben, project = board["alice"], board["ben"], board["project"]
    HA, HB = await auth_headers(alice), await auth_headers(ben)
    task = await make_task(client, alice, project["id"], title="Activity task")

    await client.patch(
        f"/api/v1/tasks/{task['id']}", json={"priority": "high"}, headers=HA
    )
    await client.post(
        f"/api/v1/tasks/{task['id']}/comments",
        json={"body": "Moving this along"},
        headers=HB,
    )

    activity = (
        await client.get(f"/api/v1/tasks/{task['id']}/activity", headers=HA)
    ).json()
    verbs = {entry["verb"] for entry in activity}
    assert {"task_created", "task_updated", "comment_created"} <= verbs
    assert all(entry["project_id"] == project["id"] for entry in activity)

    project_activity = (
        await client.get(f"/api/v1/projects/{project['id']}/activity", headers=HA)
    ).json()
    assert any(entry["task_id"] == task["id"] for entry in project_activity)

    org_activity = (
        await client.get(f"/api/v1/organizations/{SLUG}/activity", headers=HA)
    ).json()
    assert org_activity


@pytest.mark.asyncio
async def test_project_mutes_suppress_notifications(client, board):
    alice, ben, project = board["alice"], board["ben"], board["project"]
    HA = await auth_headers(alice)
    task = await make_task(client, alice, project["id"], title="Muted task")

    async def comment_notifications(actor) -> list[dict]:
        entries = (
            await client.get(
                "/api/v1/notifications?limit=100", headers=await auth_headers(actor)
            )
        ).json()["items"]
        return [
            entry
            for entry in entries
            if entry["type"] == "comment_created" and entry["task_id"] == task["id"]
        ]

    await client.post(
        f"/api/v1/tasks/{task['id']}/comments",
        json={"body": "First comment"},
        headers=await auth_headers(ben),
    )
    first = await comment_notifications(alice)
    assert len(first) == 1
    assert first[0]["project_id"] == project["id"]

    r = await client.post(
        "/api/v1/notifications/mutes",
        json={"project_id": project["id"]},
        headers=HA,
    )
    assert r.status_code == 201, r.text

    await client.post(
        f"/api/v1/tasks/{task['id']}/comments",
        json={"body": "Second comment"},
        headers=await auth_headers(ben),
    )
    assert len(await comment_notifications(alice)) == 1  # suppressed

    mutes = (await client.get("/api/v1/notifications/mutes", headers=HA)).json()
    assert any(entry["project_id"] == project["id"] for entry in mutes)

    r = await client.delete(
        f"/api/v1/notifications/mutes/{project['id']}", headers=HA
    )
    assert r.status_code == 204

    await client.post(
        f"/api/v1/tasks/{task['id']}/comments",
        json={"body": "Third comment"},
        headers=await auth_headers(ben),
    )
    assert len(await comment_notifications(alice)) == 2
