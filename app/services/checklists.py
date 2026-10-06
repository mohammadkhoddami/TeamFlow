"""Checklist items + role-bearing task assignees."""

import uuid

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import NotFoundError, ValidationFailedError
from app.models import (
    AssigneeRole,
    ChecklistItem,
    Organization,
    Task,
    TaskAssignee,
    User,
)
from app.repositories import ChecklistRepository, TaskAssigneeRepository
from app.schemas import (
    ChecklistItemCreate,
    ChecklistItemUpdate,
    TaskAssigneesUpdate,
)
from app.services import events, preferences


async def list_checklist(db: AsyncSession, task_id: uuid.UUID) -> list[ChecklistItem]:
    return await ChecklistRepository(db).list_for_task(task_id)


async def add_checklist_item(
    db: AsyncSession,
    actor: User,
    org: Organization,
    task: Task,
    data: ChecklistItemCreate,
) -> ChecklistItem:
    existing = await ChecklistRepository(db).list_for_task(task.id)
    item = await ChecklistRepository(db).add(
        ChecklistItem(
            organization_id=org.id,
            task_id=task.id,
            text=data.text,
            position=len(existing),
            created_by_id=actor.id,
        )
    )
    await db.commit()
    return item


async def get_item_for_task(
    db: AsyncSession, item_id: uuid.UUID, task_id: uuid.UUID
) -> ChecklistItem:
    item = await ChecklistRepository(db).get(item_id)
    if item is None or item.task_id != task_id:
        raise NotFoundError("Checklist item not found")
    return item


async def update_checklist_item(
    db: AsyncSession,
    actor: User,
    org: Organization,
    item: ChecklistItem,
    data: ChecklistItemUpdate,
) -> ChecklistItem:
    changed = data.model_fields_set
    if "text" in changed and data.text is not None:
        item.text = data.text
    if "is_done" in changed and data.is_done is not None:
        item.is_done = data.is_done
    if "position" in changed and data.position is not None:
        item.position = data.position
    item = await ChecklistRepository(db).update(item)
    await db.commit()
    return item


async def delete_checklist_item(
    db: AsyncSession, actor: User, org: Organization, item: ChecklistItem
) -> None:
    await ChecklistRepository(db).delete(item)
    await db.commit()


async def list_assignees(db: AsyncSession, task_id: uuid.UUID) -> list[dict]:
    rows = await TaskAssigneeRepository(db).list_for_task(task_id)
    return [
        {
            "user_id": row.user_id,
            "name": (row.user.full_name or row.user.email) if row.user else "(removed)",
            "email": row.user.email if row.user else "",
            "role": row.role,
        }
        for row in rows
    ]


async def set_assignees(
    db: AsyncSession,
    actor: User,
    org: Organization,
    task: Task,
    data: TaskAssigneesUpdate,
) -> list[dict]:
    from app.repositories import MembershipRepository

    seen: set[uuid.UUID] = set()
    for entry in data.assignees:
        if entry.user_id in seen:
            raise ValidationFailedError("Duplicate assignee")
        seen.add(entry.user_id)
        membership = await MembershipRepository(db).get_for_user(entry.user_id, org.id)
        if membership is None or not membership.is_active:
            raise ValidationFailedError("Assignees must be active organization members")

    previous = {row.user_id for row in await TaskAssigneeRepository(db).list_for_task(task.id)}
    await TaskAssigneeRepository(db).delete_for_task(task.id)
    primary: uuid.UUID | None = None
    for entry in data.assignees:
        role = entry.role if entry.role in AssigneeRole.ALL else AssigneeRole.ASSIGNEE
        db.add(
            TaskAssignee(
                organization_id=org.id,
                task_id=task.id,
                user_id=entry.user_id,
                role=role,
            )
        )
        if primary is None and role == AssigneeRole.ASSIGNEE:
            primary = entry.user_id
    if primary is None and data.assignees:
        primary = data.assignees[0].user_id
    task.assignee_id = primary
    await db.flush()

    new_assignees = seen - previous
    for user_id in new_assignees:
        if user_id == actor.id:
            continue
        await events.notify(
            db,
            user_id=user_id,
            type="task_assigned",
            title=f"You were assigned: {task.title}",
            organization_id=org.id,
            data={"task_id": str(task.id), "project_id": str(task.project_id)},
        )
    await db.commit()

    from app.repositories import ProjectRepository

    project = await ProjectRepository(db).get(task.project_id)
    if project is not None:
        for user_id in new_assignees:
            if user_id == actor.id:
                continue
            await preferences.task_email(
                db,
                user_id=user_id,
                notification_type="task_assigned",
                kind="task_assigned",
                task=task,
                project=project,
                org_slug=org.slug,
            )
    return await list_assignees(db, task.id)
