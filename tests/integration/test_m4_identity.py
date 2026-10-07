"""Integration tests: M4 identity — MFA (TOTP + recovery), OIDC SSO config, SCIM.

MFA codes are computed locally (RFC 6238) from the secret returned by
`/auth/mfa/setup`, so tests exercise the real verification path end to end.
"""

import base64
import hashlib
import hmac
import struct
import time

import pytest

from app.core.config import settings
from tests.utils import PASSWORD, auth_headers, make_org, make_user

API = settings.api_v1_prefix


def _totp(secret: str, at_time: float | None = None) -> str:
    """Minimal RFC 6238 TOTP generator (HMAC-SHA1, 30s step, 6 digits)."""
    normalized = secret.strip().upper()
    padding = "=" * ((8 - len(normalized) % 8) % 8)
    key = base64.b32decode(normalized + padding)
    counter = int(time.time() if at_time is None else at_time) // 30
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


async def _login(client, email: str) -> dict:
    r = await client.post(
        f"{API}/auth/login", data={"username": email, "password": PASSWORD}
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
async def test_mfa_full_flow_with_totp_and_recovery_codes(client):
    user = await make_user(client, email="mfa-user@example.com")
    headers = await auth_headers(user)
    mfa_url = f"{API}/auth/mfa"

    r = await client.get(mfa_url, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is False

    r = await client.post(f"{mfa_url}/setup", headers=headers)
    assert r.status_code == 200, r.text
    setup = r.json()
    secret, uri, codes = setup["secret"], setup["otpauth_uri"], setup["recovery_codes"]
    assert uri.startswith("otpauth://totp/")
    assert "secret=" in uri and "issuer=TeamFlow" in uri
    assert len(codes) == 10
    assert len(set(codes)) == 10

    r = await client.post(
        f"{mfa_url}/enable", json={"code": _totp(secret)}, headers=headers
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"enabled": True}
    r = await client.get(mfa_url, headers=headers)
    assert r.json()["enabled"] is True

    # Password login now stops at the MFA challenge: no tokens yet.
    challenge = await _login(client, user["email"])
    assert challenge["mfa_required"] is True
    assert challenge["mfa_token"]
    assert "access_token" not in challenge

    r = await client.post(
        f"{mfa_url}/verify",
        json={"mfa_token": challenge["mfa_token"], "code": _totp(secret)},
    )
    assert r.status_code == 200, r.text
    tokens = r.json()
    assert tokens["access_token"] and tokens["refresh_token"]
    r = await client.get(
        f"{API}/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert r.status_code == 200
    assert r.json()["email"] == user["email"]

    # Recovery codes sign in once and are burned on use.
    recovery = codes[0]
    challenge = await _login(client, user["email"])
    r = await client.post(
        f"{mfa_url}/verify",
        json={"mfa_token": challenge["mfa_token"], "code": recovery},
    )
    assert r.status_code == 200, r.text
    assert r.json()["access_token"]

    challenge = await _login(client, user["email"])
    r = await client.post(
        f"{mfa_url}/verify",
        json={"mfa_token": challenge["mfa_token"], "code": recovery},
    )
    assert r.status_code == 401

    # TOTP or recovery disables MFA; afterwards login issues tokens directly.
    r = await client.post(
        f"{mfa_url}/disable", json={"code": _totp(secret)}, headers=headers
    )
    assert r.status_code == 204, r.text

    body = await _login(client, user["email"])
    assert body["access_token"] and "mfa_required" not in body


@pytest.mark.asyncio
async def test_sso_config_crud_and_admin_permissions(client):
    owner = await make_user(client, email="sso-owner@example.com")
    await make_org(client, owner, name="Sso Org", slug="sso-org")
    owner_headers = await auth_headers(owner)

    payload = {
        "issuer": "https://idp.example.com",
        "client_id": "cid-123",
        "client_secret": "top-secret",
        "scopes": ["openid", "email"],
        "is_enabled": True,
        "auto_provision": True,
        "default_role": "member",
    }
    r = await client.put(
        f"{API}/organizations/sso-org/sso", json=payload, headers=owner_headers
    )
    assert r.status_code == 200, r.text
    config = r.json()
    assert config["has_secret"] is True
    assert "client_secret" not in config
    assert config["issuer"] == payload["issuer"]
    assert config["client_id"] == payload["client_id"]
    assert config["default_role"] == "member"

    r = await client.get(
        f"{API}/organizations/sso-org/sso", headers=owner_headers
    )
    assert r.status_code == 200
    assert r.json()["has_secret"] is True

    r = await client.get(f"{API}/auth/sso/sso-org/config")
    assert r.status_code == 200, r.text
    public = r.json()
    assert public["enabled"] is True
    assert public["provider"] == "oidc"
    assert public["login_url"].endswith("/auth/sso/sso-org/start")

    member = await make_user(client, email="sso-member@example.com")
    r = await client.post(
        f"{API}/organizations/sso-org/members",
        json={"user_email": member["email"], "role": "member"},
        headers=owner_headers,
    )
    assert r.status_code == 201, r.text

    r = await client.get(
        f"{API}/organizations/sso-org/sso", headers=await auth_headers(member)
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_scim_user_provisioning_flow(client):
    owner = await make_user(client, email="scim-owner@example.com")
    await make_org(client, owner, name="Scim Org", slug="scim-org")
    headers = await auth_headers(owner)

    r = await client.post(
        f"{API}/organizations/scim-org/scim-tokens",
        json={"name": "Okta"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    token_body = r.json()
    assert token_body["token"].startswith("scim_")
    bearer = {"Authorization": f"Bearer {token_body['token']}"}

    r = await client.get(f"{API}/scim/v2/ServiceProviderConfig", headers=bearer)
    assert r.status_code == 200, r.text
    assert r.json()["schemas"] == [
        "urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"
    ]

    payload = {
        "userName": "scim-user@example.com",
        "name": {"formatted": "Scim User"},
        "active": True,
    }
    r = await client.post(f"{API}/scim/v2/Users", json=payload, headers=bearer)
    assert r.status_code == 201, r.text
    resource = r.json()
    user_id = resource["id"]
    assert resource["schemas"] == [
        "urn:ietf:params:scim:schemas:core:2.0:User"
    ]
    assert resource["userName"] == "scim-user@example.com"
    assert resource["name"]["formatted"] == "Scim User"
    assert resource["active"] is True
    assert resource["emails"] == [
        {"value": "scim-user@example.com", "primary": True}
    ]

    # Duplicate userName is an RFC 7644 error.
    r = await client.post(f"{API}/scim/v2/Users", json=payload, headers=bearer)
    assert r.status_code == 409
    conflict = r.json()
    assert conflict["status"] == "409"
    assert conflict["schemas"] == [
        "urn:ietf:params:scim:api:messages:2.0:Error"
    ]

    r = await client.get(
        f"{API}/scim/v2/Users",
        params={"filter": 'userName eq "scim-user@example.com"'},
        headers=bearer,
    )
    assert r.status_code == 200, r.text
    listing = r.json()
    assert listing["totalResults"] == 1
    assert listing["startIndex"] == 1
    assert listing["Resources"][0]["id"] == user_id

    r = await client.patch(
        f"{API}/scim/v2/Users/{user_id}",
        json={
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {"op": "replace", "path": "active", "value": False},
                {"op": "replace", "path": "name.formatted", "value": "Renamed"},
            ],
        },
        headers=bearer,
    )
    assert r.status_code == 200, r.text
    patched = r.json()
    assert patched["active"] is False
    assert patched["name"]["formatted"] == "Renamed"

    r = await client.get(f"{API}/scim/v2/Users/{user_id}", headers=bearer)
    assert r.status_code == 200
    assert r.json()["active"] is False

    r = await client.delete(f"{API}/scim/v2/Users/{user_id}", headers=bearer)
    assert r.status_code == 204
    r = await client.get(f"{API}/scim/v2/Users/{user_id}", headers=bearer)
    assert r.status_code == 200
    assert r.json()["active"] is False

    r = await client.get(
        f"{API}/scim/v2/Users",
        headers={"Authorization": "Bearer scim_not-a-real-token"},
    )
    assert r.status_code == 401
