"""Webhook routes: registration (secret shown once), deliveries."""

import uuid

from fastapi import APIRouter, Query, Request, status

from app.api.deps import DB, CurrentUser, OrgMembership
from app.schemas import (
    WebhookCreate,
    WebhookCreated,
    WebhookDeliveryRead,
    WebhookRead,
    WebhookUpdate,
)
from app.services import webhooks as webhook_service

router = APIRouter(prefix="/organizations/{slug}/webhooks", tags=["webhooks"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("", status_code=status.HTTP_201_CREATED, response_model=WebhookCreated)
async def create_webhook(
    data: WebhookCreate,
    membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> WebhookCreated:
    org, m = membership
    webhook, secret = await webhook_service.create_webhook(
        db, current_user, org, m, str(data.url), list(data.events),
        data.description, ip=_ip(request),
    )
    return WebhookCreated(
        id=webhook.id,
        url=webhook.url,
        events=webhook.events,
        is_active=webhook.is_active,
        description=webhook.description,
        secret=secret,
        created_at=webhook.created_at,
    )


@router.get("", response_model=list[WebhookRead])
async def list_webhooks(membership: OrgMembership, db: DB) -> list[WebhookRead]:
    org, _m = membership
    webhooks = await webhook_service.list_webhooks(db, org.id)
    return [WebhookRead.model_validate(w) for w in webhooks]


@router.patch("/{webhook_id}", response_model=WebhookRead)
async def update_webhook(
    webhook_id: uuid.UUID,
    data: WebhookUpdate,
    membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> WebhookRead:
    org, m = membership
    webhook = await webhook_service.get_webhook_for_org(db, webhook_id, org.id)
    updated = await webhook_service.update_webhook(
        db, current_user, org, m, webhook, data, ip=_ip(request)
    )
    return WebhookRead.model_validate(updated)


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(
    webhook_id: uuid.UUID,
    membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> None:
    org, m = membership
    webhook = await webhook_service.get_webhook_for_org(db, webhook_id, org.id)
    await webhook_service.delete_webhook(db, current_user, org, m, webhook, ip=_ip(request))


@router.get("/{webhook_id}/deliveries", response_model=list[WebhookDeliveryRead])
async def list_deliveries(
    webhook_id: uuid.UUID,
    membership: OrgMembership,
    db: DB,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[WebhookDeliveryRead]:
    org, _m = membership
    await webhook_service.get_webhook_for_org(db, webhook_id, org.id)
    deliveries = await webhook_service.list_deliveries(
        db, webhook_id, offset=offset, limit=limit
    )
    return [WebhookDeliveryRead.model_validate(d) for d in deliveries]
