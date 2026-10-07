"""Activity repository."""

import uuid

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Activity


class ActivityRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def add(self, activity: Activity) -> Activity:
        self.db.add(activity)
        await self.db.flush()
        return activity

    async def add_many(self, activities: list[Activity]) -> None:
        self.db.add_all(activities)
        await self.db.flush()

    async def list_for_task(
        self, task_id: uuid.UUID, *, offset: int = 0, limit: int = 50
    ) -> tuple[list[Activity], int]:
        conds = [Activity.task_id == task_id]
        return await self._list(conds, offset=offset, limit=limit)

    async def list_for_project(
        self, project_id: uuid.UUID, *, offset: int = 0, limit: int = 50
    ) -> tuple[list[Activity], int]:
        conds = [Activity.project_id == project_id]
        return await self._list(conds, offset=offset, limit=limit)

    async def list_for_org(
        self, organization_id: uuid.UUID, *, offset: int = 0, limit: int = 50
    ) -> tuple[list[Activity], int]:
        conds = [Activity.organization_id == organization_id]
        return await self._list(conds, offset=offset, limit=limit)

    async def _list(
        self, conds: list, *, offset: int, limit: int
    ) -> tuple[list[Activity], int]:
        from sqlmodel import func

        statement = (
            select(Activity)
            .where(*conds)
            .order_by(Activity.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        items = list((await self.db.execute(statement)).scalars().all())
        total = (
            await self.db.execute(select(func.count(Activity.id)).where(*conds))
        ).scalar_one()
        return items, int(total)
