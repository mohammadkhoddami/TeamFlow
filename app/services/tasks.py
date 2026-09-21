"""Task service: CRUD, status transitions, assignment, labels, watchers.

Business rules:
  - status transitions follow a whitelist (with reopening); same->same is a
    no-op, unknown paths are 422
  - moving to DONE stamps completed_at; leaving DONE clears it
  - hierarchy: epic > story > task; a parent must be in the same project and
    at a strictly higher level, so cycles are structurally impossible
  - assignee must be an active member of the task's org
  - creator + assignee auto-watch; watchers get notified on comments/status
  - members may edit tasks; only managers+ (or the creator) may delete

Async-SQLAlchemy note: M2M collections are written through the link tables
(`TaskLabelLink`, `TaskWatcherLink`) and read back with an explicit
`select(Task)` re-fetch — implicit lazy loads (`task.labels.append(...)`)
raise MissingGreenlet inside an async session, so we never trigger them.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, insert, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import (
    NotFoundError,
    PermissionDeniedError,
    ValidationFailedError,
)
from app.models import (
    AuditAction,
    Membership,
    MembershipRole,
    Organization,
    Project,
    Task,
    TaskLabelLink,
    TaskStatus,
    TaskType,
    TaskWatcherLink,
    User,
)
from app.repositories import LabelRepository, MembershipRepository, TaskRepository
from app.schemas import TaskCreate, TaskUpdate
from app.services import audit, cache, events

# Allowed transitions; reopening a done task returns to in_progress.
STATUS_TRANSITIONS: dict[str, set[str]] = {
    TaskStatus.TODO: {TaskStatus.IN_PROGRESS},
    TaskStatus.IN_PROGRESS: {TaskStatus.TODO, TaskStatus.IN_REVIEW},
    TaskStatus.IN_REVIEW: {TaskStatus.IN_PROGRESS, TaskStatus.DONE},
    TaskStatus.DONE: {TaskStatus.IN_PROGRESS},
}


def _can_delete(membership: Membership, task: Task, actor: User) -> bool:
    if membership.role != MembershipRole.MEMBER:
        return True
    return task.created_by_id == actor.id


def _type_level(task_type: str) -> int:
    return TaskType.LEVELS.get(task_type, TaskType.LEVELS[TaskType.TASK])


async def _assert_parent_valid(
    db: AsyncSession,
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    parent_id: uuid.UUID,
    child_type: str,
    child_id: uuid.UUID | None = None,
) -> None:
    """Validates the epic > story > task rule for a proposed parent link.

    A parent must live in the same project and at a strictly higher level
    than its child; the link must also not close a cycle.
    """
    repo = TaskRepository(db)
    parent = await repo.get_in_org(parent_id, org_id)
    if not parent:
        raise ValidationFailedError("Parent task not found in this organization")
    if parent.project_id != project_id:
        raise ValidationFailedError("Parent task must belong to the same project")
    if child_id is not None and parent.id == child_id:
        raise ValidationFailedError("A task cannot be its own parent")
    if _type_level(parent.type) >= _type_level(child_type):
        raise ValidationFailedError(
            f"'{parent.type}' is not a valid parent for '{child_type}': "
            "parents must be a higher level (epic > story > task)"
        )
    if child_id is None:
        return
    # Walk up from the proposed parent; meeting the child means a cycle.
    seen = {parent.id}
    current_id = parent.parent_id
    while current_id is not None and len(seen) <= len(TaskType.ALL) + 1:
        if current_id == child_id:
            raise ValidationFailedError("Cannot nest a task under its own descendant")
        if current_id in seen:
            raise ValidationFailedError("The parent chain contains a cycle")
        seen.add(current_id)
        current_id = await repo.get_parent_id(current_id)


async def _assert_type_change_valid(
    db: AsyncSession, org_id: uuid.UUID, task: Task, new_type: str
) -> None:
    """A type change must preserve the level invariant on both ends."""
    child_types = await TaskRepository(db).children_types(task.id)
    if any(_type_level(child_type) <= _type_level(new_type) for child_type in child_types):
        raise ValidationFailedError(
            f"Cannot change type to '{new_type}': this task already has "
            "children at the same or a higher level"
        )
    if task.parent_id is not None:
        await _assert_parent_valid(
            db, org_id, task.project_id, task.parent_id, new_type, task.id
        )


async def _assert_assignee_in_org(
    db: AsyncSession, org_id: uuid.UUID, assignee_id: uuid.UUID
) -> None:
    membership = await MembershipRepository(db).get_for_user(assignee_id, org_id)
    if not membership or not membership.is_active:
        raise ValidationFailedError(
            "Assignee must be an active member of this organization"
        )


async def _resolve_label_ids(
    db: AsyncSession, org_id: uuid.UUID, label_ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    """Validates every label belongs to this org (tenant safety + 404 policy)."""
    valid: list[uuid.UUID] = []
    for label_id in label_ids:
        label = await LabelRepository(db).get_in_org(label_id, org_id)
        if not label:
            raise ValidationFailedError(f"Label {label_id} not found in this organization")
        valid.append(label.id)
    return valid


async def _set_task_labels(
    db: AsyncSession, task_id: uuid.UUID, label_ids: list[uuid.UUID]
) -> None:
    await db.execute(delete(TaskLabelLink).where(TaskLabelLink.task_id == task_id))
    if label_ids:
        await db.execute(
            insert(TaskLabelLink),
            [{"task_id": task_id, "label_id": lid} for lid in label_ids],
        )


async def _add_watchers(
    db: AsyncSession, task_id: uuid.UUID, user_ids: set[uuid.UUID]
) -> None:
    if not user_ids:
        return
    existing = set(
        (
            await db.execute(
                select(TaskWatcherLink.user_id).where(
                    TaskWatcherLink.task_id == task_id,
                    TaskWatcherLink.user_id.in_(user_ids),
                )
            )
        ).scalars()
    )
    missing = user_ids - existing
    if missing:
        await db.execute(
            insert(TaskWatcherLink),
            [{"task_id": task_id, "user_id": uid} for uid in missing],
        )


async def _remove_watcher(db: AsyncSession, task_id: uuid.UUID, user_id: uuid.UUID) -> None:
    await db.execute(
        delete(TaskWatcherLink).where(
            TaskWatcherLink.task_id == task_id,
            TaskWatcherLink.user_id == user_id,
        )
    )


async def get_task_for_org(
    db: AsyncSession, task_id: uuid.UUID, organization_id: uuid.UUID
) -> Task:
    task = await TaskRepository(db).get_in_org(task_id, organization_id)
    if not task:
        # 404 hides cross-org task IDs (IDOR containment).
        raise NotFoundError("Task not found")
    return task


def task_event_payload(task: Task) -> dict:
    return {
        "id": str(task.id),
        "project_id": str(task.project_id),
        "title": task.title,
        "status": task.status,
        "priority": task.priority,
        "type": task.type,
        "parent_id": str(task.parent_id) if task.parent_id else None,
        "assignee_id": str(task.assignee_id) if task.assignee_id else None,
        "due_date": task.due_date.isoformat() if task.due_date else None,
    }


async def refetch_task(db: AsyncSession, task_id: uuid.UUID) -> Task:
    """Re-select after commit so labels/watchers/assignee load eagerly and
    safely inside the async session (no implicit lazy loads).

    `populate_existing=True` matters when the Task is already in the identity
    map (e.g. loaded by the access dependency): without it, eager loaders
    leave already-populated collections untouched and responses would be
    stale (empty labels right after assignment)."""
    statement = (
        select(Task)
        .where(Task.id == task_id)
        .execution_options(populate_existing=True)
    )
    return (await db.execute(statement)).scalar_one()


async def create_task(
    db: AsyncSession,
    actor: User,
    org: Organization,
    project: Project,
    data: TaskCreate,
    ip: str | None = None,
) -> Task:
    if data.parent_id is not None:
        await _assert_parent_valid(
            db, org.id, project.id, data.parent_id, data.type
        )

    task = Task(
        organization_id=org.id,
        project_id=project.id,
        title=data.title,
        description=data.description,
        priority=data.priority,
        type=data.type,
        parent_id=data.parent_id,
        due_date=data.due_date,
        created_by_id=actor.id,
    )
    if data.assignee_id is not None:
        await _assert_assignee_in_org(db, org.id, data.assignee_id)
        task.assignee_id = data.assignee_id

    task = await TaskRepository(db).add(task)
    if data.label_ids:
        valid_ids = await _resolve_label_ids(db, org.id, data.label_ids)
        await _set_task_labels(db, task.id, valid_ids)

    # Creator + assignee auto-watch.
    watcher_ids = {actor.id} | ({data.assignee_id} if data.assignee_id else set())
    await _add_watchers(db, task.id, watcher_ids)

    await audit.log(
        db, AuditAction.TASK_CREATED, actor_id=actor.id,
        organization_id=org.id, target_type="task", target_id=task.id, ip=ip,
        meta={"title": task.title, "project_id": str(project.id)},
    )
    if task.assignee_id and task.assignee_id != actor.id:
        await audit.log(
            db, AuditAction.TASK_ASSIGNED, actor_id=actor.id,
            organization_id=org.id, target_type="task", target_id=task.id, ip=ip,
            meta={"assignee_id": str(task.assignee_id)},
        )
        await events.notify(
            db,
            user_id=task.assignee_id,
            type="task_assigned",
            title=f"You were assigned: {task.title}",
            organization_id=org.id,
            data={"task_id": str(task.id), "project_id": str(project.id)},
        )
    await db.commit()

    task = await refetch_task(db, task.id)
    payload = task_event_payload(task)
    await events.publish_project_event(project.id, "task.created", payload)
    await events.dispatch_webhooks(
        db, organization_id=org.id, event="task.created", data=payload
    )
    await cache.invalidate_dashboard(org.id)
    return task


async def update_task(
    db: AsyncSession,
    actor: User,
    org: Organization,
    task: Task,
    data: TaskUpdate,
    ip: str | None = None,
) -> Task:
    """Permission note: every org member may update tasks (collaboration-first);
    deletion and project management are the gated actions."""
    changed = data.model_fields_set
    old_status = task.status

    if "type" in changed and data.type is not None and data.type != task.type:
        await _assert_type_change_valid(db, org.id, task, data.type)
        task.type = data.type

    if "parent_id" in changed and data.parent_id != task.parent_id:
        if data.parent_id is None:
            task.parent_id = None
        else:
            await _assert_parent_valid(
                db, org.id, task.project_id, data.parent_id, task.type, task.id
            )
            task.parent_id = data.parent_id

    if "assignee_id" in changed and data.assignee_id != task.assignee_id:
        if data.assignee_id is not None:
            await _assert_assignee_in_org(db, org.id, data.assignee_id)
        task.assignee_id = data.assignee_id

    if "status" in changed and data.status and data.status != task.status:
        allowed = STATUS_TRANSITIONS.get(task.status, set())
        if data.status not in allowed:
            raise ValidationFailedError(
                f"Cannot move task from '{task.status}' to '{data.status}'"
            )
        task.status = data.status
        task.completed_at = datetime.now(UTC) if data.status == TaskStatus.DONE else None

    if "title" in changed and data.title is not None:
        task.title = data.title
    if "description" in changed:
        task.description = data.description
    if "priority" in changed and data.priority is not None:
        task.priority = data.priority
    if "due_date" in changed:
        task.due_date = data.due_date

    if "label_ids" in changed and data.label_ids is not None:
        valid_ids = await _resolve_label_ids(db, org.id, data.label_ids)
        await _set_task_labels(db, task.id, valid_ids)

    if task.assignee_id:
        await _add_watchers(db, task.id, {task.assignee_id})

    task = await TaskRepository(db).update(task)
    await audit.log(
        db, AuditAction.TASK_UPDATED, actor_id=actor.id,
        organization_id=org.id, target_type="task", target_id=task.id, ip=ip,
        meta={"fields": sorted(changed)},
    )
    if "assignee_id" in changed and task.assignee_id:
        await audit.log(
            db, AuditAction.TASK_ASSIGNED, actor_id=actor.id,
            organization_id=org.id, target_type="task", target_id=task.id, ip=ip,
            meta={"assignee_id": str(task.assignee_id)},
        )
        if task.assignee_id != actor.id:
            await events.notify(
                db,
                user_id=task.assignee_id,
                type="task_assigned",
                title=f"You were assigned: {task.title}",
                organization_id=org.id,
                data={"task_id": str(task.id), "project_id": str(task.project_id)},
            )
    await db.commit()

    task = await refetch_task(db, task.id)
    payload = task_event_payload(task)
    event_type = (
        "task.completed"
        if task.status == TaskStatus.DONE and old_status != TaskStatus.DONE
        else "task.updated"
    )
    await events.publish_project_event(task.project_id, "task.updated", payload)
    await events.dispatch_webhooks(
        db, organization_id=org.id, event=event_type, data=payload
    )
    await cache.invalidate_dashboard(org.id)
    return task


async def move_task(
    db: AsyncSession,
    actor: User,
    org: Organization,
    task: Task,
    new_status: str,
    ip: str | None = None,
) -> Task:
    if new_status == task.status:
        return task
    allowed = STATUS_TRANSITIONS.get(task.status, set())
    if new_status not in allowed:
        raise ValidationFailedError(
            f"Cannot move task from '{task.status}' to '{new_status}'"
        )
    return await update_task(db, actor, org, task, TaskUpdate(status=new_status), ip)


async def delete_task(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    task: Task,
    ip: str | None = None,
) -> None:
    if not _can_delete(membership, task, actor):
        raise PermissionDeniedError(
            "Only managers and above (or the creator) can delete tasks"
        )
    await audit.log(
        db, AuditAction.TASK_DELETED, actor_id=actor.id,
        organization_id=org.id, target_type="task", target_id=task.id, ip=ip,
        meta={"title": task.title},
    )
    project_id = task.project_id
    task_id_str = str(task.id)
    await TaskRepository(db).delete(task)
    await db.commit()
    await events.publish_project_event(project_id, "task.deleted", {"id": task_id_str})
    await cache.invalidate_dashboard(org.id)


async def add_watcher(db: AsyncSession, actor: User, org: Organization, task: Task) -> Task:
    await _add_watchers(db, task.id, {actor.id})
    await db.commit()
    return await refetch_task(db, task.id)


async def remove_watcher(db: AsyncSession, actor: User, org: Organization, task: Task) -> Task:
    await _remove_watcher(db, task.id, actor.id)
    await db.commit()
    return await refetch_task(db, task.id)


async def list_watchers(task: Task) -> list[uuid.UUID]:
    return [w.id for w in task.watchers]
