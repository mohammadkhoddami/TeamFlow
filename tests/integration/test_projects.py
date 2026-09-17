"""Integration tests: projects + tenant isolation (IDOR)."""

import pytest

from tests.utils import auth_headers, make_org, make_project, make_task, make_user

ALICE = "alice-proj@example.com"
BOB = "bob-proj@example.com"


@pytest.mark.asyncio
async def test_project_crud_and_membership_scoping(client):
    alice = await make_user(client, email=ALICE)
    bob = await make_user(client, email=BOB)
    org = await make_org(client, alice, name="Proj Org", slug="proj-org")
    assert org["my_role"] == "owner"

    project = await make_project(client, alice, "proj-org", name="Website")
    assert project["name"] == "Website"
    assert project["status"] == "active"

    # bob cannot see alice's project (404, not 403)
    r = await client.get(f"/api/v1/projects/{project['id']}", headers=await auth_headers(bob))
    assert r.status_code == 404

    # alice sees it
    r = await client.get(f"/api/v1/projects/{project['id']}", headers=await auth_headers(alice))
    assert r.status_code == 200

    # bob cannot create projects in alice's org (404 because he is not a member)
    r = await client.post(
        "/api/v1/organizations/proj-org/projects",
        json={"name": "Infiltration"},
        headers=await auth_headers(bob),
    )
    assert r.status_code == 404

    # member role cannot create projects in their own org
    charlie = await make_user(client, email="charlie-proj@example.com")
    await make_org(client, charlie, name="Charlies", slug="charlies")
    dana = await make_user(client, email="dana-proj@example.com")
    await client.post(
        "/api/v1/organizations/charlies/invitations",
        json={"email": "dana-proj@example.com", "role": "member"},
        headers=await auth_headers(charlie),
    )
    invs = (await client.get("/api/v1/invitations/me", headers=await auth_headers(dana))).json()
    await client.post(
        f"/api/v1/invitations/{invs[0]['id']}/accept", headers=await auth_headers(dana)
    )
    r = await client.post(
        "/api/v1/organizations/charlies/projects",
        json={"name": "Dana Project"},
        headers=await auth_headers(dana),
    )
    assert r.status_code == 403

    # manager can create
    members = (await client.get("/api/v1/organizations/charlies/members", headers=await auth_headers(charlie))).json()
    dana_id = next(m["user_id"] for m in members if m["user"]["email"] == "dana-proj@example.com")
    r = await client.patch(
        f"/api/v1/organizations/charlies/members/{dana_id}",
        json={"role": "manager"},
        headers=await auth_headers(charlie),
    )
    assert r.status_code == 200
    r = await client.post(
        "/api/v1/organizations/charlies/projects",
        json={"name": "Dana Project"},
        headers=await auth_headers(dana),
    )
    assert r.status_code == 201


@pytest.mark.asyncio
async def test_project_update_archive_delete(client):
    alice = await make_user(client, email=ALICE)
    await make_org(client, alice, name="Archive Org", slug="archive-org")
    project = await make_project(client, alice, "archive-org")

    r = await client.patch(
        f"/api/v1/projects/{project['id']}",
        json={"status": "archived", "description": "done for now"},
        headers=await auth_headers(alice),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "archived"

    # deleting cascades tasks
    task = await make_task(client, alice, project["id"])
    r = await client.delete(f"/api/v1/projects/{project['id']}", headers=await auth_headers(alice))
    assert r.status_code == 204
    r = await client.get(f"/api/v1/tasks/{task['id']}", headers=await auth_headers(alice))
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_slug_uniqueness(client):
    alice = await make_user(client, email=ALICE)
    await make_org(client, alice, name="Dupe Org", slug="dupe-org")
    r = await client.post(
        "/api/v1/organizations",
        json={"name": "Dupe Org 2", "slug": "dupe-org"},
        headers=await auth_headers(alice),
    )
    assert r.status_code == 409
    r = await client.post(
        "/api/v1/organizations",
        json={"name": "Bad Slug", "slug": "Invalid_Slug!"},
        headers=await auth_headers(alice),
    )
    assert r.status_code == 422
