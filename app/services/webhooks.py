"""Webhook CRUD service. Delivery execution lives in the Celery worker."""

import secrets
import uuid

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.models import (
    AuditAction,
    Membership,
    MembershipRole,
    Organization,
    User,
    Webhook,
)
from app.repositories import WebhookRepository
from app.schemas import WebhookUpdate
from app.services import audit


def _require_admin(membership: Membership) -> None:
    if membership.role not in (MembershipRole.ADMIN, MembershipRole.OWNER):
        raise PermissionDeniedError("Only admins and owners can manage webhooks")


def generate_secret() -> str:
    return secrets.token_urlsafe(32)


async def create_webhook(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    url: str,
    events: list[str],
    description: str | None = None,
    ip: str | None = None,
) -> tuple[Webhook, str]:
    _require_admin(membership)
    secret = generate_secret()
    webhook = await WebhookRepository(db).add(
        Webhook(
            organization_id=org.id,
            url=url,
            secret=secret,
            events=events,
            description=description,
            created_by_id=actor.id,
        )
    )
    await audit.log(
        db, AuditAction.WEBHOOK_CREATED, actor_id=actor.id,
        organization_id=org.id, target_type="webhook", target_id=webhook.id, ip=ip,
        meta={"url": url, "events": events},
    )
    await db.commit()
    await db.refresh(webhook)
    return webhook, secret


async def list_webhooks(db: AsyncSession, organization_id: uuid.UUID) -> list[Webhook]:
    return await WebhookRepository(db).list_for_org(organization_id)


async def get_webhook_for_org(
    db: AsyncSession, webhook_id: uuid.UUID, organization_id: uuid.UUID
) -> Webhook:
    webhook = await WebhookRepository(db).get_in_org(webhook_id, organization_id)
    if not webhook:
        raise NotFoundError("Webhook not found")
    return webhook


async def update_webhook(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    webhook: Webhook,
    data: WebhookUpdate,
    ip: str | None = None,
) -> Webhook:
    _require_admin(membership)
    if data.url is not None:
        webhook.url = str(data.url)
    if data.events is not None:
        webhook.events = list(data.events)
    if data.is_active is not None:
        webhook.is_active = data.is_active
    if data.description is not None:
        webhook.description = data.description
    webhook = await WebhookRepository(db).update(webhook)
    await db.commit()
    return webhook


async def delete_webhook(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    webhook: Webhook,
    ip: str | None = None,
) -> None:
    _require_admin(membership)
    await audit.log(
        db, AuditAction.WEBHOOK_DELETED, actor_id=actor.id,
        organization_id=org.id, target_type="webhook", target_id=webhook.id, ip=ip,
    )
    await WebhookRepository(db).delete(webhook)
    await db.commit()


async def list_deliveries(
    db: AsyncSession, webhook_id: uuid.UUID, *, offset: int = 0, limit: int = 50
) -> list:
    from app.repositories import WebhookDeliveryRepository

    return await WebhookDeliveryRepository(db).list_for_webhook(
        webhook_id, offset=offset, limit=limit
    )
