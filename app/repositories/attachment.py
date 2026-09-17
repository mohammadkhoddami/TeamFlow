"""Attachment repository."""

import uuid
from datetime import datetime

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Attachment


class AttachmentRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_in_org(self, attachment_id: uuid.UUID, organization_id: uuid.UUID) -> Attachment | None:
        statement = select(Attachment).where(
            Attachment.id == attachment_id,
            Attachment.organization_id == organization_id,
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def list_for_task(self, task_id: uuid.UUID) -> list[Attachment]:
        statement = (
            select(Attachment)
            .where(Attachment.task_id == task_id)
            .order_by(Attachment.created_at.desc())
        )
        return list((await self.db.execute(statement)).scalars().all())

    async def pending_older_than(self, cutoff: datetime) -> list[Attachment]:
        statement = select(Attachment).where(
            Attachment.status == "pending",
            Attachment.created_at < cutoff,
        )
        return list((await self.db.execute(statement)).scalars().all())

    async def add(self, attachment: Attachment) -> Attachment:
        self.db.add(attachment)
        await self.db.flush()
        return attachment

    async def update(self, attachment: Attachment) -> Attachment:
        self.db.add(attachment)
        await self.db.flush()
        return attachment

    async def delete(self, attachment: Attachment) -> None:
        await self.db.delete(attachment)
        await self.db.flush()
