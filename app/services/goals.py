"""Goals/OKR service (M4).

Progress roll-up:
  - a linked task with direct children counts as `done_children / children`
    (via the batched `TaskRepository.child_stats` query)
  - a leaf counts as 100% only when its status category is `done`
  - the goal's own progress is the rounded mean of its tasks' fractions

Reads batch every lookup (links, tasks, child stats, owners) so a goal list
never issues per-goal or per-task queries.
"""

import uuid

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import NotFoundError, ValidationFailedError
from app.models import Goal, GoalLink, Organization, Task, TaskStatus, User
from app.repositories import MembershipRepository, TaskRepository
from app.schemas.goal import GoalCreate, GoalUpdate


async def _assert_owner_in_org(
    db: AsyncSession, org_id: uuid.UUID, owner_id: uuid.UUID
) -> None:
    membership = await MembershipRepository(db).get_for_user(owner_id, org_id)
    if not membership or not membership.is_active:
        raise ValidationFailedError(
            "Owner must be an active member of this organization"
        )


async def create_goal(
    db: AsyncSession, actor: User, org: Organization, data: GoalCreate
) -> Goal:
    if data.owner_id is not None:
        await _assert_owner_in_org(db, org.id, data.owner_id)
    goal = Goal(
        organization_id=org.id,
        name=data.name,
        description=data.description,
        status=data.status,
        due_date=data.due_date,
        owner_id=data.owner_id or actor.id,
        created_by_id=actor.id,
    )
    db.add(goal)
    await db.flush()
    await db.commit()
    return goal


async def list_goals(db: AsyncSession, org_id: uuid.UUID) -> list[Goal]:
    statement = (
        select(Goal)
        .where(Goal.organization_id == org_id)
        .order_by(Goal.created_at.desc())
    )
    return list((await db.execute(statement)).scalars().all())


async def get_goal_for_org(
    db: AsyncSession, goal_id: uuid.UUID, organization_id: uuid.UUID
) -> Goal:
    statement = select(Goal).where(
        Goal.id == goal_id, Goal.organization_id == organization_id
    )
    goal = (await db.execute(statement)).scalar_one_or_none()
    if goal is None:
        # 404 hides cross-org goal IDs (IDOR containment).
        raise NotFoundError("Goal not found")
    return goal


async def update_goal(
    db: AsyncSession,
    actor: User,
    org: Organization,
    goal: Goal,
    data: GoalUpdate,
) -> Goal:
    changed = data.model_fields_set
    if "owner_id" in changed and data.owner_id is not None:
        await _assert_owner_in_org(db, org.id, data.owner_id)
    if "name" in changed and data.name is not None:
        goal.name = data.name
    if "description" in changed:
        goal.description = data.description
    if "status" in changed and data.status is not None:
        goal.status = data.status
    if "due_date" in changed:
        goal.due_date = data.due_date
    if "owner_id" in changed:
        goal.owner_id = data.owner_id
    db.add(goal)
    await db.flush()
    await db.commit()
    return goal


async def delete_goal(
    db: AsyncSession, actor: User, org: Organization, goal: Goal
) -> None:
    await db.delete(goal)
    await db.commit()


async def link_tasks(
    db: AsyncSession,
    actor: User,
    org: Organization,
    goal: Goal,
    task_ids: list[uuid.UUID],
) -> None:
    """Links org tasks to the goal; already-linked IDs are ignored."""
    unique_ids = list(dict.fromkeys(task_ids))
    if not unique_ids:
        return
    found = set(
        (
            await db.execute(
                select(Task.id).where(
                    Task.organization_id == org.id, Task.id.in_(unique_ids)
                )
            )
        )
        .scalars()
        .all()
    )
    if any(task_id not in found for task_id in unique_ids):
        raise ValidationFailedError("Some tasks were not found in this organization")
    existing = set(
        (
            await db.execute(
                select(GoalLink.task_id).where(
                    GoalLink.goal_id == goal.id,
                    GoalLink.task_id.in_(unique_ids),
                )
            )
        )
        .scalars()
        .all()
    )
    for task_id in unique_ids:
        if task_id not in existing:
            db.add(GoalLink(goal_id=goal.id, task_id=task_id))
    await db.commit()


async def unlink_task(
    db: AsyncSession,
    actor: User,
    org: Organization,
    goal: Goal,
    task_id: uuid.UUID,
) -> None:
    link = (
        await db.execute(
            select(GoalLink).where(
                GoalLink.goal_id == goal.id, GoalLink.task_id == task_id
            )
        )
    ).scalar_one_or_none()
    if link is None:
        raise NotFoundError("Task is not linked to this goal")
    await db.delete(link)
    await db.commit()


def _task_fraction(task: Task, stats: dict[uuid.UUID, tuple[int, int]]) -> float:
    child_count, done_count = stats.get(task.id, (0, 0))
    if child_count:
        return done_count / child_count
    return 1.0 if task.status_category == TaskStatus.DONE else 0.0


async def goal_payloads(
    db: AsyncSession, org_id: uuid.UUID, goals: list[Goal]
) -> list[dict]:
    """Serializes goals with linked task refs and progress (batched queries)."""
    if not goals:
        return []
    goal_ids = [goal.id for goal in goals]
    links = list(
        (
            await db.execute(select(GoalLink).where(GoalLink.goal_id.in_(goal_ids)))
        )
        .scalars()
        .all()
    )
    task_ids = {link.task_id for link in links}
    tasks: dict[uuid.UUID, Task] = {}
    stats: dict[uuid.UUID, tuple[int, int]] = {}
    if task_ids:
        rows = (
            await db.execute(
                select(Task).where(
                    Task.organization_id == org_id, Task.id.in_(task_ids)
                )
            )
        ).scalars().all()
        tasks = {task.id: task for task in rows}
        stats = await TaskRepository(db).child_stats(org_id, list(task_ids))

    links_by_goal: dict[uuid.UUID, list[uuid.UUID]] = {}
    for link in links:
        if link.task_id in tasks:
            links_by_goal.setdefault(link.goal_id, []).append(link.task_id)

    owner_ids = {goal.owner_id for goal in goals if goal.owner_id is not None}
    owners: dict[uuid.UUID, User] = {}
    if owner_ids:
        rows = (
            await db.execute(select(User).where(User.id.in_(owner_ids)))
        ).scalars().all()
        owners = {user.id: user for user in rows}

    payloads: list[dict] = []
    for goal in goals:
        refs: list[dict] = []
        fractions: list[float] = []
        for task_id in links_by_goal.get(goal.id, []):
            task = tasks[task_id]
            fraction = _task_fraction(task, stats)
            fractions.append(fraction)
            refs.append(
                {
                    "id": task.id,
                    "key": task.key,
                    "title": task.title,
                    "type": task.type,
                    "status": task.status,
                    "status_category": task.status_category,
                    "progress_pct": round(fraction * 100),
                }
            )
        progress = round((sum(fractions) / len(fractions)) * 100) if fractions else 0
        payloads.append(
            {
                "id": goal.id,
                "organization_id": goal.organization_id,
                "name": goal.name,
                "description": goal.description,
                "status": goal.status,
                "due_date": goal.due_date,
                "owner_id": goal.owner_id,
                "owner": owners.get(goal.owner_id),
                "created_by_id": goal.created_by_id,
                "progress_pct": progress,
                "tasks": refs,
                "created_at": goal.created_at,
                "updated_at": goal.updated_at,
            }
        )
    return payloads
