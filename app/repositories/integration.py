"""Integration repository."""

import uuid

from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Integration, IntegrationEvent


class IntegrationRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, integration_id: uuid.UUID) -> Integration | None:
        statement = select(Integration).where(Integration.id == integration_id)
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def get_in_org(
        self, integration_id: uuid.UUID, organization_id: uuid.UUID
    ) -> Integration | None:
        statement = select(Integration).where(
            Integration.id == integration_id,
            Integration.organization_id == organization_id,
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def list_for_org(
        self, organization_id: uuid.UUID, *, provider: str | None = None
    ) -> list[Integration]:
        conds = [Integration.organization_id == organization_id]
        if provider is not None:
            conds.append(Integration.provider == provider)
        statement = select(Integration).where(*conds).order_by(Integration.created_at.asc())
        return list((await self.db.execute(statement)).scalars().all())

    async def list_active_for_event(
        self, organization_id: uuid.UUID, event: str
    ) -> list[Integration]:
        statement = select(Integration).where(
            Integration.organization_id == organization_id,
            Integration.is_active == True,  # noqa: E712
            Integration.provider.in_(("slack", "teams")),
        )
        integrations = list((await self.db.execute(statement)).scalars().all())
        return [entry for entry in integrations if event in (entry.events or [])]

    async def add(self, integration: Integration) -> Integration:
        self.db.add(integration)
        await self.db.flush()
        return integration

    async def update(self, integration: Integration) -> Integration:
        self.db.add(integration)
        await self.db.flush()
        return integration

    async def delete(self, integration: Integration) -> None:
        await self.db.delete(integration)
        await self.db.flush()

    # --- events ---------------------------------------------------------
    async def add_event(self, event: IntegrationEvent) -> IntegrationEvent:
        self.db.add(event)
        await self.db.flush()
        return event

    async def list_events(
        self,
        organization_id: uuid.UUID,
        *,
        integration_id: uuid.UUID | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[IntegrationEvent], int]:
        conds = [IntegrationEvent.organization_id == organization_id]
        if integration_id is not None:
            conds.append(IntegrationEvent.integration_id == integration_id)
        statement = (
            select(IntegrationEvent)
            .where(*conds)
            .order_by(IntegrationEvent.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        items = list((await self.db.execute(statement)).scalars().all())
        total = (
            await self.db.execute(
                select(func.count(IntegrationEvent.id)).where(*conds)
            )
        ).scalar_one()
        return items, int(total)
