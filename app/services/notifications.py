"""Notification service: user inbox queries (creation lives in events.notify)."""

import uuid
from datetime import UTC, datetime

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import NotFoundError
from app.models import Notification, User
from app.repositories import NotificationRepository


async def list_notifications(
    db: AsyncSession,
    user: User,
    *,
    unread_only: bool = False,
    offset: int = 0,
    limit: int = 20,
) -> tuple[list[Notification], int]:
    return await NotificationRepository(db).list_for_user(
        user.id, unread_only=unread_only, offset=offset, limit=limit
    )


async def unread_count(db: AsyncSession, user: User) -> int:
    return await NotificationRepository(db).unread_count(user.id)


async def mark_read(db: AsyncSession, user: User, notification_id: uuid.UUID) -> Notification:
    notification = await NotificationRepository(db).get_for_user(notification_id, user.id)
    if not notification:
        # 404 hides other users' notification IDs (IDOR containment).
        raise NotFoundError("Notification not found")
    if notification.read_at is None:
        notification.read_at = datetime.now(UTC)
        db.add(notification)
        await db.commit()
    return notification


async def mark_all_read(db: AsyncSession, user: User) -> int:
    count = await NotificationRepository(db).mark_all_read(user.id)
    await db.commit()
    return count
