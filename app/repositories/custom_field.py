"""Custom field repositories."""

import uuid

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import CustomField, CustomFieldValue


class CustomFieldRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_in_project(
        self, field_id: uuid.UUID, project_id: uuid.UUID
    ) -> CustomField | None:
        statement = select(CustomField).where(
            CustomField.id == field_id, CustomField.project_id == project_id
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def get_by_key(self, project_id: uuid.UUID, key: str) -> CustomField | None:
        statement = select(CustomField).where(
            CustomField.project_id == project_id, CustomField.key == key
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def list_for_project(self, project_id: uuid.UUID) -> list[CustomField]:
        statement = (
            select(CustomField)
            .where(CustomField.project_id == project_id)
            .order_by(CustomField.position.asc(), CustomField.created_at.asc())
        )
        return list((await self.db.execute(statement)).scalars().all())

    async def add(self, field: CustomField) -> CustomField:
        self.db.add(field)
        await self.db.flush()
        return field

    async def update(self, field: CustomField) -> CustomField:
        self.db.add(field)
        await self.db.flush()
        return field

    async def delete(self, field: CustomField) -> None:
        await self.db.delete(field)
        await self.db.flush()


class CustomFieldValueRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, task_id: uuid.UUID, field_id: uuid.UUID) -> CustomFieldValue | None:
        statement = select(CustomFieldValue).where(
            CustomFieldValue.task_id == task_id,
            CustomFieldValue.field_id == field_id,
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def list_for_tasks(
        self, task_ids: list[uuid.UUID]
    ) -> list[CustomFieldValue]:
        if not task_ids:
            return []
        statement = select(CustomFieldValue).where(
            CustomFieldValue.task_id.in_(task_ids)
        )
        return list((await self.db.execute(statement)).scalars().all())

    async def add(self, value: CustomFieldValue) -> CustomFieldValue:
        self.db.add(value)
        await self.db.flush()
        return value

    async def update(self, value: CustomFieldValue) -> CustomFieldValue:
        self.db.add(value)
        await self.db.flush()
        return value

    async def delete(self, value: CustomFieldValue) -> None:
        await self.db.delete(value)
        await self.db.flush()
