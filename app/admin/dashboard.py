"""Dashboard aggregates for the admin landing page.

Operator-facing counts, fetched fresh on every visit (unlike the API's
Redis-cached dashboard) so the numbers always reflect the live database.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.core.db import AsyncSessionLocal
from app.models import (
    Attachment,
    AuditLog,
    Comment,
    Membership,
    Notification,
    Organization,
    Project,
    ProjectStatus,
    Task,
    TaskStatus,
    User,
    Webhook,
)


async def collect_dashboard_stats() -> dict:
    now = datetime.now(UTC)
    day_ago = now - timedelta(hours=24)

    async with AsyncSessionLocal() as db:

        async def count(model, *where) -> int:
            stmt = select(func.count()).select_from(model)
            if where:
                stmt = stmt.where(*where)
            return int((await db.execute(stmt)).scalar_one())

        users_total = await count(User)
        users_active = await count(User, User.is_active.is_(True))
        users_superusers = await count(User, User.is_superuser.is_(True))
        organizations_total = await count(Organization)
        organizations_active = await count(Organization, Organization.is_active.is_(True))
        projects_total = await count(Project)
        projects_active = await count(Project, Project.status == ProjectStatus.ACTIVE)
        tasks_total = await count(Task)
        tasks_overdue = await count(
            Task,
            Task.due_date.is_not(None),
            Task.due_date < now,
            Task.status != TaskStatus.DONE,
        )
        memberships = await count(Membership)
        comments = await count(Comment)
        attachments = await count(Attachment)
        webhooks_active = await count(Webhook, Webhook.is_active.is_(True))
        notifications_unread = await count(
            Notification, Notification.read_at.is_(None)
        )
        audit_24h = await count(AuditLog, AuditLog.created_at >= day_ago)

        status_rows = (
            await db.execute(
                select(Task.status, func.count()).select_from(Task).group_by(Task.status)
            )
        ).all()
        tasks_by_status = {status: int(total) for status, total in status_rows}

        recent_users = list(
            (
                await db.execute(
                    select(User).order_by(User.created_at.desc()).limit(6)
                )
            ).scalars()
        )
        recent_organizations = list(
            (
                await db.execute(
                    select(Organization).order_by(Organization.created_at.desc()).limit(6)
                )
            ).scalars()
        )
        recent_tasks = list(
            (
                await db.execute(select(Task).order_by(Task.created_at.desc()).limit(6))
            ).scalars()
        )
        recent_audit = list(
            (
                await db.execute(
                    select(AuditLog)
                    .options(selectinload(AuditLog.actor))
                    .order_by(AuditLog.created_at.desc())
                    .limit(10)
                )
            ).scalars()
        )

    return {
        "users": {
            "total": users_total,
            "active": users_active,
            "superusers": users_superusers,
        },
        "organizations": {"total": organizations_total, "active": organizations_active},
        "projects": {"total": projects_total, "active": projects_active},
        "tasks": {
            "total": tasks_total,
            "overdue": tasks_overdue,
            "by_status": tasks_by_status,
            "statuses": TaskStatus.ALL,
        },
        "memberships": memberships,
        "comments": comments,
        "attachments": attachments,
        "webhooks_active": webhooks_active,
        "notifications_unread": notifications_unread,
        "audit_24h": audit_24h,
        "recent_users": recent_users,
        "recent_organizations": recent_organizations,
        "recent_tasks": recent_tasks,
        "recent_audit": recent_audit,
        "generated_at": now,
    }
