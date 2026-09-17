"""Dashboard route: org-level statistics with cache."""

from fastapi import APIRouter, Query

from app.api.deps import DB, OrgMembership, RedisDep
from app.schemas import DashboardStats
from app.services import dashboard as dashboard_service

dashboard_router = APIRouter(prefix="/organizations/{slug}/dashboard", tags=["dashboard"])


@dashboard_router.get("", response_model=DashboardStats, summary="Organization statistics")
async def dashboard(
    membership: OrgMembership,
    db: DB,
    redis_client: RedisDep,
    use_cache: bool = Query(default=True),
) -> DashboardStats:
    """SQL-aggregated stats (no row loading); short-TTL Redis cache absorbs
    repeated polling. `?use_cache=false` forces recomputation."""
    org, _m = membership
    stats = await dashboard_service.get_dashboard(
        db, redis_client, org.id, use_cache=use_cache
    )
    return DashboardStats.model_validate(stats)
