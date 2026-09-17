"""Audit log route (admin+)."""

import uuid

from fastapi import APIRouter, Query

from app.api.deps import DB, OrgMembership
from app.core.exceptions import PermissionDeniedError
from app.models import MembershipRole
from app.repositories import AuditLogRepository
from app.schemas import AuditLogRead, Page

audit_router = APIRouter(prefix="/organizations/{slug}/audit-logs", tags=["audit"])


@audit_router.get("", response_model=Page[AuditLogRead], summary="Organization audit trail")
async def list_audit_logs(
    membership: OrgMembership,
    db: DB,
    action: str | None = Query(default=None, max_length=64),
    actor_id: uuid.UUID | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> Page[AuditLogRead]:
    _org, m = membership
    if m.role not in (MembershipRole.ADMIN, MembershipRole.OWNER):
        raise PermissionDeniedError("Only admins and owners can view audit logs")
    items, total = await AuditLogRepository(db).list_for_org(
        _org.id, action=action, actor_id=actor_id, offset=offset, limit=limit
    )
    return Page[AuditLogRead](
        items=[AuditLogRead.model_validate(l) for l in items],
        total=total,
        offset=offset,
        limit=limit,
    )
