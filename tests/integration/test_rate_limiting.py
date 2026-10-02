"""Integration tests: Redis-backed rate limiting on sensitive endpoints."""

import pytest

from app.core.config import settings
from tests.utils import OTP_CODE, PASSWORD, make_user, plant_otp

EMAIL = "ratelimited@example.com"


@pytest.mark.asyncio
async def test_login_rate_limit_per_email(client):
    settings.rate_limit_enabled = True
    try:
        await make_user(client, email=EMAIL)  # spends one auth_email hit
        statuses = []
        for _ in range(8):
            r = await client.post(
                "/api/v1/auth/login", data={"username": EMAIL, "password": PASSWORD}
            )
            statuses.append(r.status_code)
        first_ok = settings.auth_rate_limit_max - 1  # one hit spent by make_user
        assert all(s == 200 for s in statuses[:first_ok])
        limited = statuses[first_ok:]
        assert limited and all(s == 429 for s in limited)
        assert "Retry-After" in r.headers
    finally:
        settings.rate_limit_enabled = False


@pytest.mark.asyncio
async def test_login_rate_limit_counts_failed_attempts_too(client):
    settings.rate_limit_enabled = True
    try:
        await make_user(client, email=EMAIL)
        # Burn the remaining quota with failures, then a valid login is blocked.
        for _ in range(settings.auth_rate_limit_max - 1):
            await client.post(
                "/api/v1/auth/login", data={"username": EMAIL, "password": "nope-nope-nope"}
            )
        r = await client.post(
            "/api/v1/auth/login", data={"username": EMAIL, "password": PASSWORD}
        )
        assert r.status_code == 429
    finally:
        settings.rate_limit_enabled = False


@pytest.mark.asyncio
async def test_register_rate_limit_per_ip(client):
    settings.rate_limit_enabled = True
    settings.register_rate_limit_max = 3
    settings.register_rate_limit_window = 3600
    try:
        statuses = []
        for i in range(5):
            email = f"r{i}@example.com"
            await plant_otp(email)
            r = await client.post(
                "/api/v1/auth/register",
                json={"email": email, "password": PASSWORD, "code": OTP_CODE},
            )
            statuses.append(r.status_code)
        assert statuses[:3] == [201, 201, 201]
        assert statuses[3:] == [429, 429]
    finally:
        settings.rate_limit_enabled = False
        settings.register_rate_limit_max = 3
        settings.register_rate_limit_window = 3600


@pytest.mark.asyncio
async def test_rate_limit_fails_open_when_redis_down(client):
    settings.rate_limit_enabled = True
    try:
        await make_user(client, email=EMAIL)
        from unittest.mock import AsyncMock, patch


        broken = AsyncMock(side_effect=ConnectionError("redis down"))
        with patch("app.core.redis.get_redis_client", return_value=broken):
            r = await client.post(
                "/api/v1/auth/login", data={"username": EMAIL, "password": PASSWORD}
            )
        # fail-open: request processed despite Redis being unavailable
        assert r.status_code == 200
    finally:
        settings.rate_limit_enabled = False
