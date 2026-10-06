"""Task link + status history repositories."""

import uuid

from sqlalchemy import or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import TaskLink, TaskStatusHistory


class TaskLinkRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, link_id: uuid.UUID) -> TaskLink | None:
        return await self.db.get(TaskLink, link_id)

    async def list_for_task(self, task_id: uuid.UUID) -> list[TaskLink]:
        statement = select(TaskLink).where(
            or_(TaskLink.from_task_id == task_id, TaskLink.to_task_id == task_id)
        )
        return list((await self.db.execute(statement)).scalars().all())

    async def list_for_tasks(self, task_ids: list[uuid.UUID]) -> list[TaskLink]:
        if not task_ids:
            return []
        statement = select(TaskLink).where(
            or_(
                TaskLink.from_task_id.in_(task_ids),
                TaskLink.to_task_id.in_(task_ids),
            )
        )
        return list((await self.db.execute(statement)).scalars().all())

    async def find(
        self, from_task_id: uuid.UUID, to_task_id: uuid.UUID, link_type: str
    ) -> TaskLink | None:
        statement = select(TaskLink).where(
            TaskLink.from_task_id == from_task_id,
            TaskLink.to_task_id == to_task_id,
            TaskLink.link_type == link_type,
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def add(self, link: TaskLink) -> TaskLink:
        self.db.add(link)
        await self.db.flush()
        return link

    async def delete(self, link: TaskLink) -> None:
        await self.db.delete(link)
        await self.db.flush()


class TaskStatusHistoryRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def add(self, entry: TaskStatusHistory) -> TaskStatusHistory:
        self.db.add(entry)
        await self.db.flush()
        return entry

    async def list_for_task(self, task_id: uuid.UUID) -> list[TaskStatusHistory]:
        statement = (
            select(TaskStatusHistory)
            .where(TaskStatusHistory.task_id == task_id)
            .order_by(TaskStatusHistory.changed_at.asc())
        )
        return list((await self.db.execute(statement)).scalars().all())

    async def list_for_tasks(
        self, task_ids: list[uuid.UUID]
    ) -> list[TaskStatusHistory]:
        if not task_ids:
            return []
        statement = (
            select(TaskStatusHistory)
            .where(TaskStatusHistory.task_id.in_(task_ids))
            .order_by(TaskStatusHistory.changed_at.asc())
        )
        return list((await self.db.execute(statement)).scalars().all())
