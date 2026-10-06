"""Integration tests for M3 ecosystem: API tokens/service accounts/OAuth apps
(#24), releases/roadmap/calendar (#16, #17), integrations (#23) and cursor
pagination (#37)."""

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import pytest

from tests.utils import auth_headers, make_org, make_project, make_task, make_user

ALICE = "m3e-alice@example.com"
BEN = "m3e-ben@example.com"
SLUG = "m3e-org"


@pytest.fixture
async def board(client):
    alice = await make_user(client, email=ALICE, full_name="Alice")
    ben = await make_user(client, email=BEN, full_name="Ben")
    await make_org(client, alice, name="M3 Ecosystem", slug=SLUG)
    project = await make_project(client, alice, SLUG, name="Ecosystem Board")
    return {"alice": alice, "ben": ben, "project": project}


async def _add_member(client, actor, email, role="member") -> str:
    r = await client.post(
        f"/api/v1/organizations/{SLUG}/members",
        json={"user_email": email, "role": role},
        headers=await auth_headers(actor),
    )
    assert r.status_code == 201, r.text
    return r.json()["user_id"]


# --- #24: API tokens -------------------------------------------------------


@pytest.mark.asyncio
async def test_api_token_lifecycle_scopes_and_usage(client, board):
    alice = board["alice"]
    HA = await auth_headers(alice)
    r = await client.post(
        f"/api/v1/organizations/{SLUG}/api-tokens",
        json={"name": "CI read token", "scopes": ["read"]},
        headers=HA,
    )
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["token"].startswith("tf_")
    assert created["token_prefix"] == created["token"][:12]
    token_headers = {"Authorization": f"Bearer {created['token']}"}

    # The token authenticates as its owner.
    r = await client.get(
        f"/api/v1/organizations/{SLUG}/projects", headers=token_headers
    )
    assert r.status_code == 200, r.text

    # ... but a read-scope token cannot write.
    r = await client.post(
        f"/api/v1/organizations/{SLUG}/projects",
        json={"name": "Nope"},
        headers=token_headers,
    )
    assert r.status_code == 403

    usage = (
        await client.get(
            f"/api/v1/organizations/{SLUG}/api-tokens/{created['id']}/usage",
            headers=HA,
        )
    ).json()
    assert usage["usage_count"] >= 1
    assert usage["requests_last_minute"] >= 1

    # Rotation invalidates the old secret, revocation stops the new one.
    rotated = (
        await client.post(
            f"/api/v1/organizations/{SLUG}/api-tokens/{created['id']}/rotate",
            headers=HA,
        )
    ).json()
    r = await client.get(
        f"/api/v1/organizations/{SLUG}/projects",
        headers={"Authorization": f"Bearer {created['token']}"},
    )
    assert r.status_code == 401
    rotated_headers = {"Authorization": f"Bearer {rotated['token']}"}
    assert (
        await client.get(
            f"/api/v1/organizations/{SLUG}/projects", headers=rotated_headers
        )
    ).status_code == 200

    r = await client.delete(
        f"/api/v1/organizations/{SLUG}/api-tokens/{created['id']}", headers=HA
    )
    assert r.status_code == 204
    assert (
        await client.get(
            f"/api/v1/organizations/{SLUG}/projects", headers=rotated_headers
        )
    ).status_code == 401


@pytest.mark.asyncio
async def test_service_accounts_are_hidden_and_scoped(client, board):
    alice, ben = board["alice"], board["ben"]
    HA, HB = await auth_headers(alice), await auth_headers(ben)
    await _add_member(client, alice, BEN)

    # Members cannot manage service accounts.
    r = await client.post(
        f"/api/v1/organizations/{SLUG}/service-accounts",
        json={"name": "Robot", "scopes": ["read"]},
        headers=HB,
    )
    assert r.status_code == 403

    r = await client.post(
        f"/api/v1/organizations/{SLUG}/service-accounts",
        json={"name": "Robot", "scopes": ["read", "write"]},
        headers=HA,
    )
    assert r.status_code == 201, r.text
    account = r.json()
    assert account["user_id"]

    # The shadow user must not appear in the member roster.
    members = (
        await client.get(f"/api/v1/organizations/{SLUG}/members", headers=HA)
    ).json()
    assert all(m["user_id"] != account["user_id"] for m in members)

    # Token scopes must be a subset of the account's scopes.
    r = await client.post(
        f"/api/v1/organizations/{SLUG}/api-tokens",
        json={
            "name": "robot token",
            "scopes": ["read"],
            "service_account_id": account["id"],
        },
        headers=HA,
    )
    assert r.status_code == 201, r.text
    robot_headers = {"Authorization": f"Bearer {r.json()['token']}"}
    assert (
        await client.get(
            f"/api/v1/organizations/{SLUG}/projects", headers=robot_headers
        )
    ).status_code == 200

    r = await client.post(
        f"/api/v1/organizations/{SLUG}/api-tokens",
        json={
            "name": "too broad",
            "scopes": ["admin"],
            "service_account_id": account["id"],
        },
        headers=HA,
    )
    assert r.status_code == 422

    # Deleting the account cascades to its tokens.
    r = await client.delete(
        f"/api/v1/organizations/{SLUG}/service-accounts/{account['id']}", headers=HA
    )
    assert r.status_code == 204
    assert (
        await client.get(
            f"/api/v1/organizations/{SLUG}/projects", headers=robot_headers
        )
    ).status_code == 401


@pytest.mark.asyncio
async def test_oauth_app_client_credentials_grant(client, board):
    alice = board["alice"]
    HA = await auth_headers(alice)
    r = await client.post(
        f"/api/v1/organizations/{SLUG}/oauth-apps",
        json={"name": "Deploy bot", "scopes": ["read", "write"]},
        headers=HA,
    )
    assert r.status_code == 201, r.text
    app = r.json()
    assert app["client_secret"].startswith("tfs_")

    r = await client.post(
        "/api/v1/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": app["client_id"],
            "client_secret": app["client_secret"],
            "scope": "read",
        },
    )
    assert r.status_code == 200, r.text
    access = r.json()
    assert access["access_token"].startswith("tfo_")
    oauth_headers = {"Authorization": f"Bearer {access['access_token']}"}
    assert (
        await client.get(
            f"/api/v1/organizations/{SLUG}/projects", headers=oauth_headers
        )
    ).status_code == 200

    # Requesting a scope outside the app registration is rejected.
    r = await client.post(
        "/api/v1/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": app["client_id"],
            "client_secret": app["client_secret"],
            "scope": "admin",
        },
    )
    assert r.status_code == 422

    r = await client.post(
        "/api/v1/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": app["client_id"],
            "client_secret": "wrong",
        },
    )
    assert r.status_code == 401


# --- #16/#17: releases, roadmap, calendar ----------------------------------


@pytest.mark.asyncio
async def test_releases_roadmap_and_calendar(client, board):
    alice, project = board["alice"], board["project"]
    HA = await auth_headers(alice)
    now = datetime.now(UTC)

    epic = await make_task(
        client,
        alice,
        project["id"],
        title="Login epic",
        type="epic",
        due_date=(now + timedelta(days=20)).isoformat(),
    )
    release = (
        await client.post(
            f"/api/v1/projects/{project['id']}/releases",
            json={
                "name": "v1.0",
                "version": "1.0.0",
                "status": "planned",
                "release_date": (now + timedelta(days=25)).isoformat(),
            },
            headers=HA,
        )
    ).json()
    await make_task(
        client,
        alice,
        project["id"],
        title="Login story",
        type="story",
        parent_id=epic["id"],
        release_id=release["id"],
        due_date=(now + timedelta(days=5)).isoformat(),
    )

    releases = (
        await client.get(
            f"/api/v1/projects/{project['id']}/releases", headers=HA
        )
    ).json()
    assert len(releases) == 1
    assert releases[0]["task_count"] == 1 and releases[0]["done_task_count"] == 0

    r = await client.patch(
        f"/api/v1/projects/{project['id']}/releases/{release['id']}",
        json={"status": "released"},
        headers=HA,
    )
    assert r.status_code == 200
    assert r.json()["released_at"] is not None

    roadmap = (
        await client.get(
            f"/api/v1/projects/{project['id']}/roadmap", headers=HA
        )
    ).json()
    assert len(roadmap["epics"]) == 1
    assert roadmap["epics"][0]["task_count"] == 1
    assert roadmap["releases"][0]["status"] == "released"

    # Calendar window includes the story, and drag-to-reschedule (a PATCH of
    # due_date) moves it to another day.
    start = (now - timedelta(days=1)).date().isoformat()
    end = (now + timedelta(days=40)).date().isoformat()
    calendar = (
        await client.get(
            f"/api/v1/organizations/{SLUG}/calendar",
            params={"start": start, "end": end, "project_id": project["id"]},
            headers=HA,
        )
    ).json()
    story = next(entry for entry in calendar["tasks"] if entry["title"] == "Login story")
    moved_day = now + timedelta(days=10)
    r = await client.patch(
        f"/api/v1/tasks/{story['id']}",
        json={"due_date": moved_day.isoformat()},
        headers=HA,
    )
    assert r.status_code == 200, r.text
    calendar = (
        await client.get(
            f"/api/v1/organizations/{SLUG}/calendar",
            params={"start": start, "end": end, "project_id": project["id"]},
            headers=HA,
        )
    ).json()
    updated = next(entry for entry in calendar["tasks"] if entry["id"] == story["id"])
    assert updated["due_date"].startswith(moved_day.date().isoformat())


# --- #23: integrations -----------------------------------------------------


@pytest.mark.asyncio
async def test_vcs_webhook_links_commits_and_auto_transitions(client, board):
    alice, project = board["alice"], board["project"]
    HA = await auth_headers(alice)
    task = await make_task(client, alice, project["id"], title="Fix login redirect")

    r = await client.post(
        f"/api/v1/organizations/{SLUG}/integrations",
        json={
            "provider": "github",
            "name": "teamflow/backend",
            "config": {"repository": "teamflow/backend", "auto_transition": {"push": "in_progress"}},
        },
        headers=HA,
    )
    assert r.status_code == 201, r.text
    integration = r.json()
    assert integration["has_secret"] and integration["secret"]
    assert integration["webhook_path"].startswith("/api/v1/integrations/github/")

    payload = json.dumps(
        {
            "commits": [
                {"message": f"{task['key']} fix login redirect", "url": "https://github.com/x/commit/abc"}
            ],
            "ref": "refs/heads/main",
        }
    ).encode()
    signature = "sha256=" + hmac.new(
        integration["secret"].encode(), payload, hashlib.sha256
    ).hexdigest()

    r = await client.post(
        integration["webhook_path"],
        content=payload,
        headers={"X-GitHub-Event": "push", "X-Hub-Signature-256": signature},
    )
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["matched"] == 1
    assert task["key"] in result["linked"]
    assert any(task["key"] in entry for entry in result["transitions"])

    comments = (
        await client.get(f"/api/v1/tasks/{task['id']}/comments", headers=HA)
    ).json()
    assert any("Linked" in entry["body"] and task["key"] in entry["body"] for entry in comments)

    refreshed = (await client.get(f"/api/v1/tasks/{task['id']}", headers=HA)).json()
    assert refreshed["status"] == "in_progress"

    # Bad signature is rejected.
    r = await client.post(
        integration["webhook_path"],
        content=payload,
        headers={"X-GitHub-Event": "push", "X-Hub-Signature-256": "sha256=deadbeef"},
    )
    assert r.status_code == 401

    events = (
        await client.get(
            f"/api/v1/organizations/{SLUG}/integrations/events", headers=HA
        )
    ).json()
    assert events and events[0]["direction"] == "inbound"


@pytest.mark.asyncio
async def test_chat_and_calendar_integrations(client, board):
    alice, project = board["alice"], board["project"]
    HA = await auth_headers(alice)

    r = await client.post(
        f"/api/v1/organizations/{SLUG}/integrations",
        json={"provider": "slack", "name": "engineering", "events": ["task.created"]},
        headers=HA,
    )
    assert r.status_code == 422  # slack needs config.webhook_url

    r = await client.post(
        f"/api/v1/organizations/{SLUG}/integrations",
        json={
            "provider": "slack",
            "name": "engineering",
            "config": {"webhook_url": "https://hooks.slack.com/services/T/B/X"},
            "events": ["task.created"],
        },
        headers=HA,
    )
    assert r.status_code == 201, r.text
    assert r.json()["secret"] is None

    # Outbound chat dispatch creates a durable event row per matching event.
    await make_task(client, alice, project["id"], title="Ping slack")
    events = (
        await client.get(
            f"/api/v1/organizations/{SLUG}/integrations/events", headers=HA
        )
    ).json()
    outbound = [entry for entry in events if entry["direction"] == "outbound"]
    assert outbound and outbound[0]["event_type"] == "task.created"

    r = await client.post(
        f"/api/v1/organizations/{SLUG}/integrations",
        json={"provider": "google_calendar", "name": "My calendar"},
        headers=HA,
    )
    assert r.status_code == 201, r.text
    gcal = r.json()
    await make_task(
        client,
        alice,
        project["id"],
        title="Calendar sync task",
        due_date=(datetime.now(UTC) + timedelta(days=3)).isoformat(),
    )
    r = await client.get(
        f"{gcal['feed_path']}", params={"token": gcal["secret"]}
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/calendar")
    assert "BEGIN:VCALENDAR" in r.text
    assert "SUMMARY" in r.text

    r = await client.get(f"{gcal['feed_path']}", params={"token": "nope"})
    assert r.status_code == 404


# --- #37: cursor pagination ------------------------------------------------


@pytest.mark.asyncio
async def test_cursor_pagination_is_stable_and_exhaustive(client, board):
    alice, project = board["alice"], board["project"]
    HA = await auth_headers(alice)
    for index in range(5):
        await make_task(client, alice, project["id"], title=f"Cursor {index}")

    collected: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        params = {"project_id": project["id"], "limit": 2}
        if cursor:
            params["cursor"] = cursor
        page = (
            await client.get(
                f"/api/v1/organizations/{SLUG}/tasks/cursor", params=params, headers=HA
            )
        ).json()
        collected.extend(entry["id"] for entry in page["items"])
        pages += 1
        cursor = page["next_cursor"]
        if cursor is None:
            break
        assert pages < 10

    assert len(collected) == 5
    assert len(set(collected)) == 5
    assert pages == 3

    r = await client.get(
        f"/api/v1/organizations/{SLUG}/tasks/cursor",
        params={"cursor": "not-a-cursor"},
        headers=HA,
    )
    assert r.status_code == 422
