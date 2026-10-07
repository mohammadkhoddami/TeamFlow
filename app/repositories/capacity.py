"""Sprint capacity repository."""

import uuid

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import SprintCapacity


class CapacityRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_for_sprint(self, sprint_id: uuid.UUID) -> list[SprintCapacity]:
        statement = select(SprintCapacity).where(SprintCapacity.sprint_id == sprint_id)
        return list((await self.db.execute(statement)).scalars().all())

    async def get(self, sprint_id: uuid.UUID, user_id: uuid.UUID) -> SprintCapacity | None:
        statement = select(SprintCapacity).where(
            SprintCapacity.sprint_id == sprint_id,
            SprintCapacity.user_id == user_id,
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def add(self, entry: SprintCapacity) -> SprintCapacity:
        self.db.add(entry)
        await self.db.flush()
        return entry

    async def delete(self, entry: SprintCapacity) -> None:
        await self.db.delete(entry)
        await self.db.flush()
