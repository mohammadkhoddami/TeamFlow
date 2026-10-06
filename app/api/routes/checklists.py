"""Checklist + multi-assignee routes."""

import uuid

from fastapi import APIRouter, status

from app.api.deps import DB, CurrentUser, TaskAccess
from app.schemas import (
    ChecklistItemCreate,
    ChecklistItemRead,
    ChecklistItemUpdate,
    TaskAssigneeRead,
    TaskAssigneesUpdate,
)
from app.services import checklists as checklist_service

task_checklist_router = APIRouter(prefix="/tasks/{task_id}/checklist", tags=["checklists"])
task_assignees_router = APIRouter(prefix="/tasks/{task_id}/assignees", tags=["assignees"])


@task_checklist_router.get("", response_model=list[ChecklistItemRead])
async def list_checklist(task_access: TaskAccess, db: DB) -> list[ChecklistItemRead]:
    task, _org, _m = task_access
    rows = await checklist_service.list_checklist(db, task.id)
    return [ChecklistItemRead.model_validate(row) for row in rows]


@task_checklist_router.post(
    "", status_code=status.HTTP_201_CREATED, response_model=ChecklistItemRead
)
async def add_checklist_item(
    data: ChecklistItemCreate,
    task_access: TaskAccess,
    current_user: CurrentUser,
    db: DB,
) -> ChecklistItemRead:
    task, org, _m = task_access
    item = await checklist_service.add_checklist_item(db, current_user, org, task, data)
    return ChecklistItemRead.model_validate(item)


@task_checklist_router.patch("/{item_id}", response_model=ChecklistItemRead)
async def update_checklist_item(
    item_id: uuid.UUID,
    data: ChecklistItemUpdate,
    task_access: TaskAccess,
    current_user: CurrentUser,
    db: DB,
) -> ChecklistItemRead:
    task, org, _m = task_access
    item = await checklist_service.get_item_for_task(db, item_id, task.id)
    updated = await checklist_service.update_checklist_item(
        db, current_user, org, item, data
    )
    return ChecklistItemRead.model_validate(updated)


@task_checklist_router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_checklist_item(
    item_id: uuid.UUID,
    task_access: TaskAccess,
    current_user: CurrentUser,
    db: DB,
) -> None:
    task, org, _m = task_access
    item = await checklist_service.get_item_for_task(db, item_id, task.id)
    await checklist_service.delete_checklist_item(db, current_user, org, item)


@task_assignees_router.get("", response_model=list[TaskAssigneeRead])
async def list_assignees(task_access: TaskAccess, db: DB) -> list[TaskAssigneeRead]:
    task, _org, _m = task_access
    rows = await checklist_service.list_assignees(db, task.id)
    return [TaskAssigneeRead.model_validate(row) for row in rows]


@task_assignees_router.put("", response_model=list[TaskAssigneeRead])
async def set_assignees(
    data: TaskAssigneesUpdate,
    task_access: TaskAccess,
    current_user: CurrentUser,
    db: DB,
) -> list[TaskAssigneeRead]:
    task, org, _m = task_access
    rows = await checklist_service.set_assignees(db, current_user, org, task, data)
    return [TaskAssigneeRead.model_validate(row) for row in rows]
