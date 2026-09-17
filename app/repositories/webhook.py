"""Webhook + delivery repositories."""

import uuid
from datetime import datetime

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Webhook, WebhookDelivery


class WebhookRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_in_org(self, webhook_id: uuid.UUID, organization_id: uuid.UUID) -> Webhook | None:
        statement = select(Webhook).where(
            Webhook.id == webhook_id,
            Webhook.organization_id == organization_id,
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def list_for_org(self, organization_id: uuid.UUID) -> list[Webhook]:
        statement = (
            select(Webhook)
            .where(Webhook.organization_id == organization_id)
            .order_by(Webhook.created_at.desc())
        )
        return list((await self.db.execute(statement)).scalars().all())

    async def active_for_org_and_event(
        self, organization_id: uuid.UUID, event: str
    ) -> list[Webhook]:
        """Filter in Python: webhook counts per org are tiny; keeps the query
        portable across PG/SQLite without JSON-array dialect gymnastics."""
        statement = select(Webhook).where(
            Webhook.organization_id == organization_id,
            Webhook.is_active == True,  # noqa: E712
        )
        webhooks = list((await self.db.execute(statement)).scalars().all())
        return [w for w in webhooks if event in (w.events or [])]

    async def add(self, webhook: Webhook) -> Webhook:
        self.db.add(webhook)
        await self.db.flush()
        return webhook

    async def update(self, webhook: Webhook) -> Webhook:
        self.db.add(webhook)
        await self.db.flush()
        return webhook

    async def delete(self, webhook: Webhook) -> None:
        await self.db.delete(webhook)
        await self.db.flush()


class WebhookDeliveryRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, delivery_id: uuid.UUID) -> WebhookDelivery | None:
        return await self.db.get(WebhookDelivery, delivery_id)

    async def list_for_webhook(
        self,
        webhook_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> list[WebhookDelivery]:
        statement = (
            select(WebhookDelivery)
            .where(WebhookDelivery.webhook_id == webhook_id)
            .order_by(WebhookDelivery.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list((await self.db.execute(statement)).scalars().all())

    async def stale_pending(self, older_than: datetime) -> list[WebhookDelivery]:
        statement = select(WebhookDelivery).where(
            WebhookDelivery.status == "pending",
            WebhookDelivery.created_at < older_than,
        )
        return list((await self.db.execute(statement)).scalars().all())

    async def add(self, delivery: WebhookDelivery) -> WebhookDelivery:
        self.db.add(delivery)
        await self.db.flush()
        return delivery

    async def update(self, delivery: WebhookDelivery) -> WebhookDelivery:
        self.db.add(delivery)
        await self.db.flush()
        return delivery
