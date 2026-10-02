"""API-driven factories: build state through the public interface so tests
exercise the real authorization stack, not backdoors."""

from typing import Any

from httpx import AsyncClient

from app.core.config import settings
from app.services import token_store

PASSWORD = "supersecret123"
OTP_CODE = "123456"


async def plant_otp(email: str, code: str = OTP_CODE) -> None:
    """Plants a known email code directly in Redis (codes are hashed at rest).

    Registration requires a redeemed OTP, so factories plant one first. A
    fresh client is used because sync tests (WebSocket TestClient) call this
    from a different event loop than the app's shared async client.
    """
    from redis.asyncio import Redis

    client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await token_store.store_otp(client, email, code, settings.otp_ttl_seconds)
    finally:
        await client.aclose()


async def make_user(
    client: AsyncClient,
    email: str = "user1@example.com",
    password: str = PASSWORD,
    full_name: str = "Test User",
) -> dict:
    await plant_otp(email)
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": full_name,
            "code": OTP_CODE,
        },
    )
    assert r.status_code in (201, 409), r.text
    r = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": password}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    return {"token": body["access_token"], "refresh": body["refresh_token"], "email": email}


async def auth_headers(user: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {user['token']}"}


async def make_org(
    client: AsyncClient,
    user: dict,
    name: str = "Acme Inc",
    slug: str | None = None,
) -> dict:
    slug = slug or name.lower().replace(" ", "-").replace(".", "")[:60]
    r = await client.post(
        "/api/v1/organizations",
        json={"name": name, "slug": slug},
        headers=await auth_headers(user),
    )
    assert r.status_code == 201, r.text
    return r.json()


async def make_project(
    client: AsyncClient,
    user: dict,
    org_slug: str,
    name: str = "Default Project",
) -> dict:
    r = await client.post(
        f"/api/v1/organizations/{org_slug}/projects",
        json={"name": name},
        headers=await auth_headers(user),
    )
    assert r.status_code == 201, r.text
    return r.json()


async def make_task(
    client: AsyncClient,
    user: dict,
    project_id: str,
    title: str = "Task",
    **extra: Any,
) -> dict:
    r = await client.post(
        f"/api/v1/projects/{project_id}/tasks",
        json={"title": title, **extra},
        headers=await auth_headers(user),
    )
    assert r.status_code == 201, r.text
    return r.json()
