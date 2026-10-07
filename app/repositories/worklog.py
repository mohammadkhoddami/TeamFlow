"""Worklog repository."""

import uuid
from datetime import datetime

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Task, Worklog


class WorklogRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, worklog_id: uuid.UUID) -> Worklog | None:
        return await self.db.get(Worklog, worklog_id)

    async def get_in_org(self, worklog_id: uuid.UUID, organization_id: uuid.UUID) -> Worklog | None:
        statement = select(Worklog).where(
            Worklog.id == worklog_id, Worklog.organization_id == organization_id
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def list_for_task(
        self, task_id: uuid.UUID, *, offset: int = 0, limit: int = 100
    ) -> list[Worklog]:
        statement = (
            select(Worklog)
            .where(Worklog.task_id == task_id)
            .order_by(Worklog.started_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list((await self.db.execute(statement)).scalars().all())

    async def total_minutes_for_tasks(
        self, task_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, int]:
        if not task_ids:
            return {}
        statement = (
            select(Worklog.task_id, func.coalesce(func.sum(Worklog.minutes), 0))
            .where(Worklog.task_id.in_(task_ids))
            .group_by(Worklog.task_id)
        )
        rows = (await self.db.execute(statement)).all()
        return {row[0]: int(row[1] or 0) for row in rows}

    async def list_for_org(
        self,
        organization_id: uuid.UUID,
        *,
        date_from: datetime,
        date_to: datetime,
        user_id: uuid.UUID | None = None,
    ) -> list[tuple[Worklog, Task]]:
        statement = (
            select(Worklog, Task)
            .join(Task, Task.id == Worklog.task_id)
            .where(
                Worklog.organization_id == organization_id,
                Worklog.started_at >= date_from,
                Worklog.started_at < date_to,
            )
            .order_by(Worklog.started_at.asc())
        )
        if user_id is not None:
            statement = statement.where(Worklog.user_id == user_id)
        return [(row[0], row[1]) for row in (await self.db.execute(statement)).all()]

    async def add(self, worklog: Worklog) -> Worklog:
        self.db.add(worklog)
        await self.db.flush()
        return worklog

    async def update(self, worklog: Worklog) -> Worklog:
        self.db.add(worklog)
        await self.db.flush()
        return worklog

    async def delete(self, worklog: Worklog) -> None:
        await self.db.delete(worklog)
        await self.db.flush()
