"""Health/live + readiness probes.

Liveness: process is up (cheap, no I/O). Readiness: Postgres and Redis are
reachable — expensive enough that orchestrators should call it, not LBs
every second, but no queries beyond one SELECT and one PING.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from redis.asyncio import Redis
from sqlalchemy import text

from app.core.db import engine
from app.core.redis import get_redis_client

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", summary="Liveness probe")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def readiness(redis_client: Annotated[Redis, Depends(get_redis_client)]) -> dict[str, str]:
    checks: dict[str, str] = {}
    healthy = True

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "error"
        healthy = False

    try:
        await redis_client.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "error"
        healthy = False

    if not healthy:
        return Response(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content='{"status": "unavailable"}',
            media_type="application/json",
        )

    return {"status": "ready", **checks}
