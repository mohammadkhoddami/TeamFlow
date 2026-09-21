"""Task routes: CRUD, transitions, watchers, hierarchy, filtered listing."""

import uuid
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Query, Request, status

from app.api.deps import DB, CurrentUser, OrgMembership, ProjectAccess, TaskAccess
from app.models import Task, TaskStatus, TaskType
from app.repositories import TaskFilters, TaskRepository
from app.repositories.task import DEFAULT_PAGE_SIZE
from app.schemas import (
    Page,
    PriorityLiteral,
    StatusLiteral,
    TaskCreate,
    TaskMove,
    TaskRead,
    TaskTreeNode,
    TaskTypeLiteral,
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
    return (await _serialize_many(db, [task]))[0]


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
    type: list[TaskTypeLiteral] | None = Query(default=None),
    parent_id: uuid.UUID | None = Query(default=None, description="Direct children of this task"),
    roots_only: bool = Query(default=False, description="Only top-level tasks"),
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
        type=type,
        parent_id=parent_id,
        roots_only=roots_only,
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
        items=await _serialize_many(db, items), total=total, offset=offset, limit=limit
    )


@project_task_router.get(
    "/tree",
    response_model=list[TaskTreeNode],
    summary="Epic > story > task hierarchy for a project",
)
async def get_task_tree(project_access: ProjectAccess, db: DB) -> list[TaskTreeNode]:
    """Nested hierarchy with per-node direct child counts.

    One bounded project fetch, grouped in memory; depth is limited by the
    type rules (epic > story > task) plus a defensive guard.
    """
    project, org, _m = project_access
    tasks = await TaskRepository(db).list_for_project(org.id, project.id)
    reads = {task.id: _serialize(task) for task in tasks}
    children: dict[uuid.UUID | None, list[uuid.UUID]] = defaultdict(list)
    for task in tasks:
        children[task.parent_id].append(task.id)
    max_depth = len(TaskType.ALL)

    def build(task_id: uuid.UUID, depth: int = 0) -> TaskTreeNode:
        node = TaskTreeNode.model_validate(reads[task_id])
        if depth < max_depth:
            node.children = [build(child_id, depth + 1) for child_id in children.get(task_id, [])]
        node.child_count = len(node.children)
        node.done_child_count = sum(
            1 for child in node.children if child.status == TaskStatus.DONE
        )
        return node

    # Tasks whose parent fell outside the bounded fetch still surface as roots.
    roots = [
        task.id
        for task in tasks
        if task.parent_id is None or task.parent_id not in reads
    ]
    return [build(root_id) for root_id in roots]


@task_router.get("/{task_id}", response_model=TaskRead)
async def get_task(task_access: TaskAccess, db: DB) -> TaskRead:
    task, _org, _m = task_access
    return (await _serialize_many(db, [task]))[0]


@task_router.get("/{task_id}/children", response_model=list[TaskRead])
async def list_task_children(task_access: TaskAccess, db: DB) -> list[TaskRead]:
    """Direct children of a task (stories under an epic, tasks under a story)."""
    task, org, _m = task_access
    children = await TaskRepository(db).list_children(org.id, task.id)
    return await _serialize_many(db, children)


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
    return (await _serialize_many(db, [updated]))[0]


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
    return (await _serialize_many(db, [updated]))[0]


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


def _serialize(task: Task) -> TaskRead:
    read = TaskRead.model_validate(task)
    read.watcher_ids = [w.id for w in task.watchers]
    return read


async def _serialize_many(db: DB, tasks: list[Task]) -> list[TaskRead]:
    """Serialize tasks with batched direct-child progress counters."""
    stats: dict[uuid.UUID, tuple[int, int]] = {}
    by_org: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for task in tasks:
        by_org[task.organization_id].append(task.id)
    repo = TaskRepository(db)
    for org_id, task_ids in by_org.items():
        stats.update(await repo.child_stats(org_id, task_ids))
    reads: list[TaskRead] = []
    for task in tasks:
        read = _serialize(task)
        read.child_count, read.done_child_count = stats.get(task.id, (0, 0))
        reads.append(read)
    return reads
