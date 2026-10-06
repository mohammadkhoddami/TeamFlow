"""Notification preference service + preference-gated email enqueueing.

In-app notifications are always created (the bell is cheap and expected);
email is opt-in per type and cadence. `task_email` is the single gate every
caller uses before enqueueing a transactional email.
"""

import logging
import uuid

from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.models import NotificationPreference, User
from app.repositories import PreferenceRepository, UserRepository
from app.schemas import NotificationPreferenceUpdate
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

# Notification types that default to email-on when a user has no preference row.
DEFAULT_ALLOWED = {"task_assigned", "mention", "task_due_soon", "task_completed"}


async def get_or_create(db: AsyncSession, user: User) -> NotificationPreference:
    repo = PreferenceRepository(db)
    preference = await repo.get_for_user(user.id)
    if preference is None:
        preference = await repo.add(NotificationPreference(user_id=user.id))
        await db.commit()
    return preference


async def update(
    db: AsyncSession, user: User, data: NotificationPreferenceUpdate
) -> NotificationPreference:
    preference = await get_or_create(db, user)
    changed = data.model_fields_set
    for field in (
        "email_enabled",
        "assigned",
        "mentioned",
        "comments",
        "due",
        "digest",
    ):
        if field in changed and getattr(data, field) is not None:
            setattr(preference, field, getattr(data, field))
    preference = await PreferenceRepository(db).update(preference)
    await db.commit()
    return preference


async def unsubscribe(db: AsyncSession, token: str) -> bool:
    preference = await PreferenceRepository(db).get_by_unsubscribe_token(token)
    if preference is None:
        return False
    preference.email_enabled = False
    await PreferenceRepository(db).update(preference)
    await db.commit()
    return True


def unsubscribe_url(preference: NotificationPreference) -> str:
    return f"{settings.frontend_base_url}/unsubscribe?token={preference.unsubscribe_token}"


async def _allows_email(db: AsyncSession, user_id: uuid.UUID, notification_type: str) -> bool:
    preference = await PreferenceRepository(db).get_for_user(user_id)
    if preference is None:
        return notification_type in DEFAULT_ALLOWED
    return preference.allows(notification_type)


async def task_email(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    notification_type: str,
    kind: str,
    task,
    project,
    org_slug: str,
    extra_context: dict[str, str] | None = None,
) -> None:
    """Enqueue a transactional email when the recipient's prefs allow it.

    Runs after the business transaction committed; failures here must never
    break the API call, so enqueue errors are swallowed (the in-app
    notification remains the source of truth)."""
    if not await _allows_email(db, user_id, notification_type):
        return
    user = await UserRepository(db).get(user_id)
    if user is None or not user.is_active:
        return
    preference = await PreferenceRepository(db).get_for_user(user_id)
    unsub = (
        unsubscribe_url(preference)
        if preference is not None
        else f"{settings.frontend_base_url}/settings"
    )
    context = {
        "task_title": task.title,
        "task_key": task.key or "",
        "project_name": project.name,
        "task_url": f"{settings.frontend_base_url}/org/{org_slug}/tasks?task={task.id}",
        "unsubscribe_url": unsub,
    }
    if extra_context:
        context.update(extra_context)
    try:
        await run_in_threadpool(
            celery_app.send_task, "teamflow.send_email", [user.email, kind, context]
        )
    except Exception:  # broker outage: in-app notification already persisted
        logger.exception("Failed to enqueue %s email for %s", kind, user.id)
