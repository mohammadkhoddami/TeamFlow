"""Time tracking service: worklogs, actual-estimate sync, timesheets."""

import uuid
from datetime import UTC, datetime, time, timedelta

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.models import (
    AuditAction,
    Membership,
    MembershipRole,
    Organization,
    Task,
    User,
    Worklog,
)
from app.repositories import TaskRepository, WorklogRepository
from app.schemas import WorklogCreate, WorklogUpdate
from app.services import audit


async def _sync_actual_estimate(db: AsyncSession, task_id: uuid.UUID) -> None:
    totals = await WorklogRepository(db).total_minutes_for_tasks([task_id])
    task = await TaskRepository(db).get(task_id)
    if task is None:
        return
    minutes = totals.get(task_id, 0)
    task.actual_estimate = round(minutes / 60, 2) if minutes else None
    await TaskRepository(db).update(task)


async def list_worklogs(
    db: AsyncSession, task_id: uuid.UUID, *, offset: int = 0, limit: int = 100
) -> list[Worklog]:
    return await WorklogRepository(db).list_for_task(
        task_id, offset=offset, limit=limit
    )


async def create_worklog(
    db: AsyncSession,
    actor: User,
    org: Organization,
    task: Task,
    data: WorklogCreate,
    ip: str | None = None,
) -> Worklog:
    if data.started_at.tzinfo is None:
        data = data.model_copy(update={"started_at": data.started_at.replace(tzinfo=UTC)})
    worklog = await WorklogRepository(db).add(
        Worklog(
            organization_id=org.id,
            task_id=task.id,
            user_id=actor.id,
            minutes=data.minutes,
            started_at=data.started_at,
            description=data.description,
        )
    )
    await _sync_actual_estimate(db, task.id)
    await audit.log(
        db, AuditAction.TASK_UPDATED, actor_id=actor.id,
        organization_id=org.id, target_type="worklog", target_id=worklog.id, ip=ip,
        meta={"task_id": str(task.id), "minutes": data.minutes},
    )
    await db.commit()
    await db.refresh(worklog)
    return worklog


async def update_worklog(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    worklog: Worklog,
    data: WorklogUpdate,
    ip: str | None = None,
) -> Worklog:
    if worklog.user_id != actor.id and membership.role == MembershipRole.MEMBER:
        raise PermissionDeniedError("Only the author (or managers+) can edit a worklog")
    changed = data.model_fields_set
    if "minutes" in changed and data.minutes is not None:
        worklog.minutes = data.minutes
    if "started_at" in changed and data.started_at is not None:
        started = data.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        worklog.started_at = started
    if "description" in changed:
        worklog.description = data.description
    worklog = await WorklogRepository(db).update(worklog)
    await _sync_actual_estimate(db, worklog.task_id)
    await db.commit()
    return worklog


async def delete_worklog(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    worklog: Worklog,
    ip: str | None = None,
) -> None:
    if worklog.user_id != actor.id and membership.role == MembershipRole.MEMBER:
        raise PermissionDeniedError("Only the author (or managers+) can delete a worklog")
    task_id = worklog.task_id
    await WorklogRepository(db).delete(worklog)
    await _sync_actual_estimate(db, task_id)
    await db.commit()


async def get_worklog_for_org(
    db: AsyncSession, worklog_id: uuid.UUID, organization_id: uuid.UUID
) -> Worklog:
    worklog = await WorklogRepository(db).get_in_org(worklog_id, organization_id)
    if not worklog:
        raise NotFoundError("Worklog not found")
    return worklog


async def timesheet(
    db: AsyncSession,
    organization_id: uuid.UUID,
    date_from: datetime,
    date_to: datetime,
    user_id: uuid.UUID | None = None,
) -> dict:
    rows = await WorklogRepository(db).list_for_org(
        organization_id,
        date_from=date_from,
        date_to=date_to,
        user_id=user_id,
    )
    entries: list[dict] = []
    totals: dict[uuid.UUID | None, dict] = {}
    for worklog, task in rows:
        user = worklog.user
        name = (user.full_name or user.email) if user else "(removed)"
        entries.append(
            {
                "day": worklog.started_at.date(),
                "user_id": worklog.user_id,
                "user_name": name,
                "task_id": task.id,
                "task_key": task.key,
                "task_title": task.title,
                "minutes": worklog.minutes,
            }
        )
        bucket = totals.setdefault(
            worklog.user_id, {"user_id": worklog.user_id, "user_name": name, "minutes": 0}
        )
        bucket["minutes"] += worklog.minutes
    return {
        "date_from": date_from.date(),
        "date_to": (date_to - time.resolution).date(),
        "total_minutes": sum(entry["minutes"] for entry in entries),
        "rows": entries,
        "totals_by_user": sorted(
            totals.values(), key=lambda entry: -entry["minutes"]
        ),
    }


def default_window(
    date_from: datetime | None, date_to: datetime | None
) -> tuple[datetime, datetime]:
    now = datetime.now(UTC)
    start = date_from or datetime.combine(
        (now - timedelta(days=6)).date(), time.min, tzinfo=UTC
    )
    end = date_to or datetime.combine(now.date(), time.max, tzinfo=UTC)
    return start, end
