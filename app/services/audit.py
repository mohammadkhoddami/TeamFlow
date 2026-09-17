"""Audit service: one helper, one schema, no secrets.

Audit rows are written in the caller's transaction (same session, flush only),
so an action and its audit record commit atomically. `meta` carries small,
sanitized context — callers must never put passwords, tokens, or secrets here.
"""

import uuid
from datetime import UTC, datetime

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import AuditLog
from app.repositories import AuditLogRepository


async def log(
    db: AsyncSession,
    action: str,
    *,
    actor_id: uuid.UUID | None = None,
    organization_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: uuid.UUID | str | None = None,
    ip: str | None = None,
    meta: dict | None = None,
) -> AuditLog:
    record = AuditLog(
        actor_id=actor_id,
        organization_id=organization_id,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        ip=ip,
        meta=meta,
    )
    return await AuditLogRepository(db).add(record)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()
