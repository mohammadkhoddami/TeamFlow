"""Notification preference repository."""

import uuid

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import NotificationPreference


class PreferenceRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_for_user(self, user_id: uuid.UUID) -> NotificationPreference | None:
        statement = select(NotificationPreference).where(
            NotificationPreference.user_id == user_id
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def get_by_unsubscribe_token(self, token: str) -> NotificationPreference | None:
        statement = select(NotificationPreference).where(
            NotificationPreference.unsubscribe_token == token
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def list_digest_subscribers(self, cadences: list[str]) -> list[NotificationPreference]:
        statement = select(NotificationPreference).where(
            NotificationPreference.email_enabled == True,
            NotificationPreference.digest.in_(cadences),
        )
        return list((await self.db.execute(statement)).scalars().all())

    async def add(self, preference: NotificationPreference) -> NotificationPreference:
        self.db.add(preference)
        await self.db.flush()
        return preference

    async def update(self, preference: NotificationPreference) -> NotificationPreference:
        self.db.add(preference)
        await self.db.flush()
        return preference
