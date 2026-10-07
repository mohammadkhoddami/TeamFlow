"""Integration tests for M4 governance/extensibility:

- granular permissions: custom roles + member delete gating
- project visibility (private projects + project members)
- audit export (CSV/JSON, hash-chained)
- plugin directory / install / uninstall
- heuristic AI breakdown + apply
- web-push subscription plumbing
"""

import csv
import io

import pytest

from tests.utils import auth_headers, make_org, make_project, make_task, make_user

ALICE = "m4-alice@example.com"
BOB = "m4-bob@example.com"
CAROL = "m4-carol@example.com"
SLUG = "m4-governance"


@pytest.fixture
async def org_bundle(client):
    alice = await make_user(client, email=ALICE, full_name="Alice")
    bob = await make_user(client, email=BOB, full_name="Bob")
    carol = await make_user(client, email=CAROL, full_name="Carol")
    await make_org(client, alice, name="M4 Governance", slug=SLUG)
    for email in (BOB, CAROL):
        r = await client.post(
            f"/api/v1/organizations/{SLUG}/members",
            json={"user_email": email, "role": "member"},
            headers=await auth_headers(alice),
        )
        assert r.status_code == 201, r.text
    project = await make_project(client, alice, SLUG, name="M4 Board")
    return {"alice": alice, "bob": bob, "carol": carol, "project": project}


async def _members_by_email(client, actor) -> dict:
    r = await client.get(
        f"/api/v1/organizations/{SLUG}/members", headers=await auth_headers(actor)
    )
    assert r.status_code == 200, r.text
    return {entry["user"]["email"]: entry for entry in r.json()}


# --- custom roles + granular delete -----------------------------------------


@pytest.mark.asyncio
async def test_custom_roles_and_task_delete_permission(client, org_bundle):
    alice, bob, carol = org_bundle["alice"], org_bundle["bob"], org_bundle["carol"]
    project = org_bundle["project"]
    HA, HB, HC = (
        await auth_headers(alice),
        await auth_headers(bob),
        await auth_headers(carol),
    )

    # Members cannot manage custom roles.
    r = await client.post(
        f"/api/v1/organizations/{SLUG}/roles",
        json={"name": "Auditors", "permissions": ["audit.view"]},
        headers=HB,
    )
    assert r.status_code == 403

    r = await client.post(
        f"/api/v1/organizations/{SLUG}/roles",
        json={"name": "Auditors", "permissions": ["audit.view"]},
        headers=HA,
    )
    assert r.status_code == 201, r.text
    role = r.json()
    assert role["permissions"] == ["audit.view"]

    # Unique name + closed permission vocabulary.
    r = await client.post(
        f"/api/v1/organizations/{SLUG}/roles",
        json={"name": "Auditors", "permissions": []},
        headers=HA,
    )
    assert r.status_code == 409
    r = await client.post(
        f"/api/v1/organizations/{SLUG}/roles",
        json={"name": "Root", "permissions": ["root.everything"]},
        headers=HA,
    )
    assert r.status_code == 422

    # Assign the role (without tasks.delete) to Bob.
    bob_id = (await _members_by_email(client, alice))[BOB]["user_id"]
    r = await client.patch(
        f"/api/v1/organizations/{SLUG}/members/{bob_id}",
        json={"role": "member", "custom_role_id": role["id"]},
        headers=HA,
    )
    assert r.status_code == 200, r.text
    assert r.json()["custom_role_id"] == role["id"]
    assert r.json()["custom_role_name"] == "Auditors"
    members = await _members_by_email(client, alice)
    assert members[BOB]["custom_role_name"] == "Auditors"

    # Bob still cannot delete Alice's task: no tasks.delete yet.
    task = await make_task(client, alice, project["id"], title="Delete me")
    r = await client.delete(f"/api/v1/tasks/{task['id']}", headers=HB)
    assert r.status_code == 403

    # Grant tasks.delete through the custom role -> deletion works.
    r = await client.patch(
        f"/api/v1/organizations/{SLUG}/roles/{role['id']}",
        json={"permissions": ["audit.view", "tasks.delete"]},
        headers=HA,
    )
    assert r.status_code == 200, r.text
    r = await client.delete(f"/api/v1/tasks/{task['id']}", headers=HB)
    assert r.status_code == 204, r.text

    # A plain member without the custom role still cannot delete someone else's.
    task2 = await make_task(client, alice, project["id"], title="Keep me")
    r = await client.delete(f"/api/v1/tasks/{task2['id']}", headers=HC)
    assert r.status_code == 403

    # ... but the owner can.
    r = await client.delete(f"/api/v1/tasks/{task2['id']}", headers=HA)
    assert r.status_code == 204

    # Role deletion succeeds and detaches from the membership.
    r = await client.delete(
        f"/api/v1/organizations/{SLUG}/roles/{role['id']}", headers=HA
    )
    assert r.status_code == 204
    members = await _members_by_email(client, alice)
    assert members[BOB]["custom_role_id"] is None


# --- private project visibility ---------------------------------------------


@pytest.mark.asyncio
async def test_private_project_visibility_and_project_members(client, org_bundle):
    alice, bob, carol = org_bundle["alice"], org_bundle["bob"], org_bundle["carol"]
    project = org_bundle["project"]
    HA, HB, HC = (
        await auth_headers(alice),
        await auth_headers(bob),
        await auth_headers(carol),
    )

    r = await client.patch(
        f"/api/v1/projects/{project['id']}",
        json={"visibility": "private"},
        headers=HA,
    )
    assert r.status_code == 200, r.text
    assert r.json()["visibility"] == "private"

    # Non-members get 404 and cannot see it in listings.
    assert (
        await client.get(f"/api/v1/projects/{project['id']}", headers=HB)
    ).status_code == 404
    listed = (
        await client.get(f"/api/v1/organizations/{SLUG}/projects", headers=HB)
    ).json()
    assert all(entry["id"] != project["id"] for entry in listed)
    # Owner still sees it.
    assert (
        await client.get(f"/api/v1/projects/{project['id']}", headers=HA)
    ).status_code == 200

    # Add Bob as an explicit project member (admin-only operation).
    r = await client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"user_email": BOB, "role": "viewer"},
        headers=HA,
    )
    assert r.status_code == 201, r.text
    member = r.json()
    assert member["user"]["email"] == BOB
    assert member["role"] == "viewer"

    # Bob can now read the project (and its tasks); Carol cannot.
    assert (
        await client.get(f"/api/v1/projects/{project['id']}", headers=HB)
    ).status_code == 200
    task = await make_task(client, alice, project["id"], title="Private task")
    assert (
        await client.get(f"/api/v1/tasks/{task['id']}", headers=HB)
    ).status_code == 200
    assert (
        await client.get(f"/api/v1/tasks/{task['id']}", headers=HC)
    ).status_code == 404

    # Project roster requires projects.manage; Bob (viewer) is refused.
    r = await client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"user_email": CAROL, "role": "viewer"},
        headers=HB,
    )
    assert r.status_code == 403

    # The owner can update and remove project members.
    r = await client.patch(
        f"/api/v1/projects/{project['id']}/members/{member['user_id']}",
        json={"role": "member"},
        headers=HA,
    )
    assert r.status_code == 200 and r.json()["role"] == "member"
    r = await client.delete(
        f"/api/v1/projects/{project['id']}/members/{member['user_id']}", headers=HA
    )
    assert r.status_code == 204
    assert (
        await client.get(f"/api/v1/projects/{project['id']}", headers=HB)
    ).status_code == 404


# --- audit export ------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_export_csv_and_json_hash_chain(client, org_bundle):
    alice, bob = org_bundle["alice"], org_bundle["bob"]
    HA, HB = await auth_headers(alice), await auth_headers(bob)
    await make_project(client, alice, SLUG, name="Audited Project")

    r = await client.get(
        f"/api/v1/organizations/{SLUG}/audit-logs/export", headers=HA
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert rows, "export should contain audit rows"
    header = r.text.splitlines()[0]
    for column in ("action", "prev_hash", "hash"):
        assert column in header
    assert any(row["action"] == "project.created" for row in rows)
    assert rows[0]["prev_hash"] == ""
    for previous, current in zip(rows, rows[1:]):
        assert current["prev_hash"] == previous["hash"]

    # Action filter narrows the export.
    r = await client.get(
        f"/api/v1/organizations/{SLUG}/audit-logs/export",
        params={"format": "json", "action": "project.created"},
        headers=HA,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["exported_at"]
    assert body["rows"] and all(
        row["action"] == "project.created" for row in body["rows"]
    )
    assert all(row["hash"] for row in body["rows"])

    # Non-admins cannot export.
    assert (
        await client.get(
            f"/api/v1/organizations/{SLUG}/audit-logs/export", headers=HB
        )
    ).status_code == 403


# --- plugins -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_plugin_directory_install_and_uninstall(client, org_bundle):
    alice, bob = org_bundle["alice"], org_bundle["bob"]
    HA, HB = await auth_headers(alice), await auth_headers(bob)

    directory = (
        await client.get(
            f"/api/v1/organizations/{SLUG}/plugins/directory", headers=HB
        )
    ).json()
    assert len(directory) >= 5
    assert all(entry["installed"] is False for entry in directory)
    assert any(entry["id"] == "github-issues" for entry in directory)

    # Members cannot install; admins/owners can.
    r = await client.post(
        f"/api/v1/organizations/{SLUG}/plugins",
        json={"catalog_id": "github-issues", "webhook_url": "https://example.com/hook"},
        headers=HB,
    )
    assert r.status_code == 403
    r = await client.post(
        f"/api/v1/organizations/{SLUG}/plugins",
        json={"catalog_id": "github-issues", "webhook_url": "https://example.com/hook"},
        headers=HA,
    )
    assert r.status_code == 201, r.text
    plugin = r.json()
    assert plugin["secret"]
    assert plugin["manifest"]["catalog_id"] == "github-issues"
    assert "task.created" in plugin["events"]

    # Same name -> conflict.
    r = await client.post(
        f"/api/v1/organizations/{SLUG}/plugins",
        json={"catalog_id": "github-issues", "webhook_url": "https://example.com/hook2"},
        headers=HA,
    )
    assert r.status_code == 409

    directory = (
        await client.get(
            f"/api/v1/organizations/{SLUG}/plugins/directory", headers=HA
        )
    ).json()
    entry = next(e for e in directory if e["id"] == "github-issues")
    assert entry["installed"] is True

    plugins = (
        await client.get(f"/api/v1/organizations/{SLUG}/plugins", headers=HA)
    ).json()
    assert len(plugins) == 1

    r = await client.patch(
        f"/api/v1/organizations/{SLUG}/plugins/{plugin['id']}",
        json={"events": ["task.created", "comment.created"]},
        headers=HA,
    )
    assert r.status_code == 200, r.text
    assert len(r.json()["events"]) == 2

    r = await client.delete(
        f"/api/v1/organizations/{SLUG}/plugins/{plugin['id']}", headers=HA
    )
    assert r.status_code == 204
    directory = (
        await client.get(
            f"/api/v1/organizations/{SLUG}/plugins/directory", headers=HA
        )
    ).json()
    entry = next(e for e in directory if e["id"] == "github-issues")
    assert entry["installed"] is False


# --- AI breakdown ------------------------------------------------------------


@pytest.mark.asyncio
async def test_ai_breakdown_parse_and_apply(client, org_bundle):
    alice = org_bundle["alice"]
    project = org_bundle["project"]
    HA = await auth_headers(alice)

    markdown = (
        "# Release 1\n\n"
        "## Dashboard\n"
        "- Build charts\n"
        "- Fix filters\n\n"
        "## Notifications\n"
        "- Add digest\n"
    )
    r = await client.post(
        f"/api/v1/organizations/{SLUG}/ai/breakdown",
        json={"description": markdown},
        headers=HA,
    )
    assert r.status_code == 200, r.text
    proposal = r.json()
    assert proposal["provided"] is True
    epic = proposal["items"][0]
    assert epic["type"] == "epic" and epic["title"] == "Release 1"
    stories = epic["children"]
    assert [story["title"] for story in stories] == ["Dashboard", "Notifications"]
    assert [task["title"] for task in stories[0]["children"]] == [
        "Build charts",
        "Fix filters",
    ]
    assert stories[0]["children"][0]["type"] == "task"

    # Bullets only -> top-level tasks; empty -> not provided.
    r = await client.post(
        f"/api/v1/organizations/{SLUG}/ai/breakdown",
        json={"description": "- One\n- Two"},
        headers=HA,
    )
    assert [item["type"] for item in r.json()["items"]] == ["task", "task"]
    r = await client.post(
        f"/api/v1/organizations/{SLUG}/ai/breakdown",
        json={"description": "   "},
        headers=HA,
    )
    assert r.json()["provided"] is False and r.json()["items"] == []

    # Priority heuristic fills proposals.
    r = await client.post(
        f"/api/v1/organizations/{SLUG}/ai/breakdown",
        json={"description": "- Fix production outage ASAP"},
        headers=HA,
    )
    assert r.json()["items"][0]["priority"] == "urgent"

    # Apply materializes the hierarchy through the task service.
    r = await client.post(
        f"/api/v1/organizations/{SLUG}/ai/breakdown/apply",
        json={"project_id": project["id"], "items": proposal["items"]},
        headers=HA,
    )
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["created"] == 6  # 1 epic + 2 stories + 3 tasks
    assert result["failures"] == []

    tree = (
        await client.get(
            f"/api/v1/projects/{project['id']}/tasks/tree", headers=HA
        )
    ).json()
    assert len(tree) == 1
    root = tree[0]
    assert root["title"] == "Release 1" and root["type"] == "epic"
    dashboard = next(c for c in root["children"] if c["title"] == "Dashboard")
    assert {t["title"] for t in dashboard["children"]} == {
        "Build charts",
        "Fix filters",
    }


# --- web push subscriptions --------------------------------------------------


@pytest.mark.asyncio
async def test_push_subscription_lifecycle(client, org_bundle):
    alice, bob = org_bundle["alice"], org_bundle["bob"]
    HA, HB = await auth_headers(alice), await auth_headers(bob)
    payload = {
        "endpoint": "https://push.example.com/endpoint-1",
        "keys": {"p256dh": "key-1", "auth": "auth-1"},
        "user_agent": "pytest",
    }

    r = await client.post(
        "/api/v1/notifications/push/subscribe", json=payload, headers=HA
    )
    assert r.status_code == 200, r.text
    subscription = r.json()
    assert subscription["endpoint"] == payload["endpoint"]

    # Upsert by endpoint: same row, new keys.
    r = await client.post(
        "/api/v1/notifications/push/subscribe",
        json={**payload, "keys": {"p256dh": "key-2", "auth": "auth-2"}},
        headers=HA,
    )
    assert r.status_code == 200
    assert r.json()["id"] == subscription["id"]
    assert r.json()["keys"]["p256dh"] == "key-2"

    subscriptions = (
        await client.get(
            "/api/v1/notifications/push/subscriptions", headers=HA
        )
    ).json()
    assert len(subscriptions) == 1
    assert (
        await client.get(
            "/api/v1/notifications/push/subscriptions", headers=HB
        )
    ).json() == []

    # Owner-only delete.
    assert (
        await client.delete(
            f"/api/v1/notifications/push/subscriptions/{subscription['id']}",
            headers=HB,
        )
    ).status_code == 404
    assert (
        await client.delete(
            f"/api/v1/notifications/push/subscriptions/{subscription['id']}",
            headers=HA,
        )
    ).status_code == 204
    assert (
        await client.get(
            "/api/v1/notifications/push/subscriptions", headers=HA
        )
    ).json() == []
