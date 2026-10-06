"""Global full-text search route (tasks, comments, projects)."""

from fastapi import APIRouter, Query

from app.api.deps import DB, OrgMembership
from app.schemas import SearchResponse
from app.services import search as search_service

router = APIRouter(prefix="/organizations/{slug}/search", tags=["search"])


@router.get("", response_model=SearchResponse)
async def global_search(
    membership: OrgMembership,
    db: DB,
    q: str = Query(min_length=1, max_length=200, description="Search text"),
    limit: int = Query(default=10, ge=1, le=25),
) -> SearchResponse:
    org, _m = membership
    return await search_service.search(db, org.id, q, limit=limit)
