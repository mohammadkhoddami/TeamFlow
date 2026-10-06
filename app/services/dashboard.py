"""Dashboard service: efficient SQL aggregation + short-TTL Redis cache.

All statistics are computed in the database (COUNT/GROUP BY/CASE) — no task
rows are ever loaded into Python. One connection round trip per aggregate
group; the cache absorbs repeated dash polling.
"""

import uuid

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Membership, Project, ProjectStatus, Task, TaskStatus, User
from app.services import cache


async def compute_stats(db: AsyncSession, organization_id: uuid.UUID) -> dict:
    # Buckets follow the workflow *category* so custom statuses roll up into
    # the canonical four columns.
    by_status_rows = (
        await db.execute(
            select(Task.status_category, func.count(Task.id))
            .where(Task.organization_id == organization_id)
            .group_by(Task.status_category)
        )
    ).all()
    by_status = {row[0]: row[1] for row in by_status_rows}

    now = func.now()
    total_tasks = sum(by_status.values())
    # Overdue and unassigned ride in a single aggregate query.
    extra = (
        await db.execute(
            select(
                func.count(Task.id).filter(
                    Task.due_date < now, Task.status_category != TaskStatus.DONE
                ),
                func.count(Task.id).filter(
                    Task.assignee_id.is_(None), Task.status_category != TaskStatus.DONE
                ),
            ).where(Task.organization_id == organization_id)
        )
    ).one()
    overdue_tasks, unassigned_tasks = int(extra[0] or 0), int(extra[1] or 0)

    projects_total = (
        await db.execute(
            select(func.count(Project.id)).where(Project.organization_id == organization_id)
        )
    ).scalar_one()
    projects_active = (
        await db.execute(
            select(func.count(Project.id)).where(
                Project.organization_id == organization_id,
                Project.status == ProjectStatus.ACTIVE,
            )
        )
    ).scalar_one()

    active_members = (
        await db.execute(
            select(func.count(Membership.id)).where(
                Membership.organization_id == organization_id,
                Membership.is_active == True,
            )
        )
    ).scalar_one()

    per_member_rows = (
        await db.execute(
            select(User.id, User.full_name, func.count(Task.id))
            .join(Task, Task.assignee_id == User.id)
            .where(
                Task.organization_id == organization_id,
                Task.status_category != TaskStatus.DONE,
            )
            .group_by(User.id, User.full_name)
            .order_by(func.count(Task.id).desc())
            .limit(20)
        )
    ).all()

    return {
        "projects": int(projects_total),
        "active_projects": int(projects_active),
        "total_tasks": int(total_tasks),
        "completed_tasks": int(by_status.get(TaskStatus.DONE, 0)),
        "overdue_tasks": overdue_tasks,
        "unassigned_tasks": unassigned_tasks,
        "tasks_by_status": {
            "todo": int(by_status.get(TaskStatus.TODO, 0)),
            "in_progress": int(by_status.get(TaskStatus.IN_PROGRESS, 0)),
            "in_review": int(by_status.get(TaskStatus.IN_REVIEW, 0)),
            "done": int(by_status.get(TaskStatus.DONE, 0)),
        },
        "tasks_per_member": [
            {"user_id": str(row[0]), "full_name": row[1], "open_tasks": int(row[2])}
            for row in per_member_rows
        ],
        "active_members": int(active_members),
    }


async def get_dashboard(
    db: AsyncSession, redis_client, organization_id: uuid.UUID, *, use_cache: bool = True
) -> dict:
    if use_cache:
        cached = await cache.get_dashboard_cache(redis_client, organization_id)
        if cached is not None:
            return cached
    stats = await compute_stats(db, organization_id)
    await cache.set_dashboard_cache(redis_client, organization_id, stats)
    return stats
