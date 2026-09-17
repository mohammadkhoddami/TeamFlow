"""Integration tests: dashboard aggregation + cache invalidation."""

import pytest

from tests.utils import auth_headers, make_org, make_project, make_task, make_user

EMAIL = "dash-user@example.com"


@pytest.mark.asyncio
async def test_dashboard_aggregates_and_cache(client):
    user = await make_user(client, email=EMAIL, full_name="Dash")
    await make_org(client, user, name="Dash Org", slug="dash-org")
    project = await make_project(client, user, "dash-org")
    H = await auth_headers(user)
    me = (await client.get("/api/v1/auth/me", headers=H)).json()

    t1 = await make_task(
        client, user, project["id"], "One", priority="high", assignee_id=me["id"]
    )
    await make_task(
        client, user, project["id"], "Two", priority="low", assignee_id=me["id"]
    )
    await make_task(client, user, project["id"], "Three", priority="low")

    r = await client.get("/api/v1/organizations/dash-org/dashboard", headers=H)
    assert r.status_code == 200
    stats = r.json()
    assert stats["total_tasks"] == 3
    assert stats["tasks_by_status"]["todo"] == 3
    assert stats["projects"] == 1
    assert stats["active_members"] == 1

    # complete one task
    r = await client.post(f"/api/v1/tasks/{t1['id']}/move", json={"status": "in_progress"}, headers=H)
    assert r.status_code == 200
    r = await client.post(f"/api/v1/tasks/{t1['id']}/move", json={"status": "in_review"}, headers=H)
    r = await client.post(f"/api/v1/tasks/{t1['id']}/move", json={"status": "done"}, headers=H)
    assert r.status_code == 200

    # cache was invalidated by mutations: numbers must be fresh
    r = await client.get("/api/v1/organizations/dash-org/dashboard", headers=H)
    stats = r.json()
    assert stats["completed_tasks"] == 1
    assert stats["tasks_by_status"]["done"] == 1
    assert stats["tasks_per_member"][0]["full_name"] == "Dash"
    assert stats["tasks_per_member"][0]["open_tasks"] == 1  # Two is open, One done


@pytest.mark.asyncio
async def test_dashboard_cache_is_populated(client):
    user = await make_user(client, email=EMAIL)
    org = await make_org(client, user, name="Cache Org 2", slug="cache-org-2")
    await make_project(client, user, "cache-org-2")
    H = await auth_headers(user)

    await client.get("/api/v1/organizations/cache-org-2/dashboard", headers=H)

    import uuid

    from app.core.redis import get_redis_client
    from app.services.cache import dashboard_key

    cached = await get_redis_client().get(dashboard_key(uuid.UUID(org["id"])))
    assert cached is not None
    assert "total_tasks" in cached
