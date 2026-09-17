"""Invitation repository."""

import uuid

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Invitation, InvitationStatus


class InvitationRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, invitation_id: uuid.UUID) -> Invitation | None:
        return await self.db.get(Invitation, invitation_id)

    async def get_pending_for_email(
        self, organization_id: uuid.UUID, email: str
    ) -> Invitation | None:
        statement = select(Invitation).where(
            Invitation.organization_id == organization_id,
            Invitation.email == email,
            Invitation.status == InvitationStatus.PENDING,
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def list_for_org(
        self,
        organization_id: uuid.UUID,
        *,
        status: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[Invitation]:
        conds = [Invitation.organization_id == organization_id]
        if status:
            conds.append(Invitation.status == status)
        statement = (
            select(Invitation)
            .where(*conds)
            .order_by(Invitation.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list((await self.db.execute(statement)).scalars().all())

    async def list_pending_for_user(self, email: str) -> list[Invitation]:
        statement = (
            select(Invitation)
            .where(
                Invitation.email == email,
                Invitation.status == InvitationStatus.PENDING,
            )
            .order_by(Invitation.created_at.desc())
        )
        return list((await self.db.execute(statement)).scalars().all())

    async def add(self, invitation: Invitation) -> Invitation:
        self.db.add(invitation)
        await self.db.flush()
        return invitation

    async def update(self, invitation: Invitation) -> Invitation:
        self.db.add(invitation)
        await self.db.flush()
        return invitation

    async def delete(self, invitation: Invitation) -> None:
        await self.db.delete(invitation)
        await self.db.flush()
