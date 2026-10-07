"""Saved filter repository."""

import uuid

from sqlmodel import or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import SavedFilter


class SavedFilterRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_in_org(
        self, saved_filter_id: uuid.UUID, organization_id: uuid.UUID
    ) -> SavedFilter | None:
        statement = select(SavedFilter).where(
            SavedFilter.id == saved_filter_id,
            SavedFilter.organization_id == organization_id,
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def list_visible(
        self, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> list[SavedFilter]:
        """Shared filters plus the caller's private ones."""
        statement = (
            select(SavedFilter)
            .where(
                SavedFilter.organization_id == organization_id,
                or_(
                    SavedFilter.is_shared == True,
                    SavedFilter.owner_id == user_id,
                ),
            )
            .order_by(SavedFilter.name.asc())
        )
        return list((await self.db.execute(statement)).scalars().all())

    async def add(self, saved_filter: SavedFilter) -> SavedFilter:
        self.db.add(saved_filter)
        await self.db.flush()
        return saved_filter

    async def update(self, saved_filter: SavedFilter) -> SavedFilter:
        self.db.add(saved_filter)
        await self.db.flush()
        return saved_filter

    async def delete(self, saved_filter: SavedFilter) -> None:
        await self.db.delete(saved_filter)
        await self.db.flush()
