"""Dashboard cache.

Stats are aggregated in SQL (no row loading) but are hit often; a short-TTL
Redis cache smooths bursts. Every mutation that moves the numbers invalidates
the key explicitly — the TTL is only a safety net, not the mechanism.
"""

import json
import logging
import uuid

import redis.asyncio as redis
from redis.asyncio import Redis

from app.core.redis import get_redis_client

logger = logging.getLogger(__name__)

DASHBOARD_TTL_SECONDS = 60


def dashboard_key(organization_id: uuid.UUID) -> str:
    return f"teamflow:cache:dashboard:{organization_id}"


async def get_dashboard_cache(redis_client: Redis, organization_id: uuid.UUID) -> dict | None:
    try:
        raw = await redis_client.get(dashboard_key(organization_id))
        return json.loads(raw) if raw else None
    except (redis.RedisError, ValueError):
        return None


async def set_dashboard_cache(
    redis_client: Redis, organization_id: uuid.UUID, stats: dict
) -> None:
    try:
        await redis_client.set(
            dashboard_key(organization_id),
            json.dumps(stats, default=str),
            ex=DASHBOARD_TTL_SECONDS,
        )
    except redis.RedisError:
        logger.warning("Dashboard cache write failed (Redis down?); serving uncached")


async def invalidate_dashboard(organization_id: uuid.UUID) -> None:
    try:
        await get_redis_client().delete(dashboard_key(organization_id))
    except redis.RedisError:
        logger.warning("Dashboard cache invalidation failed (Redis down?)")
