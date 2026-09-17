"""Redis connection management.

One async Redis client per process, created lazily and shared. Every Redis use
has a specific purpose:
  - refresh-token store (logout / rotation)      `auth`
  - sliding-window rate limiting                 `ratelimit`
  - WebSocket fan-out via Redis pub/sub          `realtime`
  - dashboard stats cache with TTL+invalidation  `cache`

Key naming: `teamflow:{purpose}:{entity}:{id}` — greppable and collision-free.
Redis being down must not take the API down: callers degrade gracefully
(rate limiting fails open, cache misses fall back to the DB) and log loudly.
"""

from collections.abc import AsyncIterator

from redis.asyncio import Redis

from app.core.config import settings

_client: Redis | None = None


def get_redis_client() -> Redis:
    global _client
    if _client is None:
        _client = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            health_check_interval=30,
        )
    return _client


async def close_redis_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def get_redis() -> AsyncIterator[Redis]:
    """FastAPI dependency: yields the shared client, closed at shutdown only."""
    yield get_redis_client()


async def ping_redis() -> bool:
    try:
        await get_redis_client().ping()
        return True
    except Exception:
        return False
