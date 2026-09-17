"""Idempotency key repository (used by the idempotency middleware)."""

from datetime import datetime

from sqlalchemy import delete
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import IdempotencyKey


class IdempotencyRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, key: str) -> IdempotencyKey | None:
        statement = select(IdempotencyKey).where(IdempotencyKey.key == key)
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def insert(self, record: IdempotencyKey) -> IdempotencyKey:
        self.db.add(record)
        await self.db.commit()  # committed immediately: the claim must be durable
        return record

    async def complete(
        self,
        key: str,
        response_status: int,
        content_type: str | None,
        response_body: str,
    ) -> None:
        statement = (
            select(IdempotencyKey)
            .where(IdempotencyKey.key == key)
            .with_for_update()
        )
        record = (await self.db.execute(statement)).scalar_one_or_none()
        if record is None:
            return
        record.status = "completed"
        record.response_status = response_status
        record.content_type = content_type
        record.response_body = response_body
        self.db.add(record)
        await self.db.commit()

    async def fail(self, key: str) -> None:
        record = await self.get(key)
        if record is None:
            return
        record.status = "failed"
        self.db.add(record)
        await self.db.commit()

    async def purge_older_than(self, cutoff: datetime) -> int:

        result = await self.db.execute(
            delete(IdempotencyKey).where(IdempotencyKey.created_at < cutoff)
        )
        return int(result.rowcount or 0)
