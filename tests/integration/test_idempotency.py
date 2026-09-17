"""Integration tests: idempotency middleware behavior."""


import pytest

from tests.utils import auth_headers, make_org, make_user

EMAIL = "idempotent@example.com"
KEY = "create-project-key-1"


@pytest.mark.asyncio
async def test_same_key_same_body_replays_identical_response(client):
    user = await make_user(client, email=EMAIL)
    await make_org(client, user, name="Idem Org", slug="idem-org")
    H = await auth_headers(user)
    body = {"name": "Same Project"}

    r1 = await client.post(
        "/api/v1/organizations/idem-org/projects", json=body, headers={**H, "Idempotency-Key": KEY}
    )
    assert r1.status_code == 201
    r2 = await client.post(
        "/api/v1/organizations/idem-org/projects", json=body, headers={**H, "Idempotency-Key": KEY}
    )
    assert r2.status_code == 201
    assert r2.headers.get("idempotency-replayed") == "true"
    assert r1.json()["id"] == r2.json()["id"]

    # Only one project was created.
    r = await client.get("/api/v1/organizations/idem-org/projects", headers=H)
    assert len(r.json()) == 1


@pytest.mark.asyncio
async def test_same_key_different_body_is_422(client):
    user = await make_user(client, email=EMAIL)
    await make_org(client, user, name="Idem Org 2", slug="idem-org-2")
    H = await auth_headers(user)
    r1 = await client.post(
        "/api/v1/organizations/idem-org-2/projects",
        json={"name": "One"},
        headers={**H, "Idempotency-Key": "key-same-body-test"},
    )
    assert r1.status_code == 201
    r2 = await client.post(
        "/api/v1/organizations/idem-org-2/projects",
        json={"name": "Different"},
        headers={**H, "Idempotency-Key": "key-same-body-test"},
    )
    assert r2.status_code == 422
    assert "different request body" in r2.json()["detail"]


@pytest.mark.asyncio
async def test_keys_are_scoped_per_user(client):
    u1 = await make_user(client, email="idem-u1@example.com")
    u2 = await make_user(client, email="idem-u2@example.com")
    await make_org(client, u1, name="U1 Org", slug="u1-org")
    await make_org(client, u2, name="U2 Org", slug="u2-org")
    shared_key = "shared-key-scoping"

    r1 = await client.post(
        "/api/v1/organizations/u1-org/projects",
        json={"name": "A"},
        headers={**await auth_headers(u1), "Idempotency-Key": shared_key},
    )
    r2 = await client.post(
        "/api/v1/organizations/u2-org/projects",
        json={"name": "B"},
        headers={**await auth_headers(u2), "Idempotency-Key": shared_key},
    )
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["id"] != r2.json()["id"]


@pytest.mark.asyncio
async def test_malformed_key_rejected(client):
    user = await make_user(client, email=EMAIL)
    await make_org(client, user, name="Idem Org 3", slug="idem-org-3")
    H = await auth_headers(user)
    r = await client.post(
        "/api/v1/organizations/idem-org-3/projects",
        json={"name": "x"},
        headers={**H, "Idempotency-Key": "short"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_requests_without_key_are_untouched(client):
    user = await make_user(client, email=EMAIL)
    await make_org(client, user, name="Idem Org 4", slug="idem-org-4")
    H = await auth_headers(user)
    r1 = await client.post("/api/v1/organizations/idem-org-4/projects", json={"name": "A"}, headers=H)
    r2 = await client.post("/api/v1/organizations/idem-org-4/projects", json={"name": "A"}, headers=H)
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["id"] != r2.json()["id"]
