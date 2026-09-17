"""Task routes: CRUD, transitions, watchers, filtered listing."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Query, Request, status

from app.api.deps import DB, CurrentUser, OrgMembership, ProjectAccess, TaskAccess
from app.repositories import TaskFilters, TaskRepository
from app.repositories.task import DEFAULT_PAGE_SIZE
from app.schemas import (
    Page,
    PriorityLiteral,
    StatusLiteral,
    TaskCreate,
    TaskMove,
    TaskRead,
    TaskUpdate,
    UserRead,
)
from app.services import tasks as task_service

task_router = APIRouter(prefix="/tasks", tags=["tasks"])
project_task_router = APIRouter(prefix="/projects/{project_id}/tasks", tags=["tasks"])
org_task_router = APIRouter(prefix="/organizations/{slug}/tasks", tags=["tasks"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@project_task_router.post("", status_code=status.HTTP_201_CREATED, response_model=TaskRead)
async def create_task(
    data: TaskCreate,
    project_access: ProjectAccess,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> TaskRead:
    project, org, _m = project_access
    task = await task_service.create_task(db, current_user, org, project, data, ip=_ip(request))
    return _serialize(task)


@org_task_router.get("", response_model=Page[TaskRead])
async def list_tasks(
    membership: OrgMembership,
    db: DB,
    current_user: CurrentUser,
    project_id: uuid.UUID | None = None,
    assignee_id: uuid.UUID | None = None,
    unassigned: bool = False,
    label_id: uuid.UUID | None = None,
    status: list[StatusLiteral] | None = Query(default=None),
    priority: list[PriorityLiteral] | None = Query(default=None),
    search: str | None = Query(default=None, max_length=100),
    due_before: datetime | None = None,
    due_after: datetime | None = None,
    overdue: bool = False,
    sort: str | None = Query(default=None, description="Sortable field, prefix '-' for desc"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=100),
) -> Page[TaskRead]:
    """Filter + sort + paginate. `sort` uses `-field` for descending
    (e.g. `-created_at`); unknown fields fall back to created_at desc."""
    org, _m = membership
    filters = TaskFilters(
        project_id=project_id,
        status=status,
        priority=priority,
        assignee_id=assignee_id,
        unassigned=unassigned,
        label_id=label_id,
        search=search,
        due_before=due_before,
        due_after=due_after,
        overdue=overdue,
    )
    items, total = await TaskRepository(db).list_for_org(
        org.id, filters, offset=offset, limit=limit, sort=sort
    )
    return Page[TaskRead](
        items=[_serialize(t) for t in items], total=total, offset=offset, limit=limit
    )


@task_router.get("/{task_id}", response_model=TaskRead)
async def get_task(task_access: TaskAccess) -> TaskRead:
    task, _org, _m = task_access
    return _serialize(task)


@task_router.patch("/{task_id}", response_model=TaskRead)
async def update_task(
    data: TaskUpdate,
    task_access: TaskAccess,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> TaskRead:
    task, org, _m = task_access
    updated = await task_service.update_task(db, current_user, org, task, data, ip=_ip(request))
    return _serialize(updated)


@task_router.post("/{task_id}/move", response_model=TaskRead, summary="Explicit status transition")
async def move_task(
    data: TaskMove,
    task_access: TaskAccess,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> TaskRead:
    task, org, _m = task_access
    updated = await task_service.move_task(db, current_user, org, task, data.status, ip=_ip(request))
    return _serialize(updated)


@task_router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_access: TaskAccess,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> None:
    task, org, m = task_access
    await task_service.delete_task(db, current_user, org, m, task, ip=_ip(request))


@task_router.post("/{task_id}/watchers/me", status_code=status.HTTP_204_NO_CONTENT)
async def watch_task(task_access: TaskAccess, current_user: CurrentUser, db: DB) -> None:
    task, org, _m = task_access
    await task_service.add_watcher(db, current_user, org, task)


@task_router.delete("/{task_id}/watchers/me", status_code=status.HTTP_204_NO_CONTENT)
async def unwatch_task(task_access: TaskAccess, current_user: CurrentUser, db: DB) -> None:
    task, org, _m = task_access
    await task_service.remove_watcher(db, current_user, org, task)


@task_router.get("/{task_id}/watchers", response_model=list[UserRead])
async def list_watchers(task_access: TaskAccess) -> list[UserRead]:
    task, _org, _m = task_access
    return [UserRead.model_validate(u) for u in task.watchers]


def _serialize(task) -> TaskRead:
    read = TaskRead.model_validate(task)
    read.watcher_ids = [w.id for w in task.watchers]
    return read
