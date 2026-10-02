"""Integration tests: passwordless email OTP and Google OAuth sign-in."""

import pytest

from app.core.config import settings
from app.core.redis import get_redis_client
from app.services import token_store
from app.services.integrations import google_oauth

EMAIL = "otp-user@example.com"


async def _plant_code(email: str, code: str = "123456") -> None:
    """The code is hashed at rest, so tests plant a known one directly."""
    await token_store.store_otp(get_redis_client(), email, code, 600)


# ------------------------------------------------------------------ email OTP


@pytest.mark.asyncio
async def test_otp_request_never_reveals_account_existence(client):
    r1 = await client.post("/api/v1/auth/otp/request", json={"email": EMAIL})
    r2 = await client.post(
        "/api/v1/auth/otp/request", json={"email": "ghost@example.com"}
    )
    assert r1.status_code == r2.status_code == 202
    assert r1.json() == r2.json()


@pytest.mark.asyncio
async def test_otp_verify_creates_user_and_issues_tokens(client):
    await client.post("/api/v1/auth/otp/request", json={"email": EMAIL})
    await _plant_code(EMAIL)

    r = await client.post(
        "/api/v1/auth/otp/verify", json={"email": EMAIL, "code": "123456"}
    )
    assert r.status_code == 200, r.text
    pair = r.json()
    assert pair["access_token"] and pair["refresh_token"]

    r = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {pair['access_token']}"}
    )
    assert r.status_code == 200
    assert r.json()["email"] == EMAIL

    # Single-use: the same code can never sign in twice.
    r = await client.post(
        "/api/v1/auth/otp/verify", json={"email": EMAIL, "code": "123456"}
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_otp_verify_rejects_wrong_code_without_burning_valid_one(client):
    await _plant_code(EMAIL)
    r = await client.post(
        "/api/v1/auth/otp/verify", json={"email": EMAIL, "code": "000000"}
    )
    assert r.status_code == 401
    # A wrong guess does not kill the code while attempts remain.
    r = await client.post(
        "/api/v1/auth/otp/verify", json={"email": EMAIL, "code": "123456"}
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_otp_verify_burns_code_after_max_attempts(client):
    await _plant_code(EMAIL)
    for _ in range(settings.otp_max_attempts):
        r = await client.post(
            "/api/v1/auth/otp/verify", json={"email": EMAIL, "code": "000000"}
        )
        assert r.status_code == 401
    r = await client.post(
        "/api/v1/auth/otp/verify", json={"email": EMAIL, "code": "123456"}
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_otp_login_for_existing_password_account(client):
    from tests.utils import PASSWORD

    await _plant_code(EMAIL)
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": EMAIL,
            "password": PASSWORD,
            "full_name": "Otp User",
            "code": "123456",
        },
    )
    assert r.status_code == 201
    await _plant_code(EMAIL)
    r = await client.post(
        "/api/v1/auth/otp/verify", json={"email": EMAIL, "code": "123456"}
    )
    assert r.status_code == 200


# --------------------------------------------------------------- Google OAuth


def _fake_identity(
    sub: str = "google-sub-1",
    email: str = "gmail-user@example.com",
    verified: bool = True,
) -> google_oauth.GoogleIdentity:
    return google_oauth.GoogleIdentity(
        sub=sub, email=email, email_verified=verified, name="Gmail User"
    )


def _patch_google(monkeypatch, identity: google_oauth.GoogleIdentity) -> None:
    async def fake_exchange(code: str, redirect_uri: str, verifier: str) -> str:
        return "fake-id-token"

    monkeypatch.setattr(google_oauth, "exchange_code", fake_exchange)
    monkeypatch.setattr(google_oauth, "verify_id_token", lambda token: identity)
    monkeypatch.setattr(settings, "google_client_id", "test-client-id")
    monkeypatch.setattr(settings, "google_client_secret", "test-client-secret")


async def _start_google(client) -> str:
    r = await client.get("/api/v1/auth/google/start", follow_redirects=False)
    assert r.status_code == 302
    location = r.headers["location"]
    assert location.startswith(google_oauth.GOOGLE_AUTHORIZE_URL)
    assert "code_challenge_method=S256" in location
    state = location.split("state=")[1].split("&")[0]
    return state


@pytest.mark.asyncio
async def test_google_start_disabled_without_credentials(client, monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "")
    monkeypatch.setattr(settings, "google_client_secret", "")
    r = await client.get("/api/v1/auth/google/start", follow_redirects=False)
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_google_callback_rejects_replayed_or_unknown_state(client, monkeypatch):
    _patch_google(monkeypatch, _fake_identity())
    r = await client.get(
        "/api/v1/auth/google/callback?code=x&state=forged",
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert "error=" in r.headers["location"]


@pytest.mark.asyncio
async def test_google_login_creates_user_and_handoff_is_single_use(client, monkeypatch):
    identity = _fake_identity()
    _patch_google(monkeypatch, identity)
    state = await _start_google(client)

    r = await client.get(
        f"/api/v1/auth/google/callback?code=auth-code&state={state}",
        follow_redirects=False,
    )
    assert r.status_code == 302
    location = r.headers["location"]
    assert location.startswith(f"{settings.frontend_base_url}/auth/callback?code=")
    handoff = location.split("code=")[1]

    r = await client.post("/api/v1/auth/oauth/exchange", json={"code": handoff})
    assert r.status_code == 200, r.text
    pair = r.json()
    r = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {pair['access_token']}"}
    )
    assert r.status_code == 200
    assert r.json()["email"] == identity.email

    # One-time hand-off code: replaying it fails.
    r = await client.post("/api/v1/auth/oauth/exchange", json={"code": handoff})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_google_reuses_account_by_subject_across_email_change(client, monkeypatch):
    _patch_google(monkeypatch, _fake_identity(sub="stable-sub"))
    state = await _start_google(client)
    r = await client.get(
        f"/api/v1/auth/google/callback?code=c1&state={state}",
        follow_redirects=False,
    )
    first_handoff = r.headers["location"].split("code=")[1]

    # Same Google subject, new email: must not create a second account.
    _patch_google(monkeypatch, _fake_identity(sub="stable-sub", email="renamed@example.com"))
    state = await _start_google(client)
    r = await client.get(
        f"/api/v1/auth/google/callback?code=c2&state={state}",
        follow_redirects=False,
    )
    second_handoff = r.headers["location"].split("code=")[1]

    r1 = await client.post("/api/v1/auth/oauth/exchange", json={"code": first_handoff})
    r2 = await client.post("/api/v1/auth/oauth/exchange", json={"code": second_handoff})
    assert r1.status_code == r2.status_code == 200

    redis_client = get_redis_client()
    keys = [key async for key in redis_client.scan_iter(match="teamflow:rt:*")]
    # One user -> one session family; emails differ but the account is shared.
    user_ids = {key.split(":")[2] for key in keys}
    assert len(user_ids) == 1


@pytest.mark.asyncio
async def test_google_links_existing_password_account_by_email(client, monkeypatch):
    from tests.utils import PASSWORD

    await _plant_code("linked@example.com")
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "linked@example.com",
            "password": PASSWORD,
            "full_name": "Linked",
            "code": "123456",
        },
    )
    assert r.status_code == 201

    _patch_google(monkeypatch, _fake_identity(sub="link-sub", email="linked@example.com"))
    state = await _start_google(client)
    r = await client.get(
        f"/api/v1/auth/google/callback?code=c&state={state}",
        follow_redirects=False,
    )
    handoff = r.headers["location"].split("code=")[1]
    r = await client.post("/api/v1/auth/oauth/exchange", json={"code": handoff})
    assert r.status_code == 200

    # Password login still works after linking.
    r = await client.post(
        "/api/v1/auth/login",
        data={"username": "linked@example.com", "password": PASSWORD},
    )
    assert r.status_code == 200
