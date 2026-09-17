"""Redis-backed sliding-window rate limiting for abuse-sensitive endpoints.

How it works: each (scope, identity) pair maps to a Redis sorted set whose
members are hit timestamps. `ZADD` the current hit, evict entries older than
the window, and `ZCARD` the remaining count — one atomic pipeline, no locks.
Sliding windows are preferred over fixed windows because they do not allow a
burst twice the limit around a window boundary.

Identity choice matters: auth endpoints are limited per client IP *and* per
username so one attacker cannot lock out a victim by burning their quota, and
a single IP cannot brute-force many accounts.

Redis being down fails OPEN (logged): availability beats throttling here,
because these endpoints already require valid credentials or a fresh JWT.
"""

import secrets
import time
from typing import Annotated

import redis.asyncio as redis
from fastapi import Depends, Request
from redis.asyncio import Redis

from app.core.config import settings
from app.core.exceptions import RateLimitError
from app.core.redis import get_redis_client

RedisDep = Annotated[Redis, Depends(get_redis_client)]


def _key(scope: str, identity: str) -> str:
    return f"teamflow:rl:{scope}:{identity}"


async def hit_rate_limit(
    redis_client: Redis,
    scope: str,
    identity: str,
    max_hits: int,
    window_seconds: int,
) -> None:
    """Records a hit and raises RateLimitError when the window is exceeded."""
    now = time.time()
    key = _key(scope, identity)
    member = f"{now:.6f}:{secrets.token_hex(4)}"
    window_start = now - window_seconds
    try:
        pipe = redis_client.pipeline()
        pipe.zadd(key, {member: now})
        pipe.zremrangebyscore(key, "-inf", window_start)
        pipe.zcard(key)
        pipe.expire(key, window_seconds + 1)
        _, _, count, _ = await pipe.execute()
    except redis.RedisError:
        return  # fail open; Redis outage must not brick auth

    if int(count) > max_hits:
        oldest = await redis_client.zrange(key, 0, 0, withscores=True)
        retry_after = max(1, int(window_seconds - (now - oldest[0][1]))) if oldest else window_seconds
        raise RateLimitError(
            detail="Too many requests; slow down",
            retry_after=retry_after,
        )


def client_ip(request: Request) -> str:
    """Best-effort client identity. Only the immediate socket IP is trusted;
    honoring X-Forwarded-For blindly would let callers spoof others' limits
    (set `PROXY_TRUSTED` deployment-level instead if behind a trusted proxy)."""
    return request.client.host if request.client else "unknown"

def ip_rate_limiter(
    scope: str, max_hits: int | None = None, window: int | None = None
) -> None:
    """Builds a reusable dependency (wrap in Depends at the route) limiting
    by client IP. Configure defaults via settings; pass explicit values for
    endpoints with distinct budgets."""
    if max_hits is None:
        max_hits = settings.auth_rate_limit_max
    if window is None:
        window = settings.auth_rate_limit_window

    async def _limit(request: Request, redis_client: RedisDep) -> None:
        if not settings.rate_limit_enabled:
            return
        await hit_rate_limit(redis_client, scope, client_ip(request), max_hits, window)

    return _limit
