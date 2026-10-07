"""Comment reaction + notification mute repositories."""

import uuid

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import CommentReaction, NotificationMute


class ReactionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(
        self, comment_id: uuid.UUID, user_id: uuid.UUID, emoji: str
    ) -> CommentReaction | None:
        statement = select(CommentReaction).where(
            CommentReaction.comment_id == comment_id,
            CommentReaction.user_id == user_id,
            CommentReaction.emoji == emoji,
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def list_for_comments(
        self, comment_ids: list[uuid.UUID]
    ) -> list[CommentReaction]:
        if not comment_ids:
            return []
        statement = (
            select(CommentReaction)
            .where(CommentReaction.comment_id.in_(comment_ids))
            .order_by(CommentReaction.created_at.asc())
        )
        return list((await self.db.execute(statement)).scalars().all())

    async def add(self, reaction: CommentReaction) -> CommentReaction:
        self.db.add(reaction)
        await self.db.flush()
        return reaction

    async def delete(self, reaction: CommentReaction) -> None:
        await self.db.delete(reaction)
        await self.db.flush()


class MuteRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_for_user(self, user_id: uuid.UUID) -> list[NotificationMute]:
        statement = (
            select(NotificationMute)
            .where(NotificationMute.user_id == user_id)
            .order_by(NotificationMute.created_at.desc())
        )
        return list((await self.db.execute(statement)).scalars().all())

    async def get(self, user_id: uuid.UUID, project_id: uuid.UUID) -> NotificationMute | None:
        statement = select(NotificationMute).where(
            NotificationMute.user_id == user_id,
            NotificationMute.project_id == project_id,
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def add(self, mute: NotificationMute) -> NotificationMute:
        self.db.add(mute)
        await self.db.flush()
        return mute

    async def delete(self, mute: NotificationMute) -> None:
        await self.db.delete(mute)
        await self.db.flush()
