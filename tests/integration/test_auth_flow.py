"""Integration tests: authentication flows (register/login/refresh/logout)."""

import jwt as pyjwt
import pytest

from tests.utils import OTP_CODE, PASSWORD, auth_headers, make_user, plant_otp

EMAIL = "auth-user@example.com"


@pytest.mark.asyncio
async def test_register_login_me_roundtrip(client):
    await plant_otp(EMAIL)
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": EMAIL,
            "password": PASSWORD,
            "full_name": "Auth User",
            "code": OTP_CODE,
        },
    )
    assert r.status_code == 201
    user = r.json()
    assert user["email"] == EMAIL
    assert "hashed_password" not in user and "password" not in user

    r = await client.post(
        "/api/v1/auth/login", data={"username": EMAIL, "password": PASSWORD}
    )
    assert r.status_code == 200
    tokens = r.json()
    assert tokens["token_type"] == "bearer"
    assert tokens["access_token"] and tokens["refresh_token"]

    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    r = await client.get("/api/v1/auth/me", headers=headers)
    assert r.status_code == 200
    assert r.json()["email"] == EMAIL


@pytest.mark.asyncio
async def test_login_rejects_wrong_password_and_unknown_email(client):
    await make_user(client, email=EMAIL)
    r = await client.post(
        "/api/v1/auth/login", data={"username": EMAIL, "password": "wrong-password-1"}
    )
    assert r.status_code == 401
    assert "Incorrect email or password" in r.json()["detail"]
    # Unknown email: identical error (no user enumeration).
    r = await client.post(
        "/api/v1/auth/login", data={"username": "ghost@example.com", "password": "whatever"}
    )
    assert r.status_code == 401
    assert "Incorrect email or password" in r.json()["detail"]


@pytest.mark.asyncio
async def test_register_requires_valid_otp(client):
    """Regression: registration without a redeemed email code must not create
    an account (the OTP gate used to be bypassable)."""
    payload = {
        "email": "otp-gated@example.com",
        "password": PASSWORD,
        "full_name": "Gated",
    }
    # No code at all: rejected by schema before the service runs.
    r = await client.post("/api/v1/auth/register", json=payload)
    assert r.status_code == 422

    # Unknown/wrong code: rejected and the account stays absent.
    r = await client.post(
        "/api/v1/auth/register", json={**payload, "code": "000000"}
    )
    assert r.status_code == 401
    r = await client.post(
        "/api/v1/auth/login",
        data={"username": payload["email"], "password": PASSWORD},
    )
    assert r.status_code == 401

    # The emailed code unlocks registration exactly once.
    await plant_otp(payload["email"])
    r = await client.post(
        "/api/v1/auth/register", json={**payload, "code": OTP_CODE}
    )
    assert r.status_code == 201
    r = await client.post(
        "/api/v1/auth/register", json={**payload, "code": OTP_CODE}
    )
    assert r.status_code == 409  # code consumed, then duplicate email


@pytest.mark.asyncio
async def test_register_rejects_duplicate_email_and_weak_password(client):
    await make_user(client, email=EMAIL)
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": EMAIL, "password": PASSWORD, "code": OTP_CODE},
    )
    assert r.status_code == 409
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": "short@example.com", "password": "short", "code": OTP_CODE},
    )
    assert r.status_code == 422
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": "not-an-email", "password": PASSWORD, "code": OTP_CODE},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_access_token_required(client):
    r = await client.get("/api/v1/auth/me")
    assert r.status_code == 401
    r = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_refresh_rotates_and_old_token_dies(client):
    user = await make_user(client, email=EMAIL)
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": user["refresh"]})
    assert r.status_code == 200
    new = r.json()
    assert new["refresh_token"] != user["refresh"]

    # Reusing the rotated-out token is treated as theft: whole family revoked.
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": user["refresh"]})
    assert r.status_code == 401

    # ...and the new token is dead too (family burned).
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": new["refresh_token"]})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_access_token_cannot_refresh(client):
    user = await make_user(client, email=EMAIL)
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": user["token"]})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_logout_revokes_refresh_token(client):
    user = await make_user(client, email=EMAIL)
    r = await client.post("/api/v1/auth/logout", json={"refresh_token": user["refresh"]})
    assert r.status_code == 204
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": user["refresh"]})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_logout_all_kills_every_session(client):
    u1 = await make_user(client, email=EMAIL)
    u2 = await make_user(client, email="second-session@example.com")
    r = await client.post(
        "/api/v1/auth/logout-all", headers=await auth_headers(u1)
    )
    assert r.status_code == 204
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": u1["refresh"]})
    assert r.status_code == 401
    # other users unaffected
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": u2["refresh"]})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_password_reset_flow_revokes_sessions(client):
    user = await make_user(client, email=EMAIL)
    r = await client.post("/api/v1/auth/forgot-password", json={"email": EMAIL})
    assert r.status_code == 202

    # Fetch the reset token from the Redis store (frontend would get it via email).
    import secrets

    from app.core.redis import get_redis_client
    from app.services import token_store

    # scan for the stored token hash -> we cheat by minting our own request path:
    # instead of reading the raw token (hashed at rest), verify via unknown token + known token.
    client_redis = get_redis_client()
    keys = []
    async for key in client_redis.scan_iter(match="teamflow:prt:*"):
        keys.append(key)
    assert len(keys) == 1
    user_id = await client_redis.get(keys[0])
    assert user_id

    # Wrong token -> 401
    r = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": "bogus-token", "new_password": "newsupersecret9"},
    )
    assert r.status_code == 401

    # Valid reset: craft token the same way the service does (we cannot invert
    # the hash), so mint one directly to prove the redemption path.
    raw = secrets.token_urlsafe(32)
    await token_store.store_password_reset_token(client_redis, raw, user_id, 600)
    r = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw, "new_password": "newsupersecret9"},
    )
    assert r.status_code == 204

    # Old password no longer works.
    r = await client.post(
        "/api/v1/auth/login", data={"username": EMAIL, "password": PASSWORD}
    )
    assert r.status_code == 401
    r = await client.post(
        "/api/v1/auth/login", data={"username": EMAIL, "password": "newsupersecret9"}
    )
    assert r.status_code == 200

    # All sessions were revoked by the reset.
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": user["refresh"]})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_forgot_password_never_reveals_account_existence(client):
    r1 = await client.post("/api/v1/auth/forgot-password", json={"email": EMAIL})
    r2 = await client.post(
        "/api/v1/auth/forgot-password", json={"email": "nobody@example.com"}
    )
    assert r1.status_code == r2.status_code == 202
    assert r1.json() == r2.json()


@pytest.mark.asyncio
async def test_jwt_claims_shape(client):
    user = await make_user(client, email=EMAIL)
    payload = pyjwt.decode(user["token"], options={"verify_signature": False})
    assert payload["type"] == "access"
    assert "exp" in payload and "iat" in payload
    refresh_payload = pyjwt.decode(user["refresh"], options={"verify_signature": False})
    assert refresh_payload["type"] == "refresh"
    assert "jti" in refresh_payload
