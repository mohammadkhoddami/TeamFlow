"""Audit log repository."""

import uuid
from datetime import datetime

from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import AuditLog


class AuditLogRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_for_org(
        self,
        organization_id: uuid.UUID,
        *,
        action: str | None = None,
        actor_id: uuid.UUID | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[AuditLog], int]:
        conds = [AuditLog.organization_id == organization_id]
        if action:
            conds.append(AuditLog.action == action)
        if actor_id:
            conds.append(AuditLog.actor_id == actor_id)
        statement = (
            select(AuditLog)
            .where(*conds)
            .order_by(AuditLog.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        items = list((await self.db.execute(statement)).scalars().all())
        total = (
            (await self.db.execute(select(func.count(AuditLog.id)).where(*conds)))
            .scalar_one()
        )
        return items, total

    async def add(self, log: AuditLog) -> AuditLog:
        """Added to the caller's session (same transaction); no commit here."""
        self.db.add(log)
        await self.db.flush()
        return log

    async def purge_older_than(self, cutoff: datetime) -> int:
        from sqlalchemy import delete

        result = await self.db.execute(delete(AuditLog).where(AuditLog.created_at < cutoff))
        return int(result.rowcount or 0)
