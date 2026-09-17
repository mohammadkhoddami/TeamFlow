"""Realtime event publishing and in-app notification fan-out.

WS events travel: caller -> Redis pub/sub (channel `teamflow:ws`) -> every
FastAPI worker's listener -> local ConnectionManager -> sockets. Publishing is
available from anywhere (API, worker); delivery scales to any worker count.

Webhook fan-out: match active org webhooks, create a persisted delivery row
per webhook, then enqueue the Celery delivery task off the event loop.
"""

import json
import logging
import uuid
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.redis import get_redis_client
from app.models import Notification, WebhookDelivery
from app.repositories import NotificationRepository, WebhookDeliveryRepository
from app.services.audit import now_iso
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

WS_CHANNEL = "teamflow:ws"


async def publish(
    channel: str, event_type: str, data: dict[str, Any] | None = None
) -> None:
    """Fan an event out through Redis pub/sub. Failures must not break the
    business operation: log and continue."""
    payload = {"channel": channel, "event": {"type": event_type, "data": data or {}, "ts": now_iso()}}
    try:
        await get_redis_client().publish(WS_CHANNEL, json.dumps(payload))
    except Exception:
        logger.exception("Failed to publish realtime event %s", event_type)


async def publish_project_event(
    project_id: uuid.UUID, event_type: str, data: dict[str, Any] | None = None
) -> None:
    await publish(f"project:{project_id}", event_type, data)


async def publish_user_event(
    user_id: uuid.UUID, event_type: str, data: dict[str, Any] | None = None
) -> None:
    await publish(f"user:{user_id}", event_type, data)


async def notify(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    type: str,
    title: str,
    body: str | None = None,
    data: dict | None = None,
    organization_id: uuid.UUID | None = None,
) -> Notification:
    notification = Notification(
        user_id=user_id,
        organization_id=organization_id,
        type=type,
        title=title,
        body=body,
        data=data,
    )
    notification = await NotificationRepository(db).add(notification)
    await publish_user_event(
        user_id,
        "notification",
        {
            "id": str(notification.id),
            "type": type,
            "title": title,
            "organization_id": str(organization_id) if organization_id else None,
        },
    )
    return notification


async def notify_many(
    db: AsyncSession,
    *,
    user_ids: list[uuid.UUID],
    type: str,
    title: str,
    body: str | None = None,
    data: dict | None = None,
    organization_id: uuid.UUID | None = None,
) -> None:
    for user_id in dict.fromkeys(user_ids):  # dedupe, keep order
        await notify(
            db,
            user_id=user_id,
            type=type,
            title=title,
            body=body,
            data=data,
            organization_id=organization_id,
        )


async def notify_member_joined(
    db: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID, org_name: str
) -> None:
    await notify(
        db,
        user_id=user_id,
        type="member_joined",
        title=f"You joined {org_name}",
        organization_id=organization_id,
    )


async def dispatch_webhooks(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    event: str,
    data: dict[str, Any],
) -> None:
    """Create one persisted delivery per matching webhook, then enqueue.

    Transaction ordering matters here: this runs *after* the business
    operation has committed, so this method commits the delivery rows itself
    (before enqueueing) — a broker outage then leaves rows `pending` for the
    cleanup/sweeper to retry instead of silently losing the event.

    Idempotency: each delivery has a UUID used as the `X-TeamFlow-Delivery`
    header so receivers can dedupe redeliveries caused by retries.
    """
    from app.repositories import WebhookRepository

    matching = await WebhookRepository(db).active_for_org_and_event(organization_id, event)
    if not matching:
        return

    delivery_repo = WebhookDeliveryRepository(db)
    pending: list[WebhookDelivery] = []
    for webhook in matching:
        delivery = await delivery_repo.add(
            WebhookDelivery(
                webhook_id=webhook.id,
                event=event,
                payload={
                    "id": None,  # filled after flush (delivery PK)
                    "event": event,
                    "organization_id": str(organization_id),
                    "created_at": now_iso(),
                    "data": data,
                },
            )
        )
        delivery.payload["id"] = str(delivery.id)
        pending.append(delivery)

    await db.commit()  # deliveries are durable before any enqueue attempt

    for delivery in pending:
        try:
            await run_in_threadpool(
                celery_app.send_task, "teamflow.deliver_webhook", [str(delivery.id)]
            )
        except Exception:
            # Delivery row is already committed: the sweeper task re-enqueues
            # stale pending deliveries, so we log and continue.
            logger.exception("Failed to enqueue webhook delivery %s", delivery.id)
