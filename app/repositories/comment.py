"""Comment repository."""

import uuid

from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Comment


class CommentRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_in_org(self, comment_id: uuid.UUID, organization_id: uuid.UUID) -> Comment | None:
        statement = select(Comment).where(
            Comment.id == comment_id,
            Comment.organization_id == organization_id,
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def list_for_task(
        self,
        task_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Comment], int]:
        statement = (
            select(Comment)
            .where(Comment.task_id == task_id)
            .order_by(Comment.created_at.asc())
            .offset(offset)
            .limit(limit)
        )
        items = list((await self.db.execute(statement)).scalars().all())
        total = (
            (await self.db.execute(select(func.count(Comment.id)).where(Comment.task_id == task_id)))
            .scalar_one()
        )
        return items, total

    async def add(self, comment: Comment) -> Comment:
        self.db.add(comment)
        await self.db.flush()
        return comment

    async def update(self, comment: Comment) -> Comment:
        self.db.add(comment)
        await self.db.flush()
        return comment

    async def delete(self, comment: Comment) -> None:
        await self.db.delete(comment)
        await self.db.flush()
