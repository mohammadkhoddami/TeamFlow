"""Checklist item + task assignee repositories."""

import uuid

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import ChecklistItem, TaskAssignee


class ChecklistRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, item_id: uuid.UUID) -> ChecklistItem | None:
        return await self.db.get(ChecklistItem, item_id)

    async def list_for_task(self, task_id: uuid.UUID) -> list[ChecklistItem]:
        statement = (
            select(ChecklistItem)
            .where(ChecklistItem.task_id == task_id)
            .order_by(ChecklistItem.position.asc(), ChecklistItem.created_at.asc())
        )
        return list((await self.db.execute(statement)).scalars().all())

    async def stats_for_tasks(
        self, task_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, tuple[int, int]]:
        if not task_ids:
            return {}
        done_count = func.count(ChecklistItem.id).filter(
            ChecklistItem.is_done == True
        )
        statement = (
            select(ChecklistItem.task_id, func.count(ChecklistItem.id), done_count)
            .where(ChecklistItem.task_id.in_(task_ids))
            .group_by(ChecklistItem.task_id)
        )
        rows = (await self.db.execute(statement)).all()
        return {row[0]: (int(row[1]), int(row[2] or 0)) for row in rows}

    async def add(self, item: ChecklistItem) -> ChecklistItem:
        self.db.add(item)
        await self.db.flush()
        return item

    async def update(self, item: ChecklistItem) -> ChecklistItem:
        self.db.add(item)
        await self.db.flush()
        return item

    async def delete(self, item: ChecklistItem) -> None:
        await self.db.delete(item)
        await self.db.flush()


class TaskAssigneeRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_for_task(self, task_id: uuid.UUID) -> list[TaskAssignee]:
        statement = select(TaskAssignee).where(TaskAssignee.task_id == task_id)
        return list((await self.db.execute(statement)).scalars().all())

    async def list_for_tasks(self, task_ids: list[uuid.UUID]) -> list[TaskAssignee]:
        if not task_ids:
            return []
        statement = select(TaskAssignee).where(TaskAssignee.task_id.in_(task_ids))
        return list((await self.db.execute(statement)).scalars().all())

    async def add(self, assignee: TaskAssignee) -> TaskAssignee:
        self.db.add(assignee)
        await self.db.flush()
        return assignee

    async def delete_for_task(self, task_id: uuid.UUID) -> None:
        for entry in await self.list_for_task(task_id):
            await self.db.delete(entry)
        await self.db.flush()
