"""Celery tasks: email, webhook delivery, cleanup, stats.

Workers use the *sync* engine/session (`app.core.db_sync`): running an async
loop inside Celery adds complexity with zero benefit for these short I/O
tasks. Repository classes are async-only, so workers query models directly —
the queries here are few and explicit.

Retry policies:
  - send_email: autoretry, exponential backoff + jitter, 3 attempts
  - deliver_webhook: manual retry with backoff; 4xx (except 408/429) is
    permanent; attempts + status persisted per delivery row (idempotent
    re-enqueue: already-successful deliveries short-circuit)
"""

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from celery import shared_task
from sqlalchemy import delete, select
from sqlalchemy import func as sa_func

from app.core.config import settings
from app.core.db_sync import session_scope
from app.models import IdempotencyKey
from app.services.integrations import webhook_signing

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    name="teamflow.send_email",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def send_email_task(self, to: str, kind: str, ctx: dict[str, str]) -> dict:
    """Transactional email via the console (mock) or SMTP backend."""
    from app.services.integrations.email import render, send_sync

    attempt = self.request.retries + 1
    logger.info("send_email kind=%s to=%s attempt=%s", kind, to, attempt)
    subject, body = render(kind, ctx)
    send_sync(to, subject, body)
    return {"status": "sent", "to": to, "kind": kind, "attempt": attempt}


@shared_task(
    bind=True, name="teamflow.deliver_webhook", max_retries=settings.webhook_max_retries
)
def deliver_webhook(self, delivery_id: str) -> dict:
    """HTTP POST with HMAC signature, timeout, and tracked retries.

    Idempotency: `X-TeamFlow-Delivery` (the delivery UUID) lets receivers
    dedupe redeliveries; an already-successful delivery short-circuits so
    duplicate enqueues never double-deliver."""
    from app.models import DeliveryStatus, Webhook, WebhookDelivery

    attempt = self.request.retries + 1
    with session_scope() as db:
        delivery = db.get(WebhookDelivery, uuid.UUID(delivery_id))
        if delivery is None:
            return {"status": "missing", "delivery_id": delivery_id}
        if delivery.status == DeliveryStatus.SUCCESS:
            return {"status": "already_delivered", "delivery_id": delivery_id}

        webhook = db.get(Webhook, delivery.webhook_id)
        if webhook is None or not webhook.is_active:
            delivery.status = DeliveryStatus.FAILED
            delivery.last_error = "webhook deleted or disabled"
            return {"status": "skipped", "delivery_id": delivery_id}

        body = json.dumps(delivery.payload).encode()
        timestamp = str(int(datetime.now(UTC).timestamp()))
        signature = webhook_signing.sign_payload(webhook.secret, timestamp, body)
        delivery.attempts = max(delivery.attempts, attempt)
        url, event = webhook.url, delivery.event
        # session_scope commits attempts bump + everything below on exit

    headers = {
        "Content-Type": "application/json",
        "X-TeamFlow-Event": event,
        "X-TeamFlow-Delivery": delivery_id,
        "X-TeamFlow-Timestamp": timestamp,
        "X-TeamFlow-Signature": signature,
    }
    from app.workers.celery_app import http_client

    client = http_client or httpx.Client(
        timeout=settings.webhook_timeout_seconds,
        trust_env=settings.webhook_httpx_trust_env,
    )
    try:
        response = client.post(url, content=body, headers=headers)
    except httpx.RequestError as exc:
        return _retry_or_fail(self, delivery_id, attempt, f"transport error: {exc}")

    verdict = _classify_response(response.status_code)
    with session_scope() as db:
        delivery = db.get(WebhookDelivery, uuid.UUID(delivery_id))
        if delivery is None:
            return {"status": "missing", "delivery_id": delivery_id}
        delivery.response_status = response.status_code
        if verdict == "success":
            delivery.status = DeliveryStatus.SUCCESS
            delivery.delivered_at = datetime.now(UTC)
            delivery.last_error = None
            return {"status": "delivered", "code": response.status_code}
        if verdict == "permanent":
            delivery.status = DeliveryStatus.FAILED
            delivery.last_error = f"HTTP {response.status_code} (permanent)"
            return {"status": "failed_permanently", "code": response.status_code}
        delivery.last_error = f"HTTP {response.status_code}"

    return _retry_or_fail(self, delivery_id, attempt, f"HTTP {response.status_code}")


def _classify_response(code: int) -> str:
    if 200 <= code < 300:
        return "success"
    if 400 <= code < 500 and code not in (408, 429):
        return "permanent"  # client errors will not heal; do not retry
    return "transient"


def _retry_or_fail(task, delivery_id: str, attempt: int, error: str) -> dict:
    from app.models import DeliveryStatus, WebhookDelivery

    with session_scope() as db:
        delivery = db.get(WebhookDelivery, uuid.UUID(delivery_id))
        if delivery is not None:
            delivery.last_error = error[:2000]
            delivery.attempts = max(delivery.attempts, attempt)
            if task.request.retries >= task.max_retries:
                delivery.status = DeliveryStatus.FAILED

    if task.request.retries >= task.max_retries:
        return {"status": "failed", "attempts": attempt}
    raise task.retry(exc=RuntimeError(error[:200]), countdown=min(5 * 2**attempt, 300))


@shared_task(name="teamflow.cleanup_expired_data")
def cleanup_expired_data() -> dict:
    """Beat job (every 6h): purge expired idempotency keys, stale pending
    attachments (24h+ old, object never uploaded), and re-enqueue webhook
    deliveries stranded `pending` by broker outages."""
    from app.models import Attachment, WebhookDelivery
    from app.workers.celery_app import celery_app

    removed = {"idempotency_keys": 0, "pending_attachments": 0, "deliveries_requeued": 0}
    with session_scope() as db:
        cutoff = datetime.now(UTC) - timedelta(hours=settings.idempotency_ttl_hours)
        result = db.execute(delete(IdempotencyKey).where(IdempotencyKey.created_at < cutoff))
        removed["idempotency_keys"] = int(result.rowcount or 0)

        stale = list(
            db.execute(
                select(Attachment).where(
                    Attachment.status == "pending",
                    Attachment.created_at < datetime.now(UTC) - timedelta(hours=24),
                )
            ).scalars()
        )
        for attachment in stale:
            try:
                from app.services.integrations.storage import StorageClient

                StorageClient.from_settings().remove(attachment.storage_key)
            except Exception:
                pass
            db.execute(delete(Attachment).where(Attachment.id == attachment.id))
            removed["pending_attachments"] += 1

        stranded = list(
            db.execute(
                select(WebhookDelivery).where(
                    WebhookDelivery.status == "pending",
                    WebhookDelivery.created_at < datetime.now(UTC) - timedelta(minutes=10),
                )
            ).scalars()
        )
        for delivery in stranded:
            if delivery.attempts <= settings.webhook_max_retries:
                celery_app.send_task("teamflow.deliver_webhook", [str(delivery.id)])
                removed["deliveries_requeued"] += 1
    return removed


@shared_task(name="teamflow.warm_dashboard_caches")
def warm_dashboard_caches() -> dict:
    """Beat job (hourly): precompute dashboard stats for every active org into
    the Redis cache so first viewers hit warm data."""
    import redis

    from app.models import Organization
    from app.services import dashboard as dashboard_service

    cache_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    warmed = 0
    with session_scope() as db:
        org_ids = list(
            db.execute(
                select(Organization.id).where(Organization.is_active == True)
            ).scalars()
        )
        for org_id in org_ids:
            stats = _compute_stats_sync(db, org_id)
            cache_client.set(
                dashboard_service.dashboard_key(org_id),
                json.dumps(stats, default=str),
                ex=dashboard_service.DASHBOARD_TTL_SECONDS,
            )
            warmed += 1
    return {"orgs_warmed": warmed}


def _compute_stats_sync(db, organization_id) -> dict:
    """Sync twin of dashboard.compute_stats for the worker (sync session)."""
    from app.models import Membership, Project, ProjectStatus, Task, TaskStatus, User

    by_status = {
        row[0]: row[1]
        for row in db.execute(
            select(Task.status, sa_func.count(Task.id))
            .where(Task.organization_id == organization_id)
            .group_by(Task.status)
        ).all()
    }
    now = datetime.now(UTC)
    extra = db.execute(
        select(
            sa_func.count(Task.id).filter(Task.due_date < now, Task.status != TaskStatus.DONE),
            sa_func.count(Task.id).filter(
                Task.assignee_id.is_(None), Task.status != TaskStatus.DONE
            ),
        ).where(Task.organization_id == organization_id)
    ).one()
    projects_total = db.execute(
        select(sa_func.count(Project.id)).where(Project.organization_id == organization_id)
    ).scalar_one()
    projects_active = db.execute(
        select(sa_func.count(Project.id)).where(
            Project.organization_id == organization_id,
            Project.status == ProjectStatus.ACTIVE,
        )
    ).scalar_one()
    active_members = db.execute(
        select(sa_func.count(Membership.id)).where(
            Membership.organization_id == organization_id,
            Membership.is_active == True,
        )
    ).scalar_one()
    per_member = db.execute(
        select(User.id, User.full_name, sa_func.count(Task.id))
        .join(Task, Task.assignee_id == User.id)
        .where(Task.organization_id == organization_id, Task.status != TaskStatus.DONE)
        .group_by(User.id, User.full_name)
        .order_by(sa_func.count(Task.id).desc())
        .limit(20)
    ).all()

    return {
        "projects": int(projects_total),
        "active_projects": int(projects_active),
        "total_tasks": int(sum(by_status.values())),
        "completed_tasks": int(by_status.get(TaskStatus.DONE, 0)),
        "overdue_tasks": int(extra[0] or 0),
        "unassigned_tasks": int(extra[1] or 0),
        "tasks_by_status": {
            "todo": int(by_status.get(TaskStatus.TODO, 0)),
            "in_progress": int(by_status.get(TaskStatus.IN_PROGRESS, 0)),
            "in_review": int(by_status.get(TaskStatus.IN_REVIEW, 0)),
            "done": int(by_status.get(TaskStatus.DONE, 0)),
        },
        "tasks_per_member": [
            {"user_id": str(row[0]), "full_name": row[1], "open_tasks": int(row[2])}
            for row in per_member
        ],
        "active_members": int(active_members),
    }


@shared_task(name="teamflow.send_notification_digests")
def send_notification_digests(cadence: str | None = None) -> dict:
    """Beat job (daily): email users whose preference is a daily/weekly digest.

    Collects unread notifications from the period and sends one summary email.
    Immediate-cadence users get their emails inline from the API instead.
    """
    from app.models import Notification, NotificationPreference, User
    from app.workers.celery_app import celery_app

    now = datetime.now(UTC)
    sent = 0
    with session_scope() as db:
        cadences = [cadence] if cadence else ["daily", "weekly"]
        preferences = list(
            db.execute(
                select(NotificationPreference).where(
                    NotificationPreference.email_enabled == True,
                    NotificationPreference.digest.in_(cadences),
                )
            ).scalars()
        )
        user_ids = [preference.user_id for preference in preferences]
        users = {
            user.id: user
            for user in db.execute(select(User).where(User.id.in_(user_ids))).scalars()
        }
        for preference in preferences:
            user = users.get(preference.user_id)
            if user is None or not user.is_active:
                continue
            period = (
                timedelta(days=7)
                if preference.digest == "weekly"
                else timedelta(days=1)
            )
            unread = list(
                db.execute(
                    select(Notification)
                    .where(
                        Notification.user_id == preference.user_id,
                        Notification.read_at.is_(None),
                        Notification.created_at >= now - period,
                    )
                    .order_by(Notification.created_at.desc())
                    .limit(50)
                ).scalars()
            )
            if not unread:
                continue
            lines = "\n".join(f"- {entry.title}" for entry in unread)
            celery_app.send_task(
                "teamflow.send_email",
                [
                    user.email,
                    "notification_digest",
                    {
                        "count": str(len(unread)),
                        "lines": lines,
                        "frontend_url": settings.frontend_base_url,
                        "unsubscribe_url": (
                            f"{settings.frontend_base_url}/unsubscribe"
                            f"?token={preference.unsubscribe_token}"
                        ),
                    },
                ],
            )
            sent += 1
    return {"sent": sent}


@shared_task(name="teamflow.notify_due_tasks")
def notify_due_tasks() -> dict:
    """Beat job (daily): remind watchers about tasks due within 24 hours."""
    from app.models import Notification, Task, TaskStatus

    cutoff = datetime.now(UTC) + timedelta(hours=24)
    notified = 0
    with session_scope() as db:
        tasks = list(
            db.execute(
                select(Task).where(
                    Task.due_date.is_not(None),
                    Task.due_date <= cutoff,
                    Task.status != TaskStatus.DONE,
                )
            ).scalars()
        )
        for task in tasks:
            for watcher in task.watchers:
                db.add(
                    Notification(
                        user_id=watcher.id,
                        organization_id=task.organization_id,
                        type="task_due_soon",
                        title=f"Due soon: {task.title}",
                        data={"task_id": str(task.id)},
                    )
                )
                notified += 1
    return {"notified": notified}

