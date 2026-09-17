"""Integration tests: notifications inbox + webhooks CRUD + audit trail."""

import pytest

from tests.utils import auth_headers, make_org, make_project, make_task, make_user

OWNER = "notif-owner@example.com"
MEMBER = "notif-member@example.com"


@pytest.mark.asyncio
async def test_assignment_and_comment_notifications(client):
    owner = await make_user(client, email=OWNER, full_name="Notif Owner")
    await make_org(client, owner, name="Notif Org", slug="notif-org")
    project = await make_project(client, owner, "notif-org")

    member = await make_user(client, email=MEMBER)
    await client.post(
        "/api/v1/organizations/notif-org/invitations",
        json={"email": MEMBER, "role": "member"},
        headers=await auth_headers(owner),
    )
    invs = (await client.get("/api/v1/invitations/me", headers=await auth_headers(member))).json()
    await client.post(
        f"/api/v1/invitations/{invs[0]['id']}/accept", headers=await auth_headers(member)
    )
    member_id = None
    members = (await client.get(
        "/api/v1/organizations/notif-org/members", headers=await auth_headers(owner)
    )).json()
    member_id = next(m["user_id"] for m in members if m["user"]["email"] == MEMBER)

    # assignment notification
    task = await make_task(
        client, owner, project["id"], "Assign me", assignee_id=member_id
    )
    r = await client.get("/api/v1/notifications", headers=await auth_headers(member))
    types = [n["type"] for n in r.json()["items"]]
    assert "task_assigned" in types
    assert "member_joined" in types

    # unread count + mark read
    r = await client.get("/api/v1/notifications/unread-count", headers=await auth_headers(member))
    assert r.json()["unread"] >= 2
    first = (await client.get(
        "/api/v1/notifications", headers=await auth_headers(member)
    )).json()["items"][0]
    r = await client.post(
        f"/api/v1/notifications/{first['id']}/read", headers=await auth_headers(member)
    )
    assert r.json()["read_at"] is not None
    # other user's notification -> 404 (IDOR)
    r = await client.post(
        f"/api/v1/notifications/{first['id']}/read", headers=await auth_headers(owner)
    )
    assert r.status_code == 404

    # comment notifies assignee + mention
    r = await client.post(
        f"/api/v1/tasks/{task['id']}/comments",
        json={"body": "ping member@example.com please review"},
        headers=await auth_headers(owner),
    )
    assert r.status_code == 201
    r = await client.get("/api/v1/notifications/unread-count", headers=await auth_headers(member))
    # mention notification arrived (member@example.com matches user email)
    assert r.json()["unread"] >= 1

    r = await client.post("/api/v1/notifications/read-all", headers=await auth_headers(member))
    assert r.status_code == 200
    r = await client.get("/api/v1/notifications/unread-count", headers=await auth_headers(member))
    assert r.json()["unread"] == 0


@pytest.mark.asyncio
async def test_audit_trail_records_actions(client):
    owner = await make_user(client, email=OWNER, full_name="Auditor")
    await make_org(client, owner, name="Audit Org", slug="audit-org")
    project = await make_project(client, owner, "audit-org")
    await make_task(client, owner, project["id"], "Audited task")
    H = await auth_headers(owner)

    r = await client.get("/api/v1/organizations/audit-org/audit-logs", headers=H)
    assert r.status_code == 200
    actions = [a["action"] for a in r.json()["items"]]
    assert "organization.created" in actions
    assert "project.created" in actions
    assert "task.created" in actions

    # filter by action
    r = await client.get(
        "/api/v1/organizations/audit-org/audit-logs?action=task.created", headers=H
    )
    assert all(a["action"] == "task.created" for a in r.json()["items"])

    # member cannot read audit logs
    member = await make_user(client, email="audit-member@example.com")
    await client.post(
        "/api/v1/organizations/audit-org/invitations",
        json={"email": "audit-member@example.com"},
        headers=H,
    )
    invs = (await client.get("/api/v1/invitations/me", headers=await auth_headers(member))).json()
    await client.post(
        f"/api/v1/invitations/{invs[0]['id']}/accept", headers=await auth_headers(member)
    )
    r = await client.get(
        "/api/v1/organizations/audit-org/audit-logs", headers=await auth_headers(member)
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_webhook_crud_secret_shown_once(client):
    owner = await make_user(client, email=OWNER)
    await make_org(client, owner, name="Webhook Org", slug="hook-org")
    H = await auth_headers(owner)

    r = await client.post(
        "/api/v1/organizations/hook-org/webhooks",
        json={
            "url": "https://receiver.example.com/hook",
            "events": ["task.created", "task.completed"],
        },
        headers=H,
    )
    assert r.status_code == 201, r.text
    created = r.json()
    secret = created["secret"]
    assert len(secret) >= 32

    # subsequent reads never include the secret
    hooks = (await client.get("/api/v1/organizations/hook-org/webhooks", headers=H)).json()
    assert hooks[0]["id"] == created["id"]
    assert "secret" not in hooks[0]

    r = await client.patch(
        f"/api/v1/organizations/hook-org/webhooks/{created['id']}",
        json={"events": ["comment.created"], "is_active": False},
        headers=H,
    )
    assert r.status_code == 200
    assert r.json()["is_active"] is False
    assert r.json()["events"] == ["comment.created"]

    r = await client.get(
        f"/api/v1/organizations/hook-org/webhooks/{created['id']}/deliveries", headers=H
    )
    assert r.status_code == 200
    assert r.json() == []

    r = await client.delete(
        f"/api/v1/organizations/hook-org/webhooks/{created['id']}", headers=H
    )
    assert r.status_code == 204
