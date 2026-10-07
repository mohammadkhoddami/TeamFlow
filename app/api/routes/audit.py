"""Audit log routes (admin+): paginated listing and hash-chained export."""

import csv
import hashlib
import io
import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Query, Response
from fastapi.responses import JSONResponse
from sqlmodel import select

from app.api.deps import DB, OrgMembership
from app.core.exceptions import PermissionDeniedError
from app.models import AuditLog, MembershipRole
from app.repositories import AuditLogRepository
from app.schemas import AuditLogRead, Page
from app.services.audit import now_iso

audit_router = APIRouter(prefix="/organizations/{slug}/audit-logs", tags=["audit"])

EXPORT_LIMIT = 5000


def _require_admin(membership) -> None:
    if membership.role not in (MembershipRole.ADMIN, MembershipRole.OWNER):
        raise PermissionDeniedError("Only admins and owners can view audit logs")


def _canonical(record: AuditLog) -> str:
    return json.dumps(
        {
            "id": str(record.id),
            "action": record.action,
            "target_type": record.target_type,
            "target_id": record.target_id,
            "actor_id": str(record.actor_id) if record.actor_id else None,
            "created_at": record.created_at.isoformat(),
            "meta": record.meta,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _export_rows(records: list[AuditLog]) -> list[dict]:
    """Adds a per-org hash chain: each row commits to the previous one, so a
    deleted/edited row breaks verification from that point onward."""
    exported: list[dict] = []
    prev_hash = ""
    for record in records:
        digest = hashlib.sha256(
            (prev_hash + _canonical(record)).encode()
        ).hexdigest()
        meta = (
            json.loads(json.dumps(record.meta, default=str)) if record.meta else None
        )
        exported.append(
            {
                "id": str(record.id),
                "action": record.action,
                "target_type": record.target_type,
                "target_id": record.target_id,
                "actor_id": str(record.actor_id) if record.actor_id else None,
                "created_at": record.created_at.isoformat(),
                "meta": meta,
                "prev_hash": prev_hash,
                "hash": digest,
            }
        )
        prev_hash = digest
    return exported


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
    _require_admin(m)
    items, total = await AuditLogRepository(db).list_for_org(
        _org.id, action=action, actor_id=actor_id, offset=offset, limit=limit
    )
    return Page[AuditLogRead](
        items=[AuditLogRead.model_validate(l) for l in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@audit_router.get("/export", summary="Export the audit trail (hash-chained)")
async def export_audit_logs(
    membership: OrgMembership,
    db: DB,
    export_format: str = Query(default="csv", alias="format", pattern="^(csv|json)$"),
    action: str | None = Query(default=None, max_length=64),
    actor_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> Response:
    org, m = membership
    _require_admin(m)

    if date_from is not None and date_from.tzinfo is None:
        date_from = date_from.replace(tzinfo=UTC)
    if date_to is not None and date_to.tzinfo is None:
        date_to = date_to.replace(tzinfo=UTC)

    conditions = [AuditLog.organization_id == org.id]
    if action:
        conditions.append(AuditLog.action == action)
    if actor_id:
        conditions.append(AuditLog.actor_id == actor_id)
    if date_from is not None:
        conditions.append(AuditLog.created_at >= date_from)
    if date_to is not None:
        conditions.append(AuditLog.created_at <= date_to)

    statement = (
        select(AuditLog)
        .where(*conditions)
        .order_by(AuditLog.created_at.asc())
        .limit(EXPORT_LIMIT)
    )
    records = list((await db.execute(statement)).scalars().all())
    rows = _export_rows(records)

    if export_format == "json":
        return JSONResponse(content={"exported_at": now_iso(), "rows": rows})

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    columns = [
        "id", "action", "target_type", "target_id", "actor_id",
        "created_at", "meta", "prev_hash", "hash",
    ]
    writer.writerow(columns)
    for row in rows:
        writer.writerow(
            [
                row["id"],
                row["action"],
                row["target_type"] or "",
                row["target_id"] or "",
                row["actor_id"] or "",
                row["created_at"],
                json.dumps(row["meta"], sort_keys=True, default=str) if row["meta"] else "",
                row["prev_hash"],
                row["hash"],
            ]
        )
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="audit-logs.csv"'},
    )
