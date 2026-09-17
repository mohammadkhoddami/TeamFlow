"""Notification repository."""

import uuid
from datetime import UTC, datetime

from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Notification


class NotificationRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_for_user(self, notification_id: uuid.UUID, user_id: uuid.UUID) -> Notification | None:
        statement = select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user_id,
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def list_for_user(
        self,
        user_id: uuid.UUID,
        *,
        unread_only: bool = False,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Notification], int]:
        conds = [Notification.user_id == user_id]
        if unread_only:
            conds.append(Notification.read_at.is_(None))
        statement = (
            select(Notification)
            .where(*conds)
            .order_by(Notification.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        items = list((await self.db.execute(statement)).scalars().all())
        total = (
            (await self.db.execute(select(func.count(Notification.id)).where(*conds)))
            .scalar_one()
        )
        return items, total

    async def unread_count(self, user_id: uuid.UUID) -> int:
        statement = select(func.count(Notification.id)).where(
            Notification.user_id == user_id,
            Notification.read_at.is_(None),
        )
        return (await self.db.execute(statement)).scalar_one()

    async def mark_all_read(self, user_id: uuid.UUID) -> int:
        """Bulk UPDATE (no row loading); returns affected row count."""
        from sqlalchemy import update

        statement = (
            update(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.read_at.is_(None),
            )
            .values(read_at=datetime.now(UTC))
        )
        result = await self.db.execute(statement)
        return int(result.rowcount or 0)

    async def add(self, notification: Notification) -> Notification:
        self.db.add(notification)
        await self.db.flush()
        return notification

    async def add_many(self, notifications: list[Notification]) -> None:
        self.db.add_all(notifications)
        await self.db.flush()
