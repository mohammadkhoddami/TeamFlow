"""Integration tests: organizations, RBAC, invitations."""

import pytest

from tests.utils import auth_headers, make_org, make_user

OWNER = "org-owner@example.com"
ADMIN = "org-admin@example.com"
MANAGER = "org-manager@example.com"
MEMBER = "org-member@example.com"
OUTSIDER = "org-outsider@example.com"


@pytest.fixture
async def seeded_org(client):
    """owner -> admin -> manager -> member inside `rbac-org`."""
    owner = await make_user(client, email=OWNER, full_name="Owner")
    org = await make_org(client, owner, name="RBAC Org", slug="rbac-org")
    admin = await make_user(client, email=ADMIN)
    manager = await make_user(client, email=MANAGER)
    member = await make_user(client, email=MEMBER)
    outsider = await make_user(client, email=OUTSIDER)

    # direct adds bypass invitations for test setup
    for email, role in [(ADMIN, "admin"), (MANAGER, "manager"), (MEMBER, "member")]:
        r = await client.post(
            "/api/v1/organizations/rbac-org/members",
            json={"user_email": email, "role": role},
            headers=await auth_headers(owner),
        )
        assert r.status_code == 201, r.text
    return {"owner": owner, "admin": admin, "manager": manager, "member": member,
            "outsider": outsider, "org": org}


@pytest.mark.asyncio
async def test_outsider_gets_404_not_403(client, seeded_org):
    # Non-members must not learn the org exists.
    r = await client.get("/api/v1/organizations/rbac-org", headers=await auth_headers(seeded_org["outsider"]))
    assert r.status_code == 404
    r = await client.get(
        "/api/v1/organizations/rbac-org/members", headers=await auth_headers(seeded_org["outsider"])
    )
    assert r.status_code == 404
    r = await client.get("/api/v1/organizations/does-not-exist", headers=await auth_headers(seeded_org["owner"]))
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_org_update_requires_admin(client, seeded_org):
    H = auth_headers
    for user, expected in [("member", 403), ("manager", 403), ("admin", 200), ("owner", 200)]:
        r = await client.patch(
            "/api/v1/organizations/rbac-org",
            json={"name": "RBAC Org Renamed"},
            headers=await H(seeded_org[user]),
        )
        assert r.status_code == expected, (user, r.status_code)
    r = await client.get("/api/v1/organizations/rbac-org", headers=await H(seeded_org["owner"]))
    assert r.json()["name"] == "RBAC Org Renamed"


@pytest.mark.asyncio
async def test_only_owner_deletes_org(client, seeded_org):
    H = auth_headers
    r = await client.delete(
        "/api/v1/organizations/rbac-org", headers=await H(seeded_org["admin"])
    )
    assert r.status_code == 403
    r = await client.delete(
        "/api/v1/organizations/rbac-org", headers=await H(seeded_org["owner"])
    )
    assert r.status_code == 204
    r = await client.get("/api/v1/organizations/rbac-org", headers=await H(seeded_org["owner"]))
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_member_role_change_hierarchy(client, seeded_org):
    H = auth_headers
    member_id = (await client.get(
        "/api/v1/organizations/rbac-org/members", headers=await H(seeded_org["owner"])
    )).json()
    ids = {m["user"]["email"]: m["user_id"] for m in member_id}

    # manager cannot promote member to admin (manager outranks member but not admin)
    r = await client.patch(
        f"/api/v1/organizations/rbac-org/members/{ids[MEMBER]}",
        json={"role": "admin"},
        headers=await H(seeded_org["manager"]),
    )
    assert r.status_code == 403

    # admin promotes member to manager: OK
    r = await client.patch(
        f"/api/v1/organizations/rbac-org/members/{ids[MEMBER]}",
        json={"role": "manager"},
        headers=await H(seeded_org["admin"]),
    )
    assert r.status_code == 200
    assert r.json()["role"] == "manager"

    # admin cannot touch the owner
    r = await client.patch(
        f"/api/v1/organizations/rbac-org/members/{ids[OWNER]}",
        json={"role": "member"},
        headers=await H(seeded_org["admin"]),
    )
    assert r.status_code == 403

    # nobody can change their own role
    r = await client.patch(
        f"/api/v1/organizations/rbac-org/members/{ids[ADMIN]}",
        json={"role": "owner"},
        headers=await H(seeded_org["admin"]),
    )
    assert r.status_code == 403

    # manager cannot demote the admin that outranks them
    r = await client.patch(
        f"/api/v1/organizations/rbac-org/members/{ids[ADMIN]}",
        json={"role": "member"},
        headers=await H(seeded_org["manager"]),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_owner_cannot_be_removed_and_self_leave(client, seeded_org):
    H = auth_headers
    members = (await client.get(
        "/api/v1/organizations/rbac-org/members", headers=await H(seeded_org["owner"])
    )).json()
    ids = {m["user"]["email"]: m["user_id"] for m in members}

    r = await client.delete(
        f"/api/v1/organizations/rbac-org/members/{ids[OWNER]}",
        headers=await H(seeded_org["admin"]),
    )
    assert r.status_code == 403

    # member leaves the org themselves (self-removal allowed)
    r = await client.delete(
        f"/api/v1/organizations/rbac-org/members/{ids[MEMBER]}",
        headers=await H(seeded_org["member"]),
    )
    assert r.status_code == 204
    r = await client.get("/api/v1/organizations/rbac-org", headers=await H(seeded_org["member"]))
    assert r.status_code == 404

    # manager cannot remove admin
    r = await client.delete(
        f"/api/v1/organizations/rbac-org/members/{ids[ADMIN]}",
        headers=await H(seeded_org["manager"]),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_invitation_flow_accept(client, seeded_org):
    H = auth_headers
    invitee = await make_user(client, email="invitee@example.com", full_name="Invitee")

    # member cannot invite
    r = await client.post(
        "/api/v1/organizations/rbac-org/invitations",
        json={"email": "invitee@example.com", "role": "member"},
        headers=await H(seeded_org["member"]),
    )
    assert r.status_code == 403

    # manager invites as member
    r = await client.post(
        "/api/v1/organizations/rbac-org/invitations",
        json={"email": "invitee@example.com", "role": "member"},
        headers=await H(seeded_org["manager"]),
    )
    assert r.status_code == 201
    invitation_id = r.json()["id"]

    # duplicate pending invite -> conflict
    r = await client.post(
        "/api/v1/organizations/rbac-org/invitations",
        json={"email": "invitee@example.com", "role": "member"},
        headers=await H(seeded_org["manager"]),
    )
    assert r.status_code == 409

    # invitee sees and accepts it
    r = await client.get("/api/v1/invitations/me", headers=await H(invitee))
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["organization_name"] == "RBAC Org"

    # another user cannot accept someone else's invite (404, IDOR containment)
    r = await client.post(
        f"/api/v1/invitations/{invitation_id}/accept", headers=await H(seeded_org["outsider"])
    )
    assert r.status_code == 404

    r = await client.post(
        f"/api/v1/invitations/{invitation_id}/accept", headers=await H(invitee)
    )
    assert r.status_code == 200
    assert r.json()["role"] == "member"

    # double accept -> validation error
    r = await client.post(
        f"/api/v1/invitations/{invitation_id}/accept", headers=await H(invitee)
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_invitation_decline_and_revoke(client, seeded_org):
    H = auth_headers
    invitee = await make_user(client, email="decline-me@example.com")

    r = await client.post(
        "/api/v1/organizations/rbac-org/invitations",
        json={"email": "decline-me@example.com"},
        headers=await H(seeded_org["admin"]),
    )
    inv_id = r.json()["id"]
    r = await client.post(
        f"/api/v1/invitations/{inv_id}/decline", headers=await H(invitee)
    )
    assert r.status_code == 204

    # manager creates, admin revokes
    r = await client.post(
        "/api/v1/organizations/rbac-org/invitations",
        json={"email": "decline-me@example.com"},
        headers=await H(seeded_org["manager"]),
    )
    inv2 = r.json()["id"]
    r = await client.delete(
        f"/api/v1/organizations/rbac-org/invitations/{inv2}",
        headers=await H(seeded_org["admin"]),
    )
    assert r.status_code == 204
    r = await client.post(
        f"/api/v1/invitations/{inv2}/accept", headers=await H(invitee)
    )
    assert r.status_code == 422  # revoked


@pytest.mark.asyncio
async def test_my_organizations_lists_role(client, seeded_org):
    H = auth_headers
    r = await client.get("/api/v1/organizations", headers=await H(seeded_org["owner"]))
    assert r.status_code == 200
    orgs = r.json()
    assert orgs[0]["organization"]["slug"] == "rbac-org"
    assert orgs[0]["role"] == "owner"
