"""Label repository."""

import uuid

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Label


class LabelRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_in_org(self, label_id: uuid.UUID, organization_id: uuid.UUID) -> Label | None:
        statement = select(Label).where(
            Label.id == label_id,
            Label.organization_id == organization_id,
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def list_for_org(
        self,
        organization_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Label]:
        statement = (
            select(Label)
            .where(Label.organization_id == organization_id)
            .order_by(Label.name.asc())
            .offset(offset)
            .limit(limit)
        )
        return list((await self.db.execute(statement)).scalars().all())

    async def get_by_name(self, organization_id: uuid.UUID, name: str) -> Label | None:
        statement = select(Label).where(
            Label.organization_id == organization_id,
            Label.name == name,
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def add(self, label: Label) -> Label:
        self.db.add(label)
        await self.db.flush()
        return label

    async def update(self, label: Label) -> Label:
        self.db.add(label)
        await self.db.flush()
        return label

    async def delete(self, label: Label) -> None:
        await self.db.delete(label)
        await self.db.flush()
