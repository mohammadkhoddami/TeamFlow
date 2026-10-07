"""Sprint capacity service: who is overloaded?"""

import uuid

from sqlalchemy import case, func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import PermissionDeniedError, ValidationFailedError
from app.models import (
    Membership,
    MembershipRole,
    Organization,
    Sprint,
    SprintCapacity,
    Task,
    TaskStatus,
    User,
)
from app.repositories import CapacityRepository, MembershipRepository
from app.schemas import CapacityUpdate


def _require_manage(membership: Membership) -> None:
    if membership.role == MembershipRole.MEMBER:
        raise PermissionDeniedError("Only managers and above can edit capacity")


async def get_capacity(
    db: AsyncSession, org_id: uuid.UUID, sprint: Sprint
) -> list[dict]:
    capacities = {
        entry.user_id: entry
        for entry in await CapacityRepository(db).list_for_sprint(sprint.id)
    }
    assignments = (
        await db.execute(
            select(
                Task.assignee_id,
                func.count(Task.id),
                func.coalesce(func.sum(Task.estimate), 0),
                func.coalesce(
                    func.sum(
                        case(
                            (Task.status_category == TaskStatus.DONE, Task.estimate),
                            else_=0,
                        )
                    ),
                    0,
                ),
            )
            .where(
                Task.organization_id == org_id,
                Task.sprint_id == sprint.id,
                Task.archived_at.is_(None),
                Task.assignee_id.is_not(None),
            )
            .group_by(Task.assignee_id)
        )
    ).all()
    by_user = {
        row[0]: {
            "assigned_tasks": int(row[1]),
            "assigned_points": float(row[2] or 0),
            "completed_points": float(row[3] or 0),
        }
        for row in assignments
    }

    members = await MembershipRepository(db).list_for_org(org_id, limit=1000)
    result: list[dict] = []
    for membership in members:
        if membership.user is None:
            continue
        stats = by_user.get(
            membership.user_id,
            {"assigned_tasks": 0, "assigned_points": 0.0, "completed_points": 0.0},
        )
        entry = capacities.get(membership.user_id)
        capacity = entry.capacity if entry else None
        overloaded = bool(
            capacity is not None and stats["assigned_points"] > capacity
        )
        result.append(
            {
                "user_id": membership.user_id,
                "name": membership.user.full_name or membership.user.email,
                "capacity": capacity,
                "note": entry.note if entry else None,
                **stats,
                "overloaded": overloaded,
            }
        )
    result.sort(key=lambda row: (-row["assigned_points"], row["name"]))
    return result


async def set_capacity(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    sprint: Sprint,
    data: CapacityUpdate,
) -> list[dict]:
    _require_manage(membership)
    seen: set[uuid.UUID] = set()
    for entry in data.entries:
        if entry.user_id in seen:
            raise ValidationFailedError("Duplicate member in capacity update")
        seen.add(entry.user_id)
        member = await MembershipRepository(db).get_for_user(entry.user_id, org.id)
        if member is None or not member.is_active:
            raise ValidationFailedError("Capacity can only reference active members")
    repo = CapacityRepository(db)
    existing = {row.user_id: row for row in await repo.list_for_sprint(sprint.id)}
    for entry in data.entries:
        row = existing.pop(entry.user_id, None)
        if entry.capacity is None and row is not None:
            await repo.delete(row)
            continue
        if entry.capacity is None:
            continue
        if row is None:
            row = SprintCapacity(
                organization_id=org.id,
                sprint_id=sprint.id,
                user_id=entry.user_id,
                capacity=entry.capacity,
                note=entry.note,
            )
            await repo.add(row)
        else:
            row.capacity = entry.capacity
            row.note = entry.note
            await db.flush()
    for row in existing.values():
        await repo.delete(row)
    await db.commit()
    return await get_capacity(db, org.id, sprint)
