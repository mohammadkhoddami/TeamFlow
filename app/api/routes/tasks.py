"""Task routes: CRUD, transitions, watchers, hierarchy, filtered listing,
TeamQL queries, bulk operations and archive/restore."""

import uuid
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Query, Request, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import DB, CurrentUser, OrgMembership, ProjectAccess, TaskAccess
from app.models import Task, TaskStatus, TaskType
from app.repositories import (
    ChecklistRepository,
    LabelRepository,
    MembershipRepository,
    SprintRepository,
    TaskAssigneeRepository,
    TaskFilters,
    TaskRepository,
    WorklogRepository,
)
from app.repositories.task import DEFAULT_PAGE_SIZE
from app.schemas import (
    BulkTaskRequest,
    BulkTaskResult,
    CustomFieldValueRead,
    Page,
    PriorityLiteral,
    StatusLiteral,
    TaskAssigneeRead,
    TaskCreate,
    TaskMove,
    TaskRead,
    TaskTreeNode,
    TaskTypeLiteral,
    TaskUpdate,
    UserRead,
)
from app.services import bulk as bulk_service
from app.services import tasks as task_service
from app.services.teamql import parse_teamql

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
    sprint_id: uuid.UUID | None = Query(default=None, description="Only this sprint"),
    backlog_only: bool = Query(default=False, description="Only sprintless tasks"),
    include_archived: bool = Query(default=False),
    archived_only: bool = Query(default=False, description="Only archived tasks"),
    blocked: bool | None = Query(
        default=None, description="true = blocked by an open task, false = not blocked"
    ),
    category: list[StatusLiteral] | None = Query(
        default=None, description="Workflow categories (todo/in_progress/in_review/done)"
    ),
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
        sprint_id=sprint_id,
        backlog_only=backlog_only,
        include_archived=include_archived,
        archived_only=archived_only,
        blocked=blocked,
        categories=category,
    )
    items, total = await TaskRepository(db).list_for_org(
        org.id, filters, offset=offset, limit=limit, sort=sort
    )
    return Page[TaskRead](
        items=await _serialize_many(db, items), total=total, offset=offset, limit=limit
    )


@org_task_router.get(
    "/query",
    response_model=Page[TaskRead],
    summary="Run a TeamQL query (saved filters use the same language)",
)
async def query_tasks(
    membership: OrgMembership,
    db: DB,
    current_user: CurrentUser,
    q: str = Query(min_length=1, max_length=2000),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=100),
) -> Page[TaskRead]:
    org, _m = membership
    filters, sort = await build_teamql_filters(db, org.id, q, current_user.id)
    items, total = await TaskRepository(db).list_for_org(
        org.id, filters, offset=offset, limit=limit, sort=sort
    )
    return Page[TaskRead](
        items=await _serialize_many(db, items), total=total, offset=offset, limit=limit
    )


async def build_teamql_filters(
    db: AsyncSession, org_id: uuid.UUID, query: str, me_id: uuid.UUID
) -> tuple[TaskFilters, str | None]:
    """Resolves TeamQL lookups (members/labels/sprints) then parses."""
    members = await MembershipRepository(db).list_for_org(org_id, limit=1000)
    members_by_email = {
        (m.user.email.lower() if m.user else ""): m.user_id
        for m in members
        if m.user is not None
    }
    labels = await LabelRepository(db).list_for_org(org_id, limit=500)
    labels_by_name = {label.name.lower(): label.id for label in labels}
    sprints: dict[str, uuid.UUID] = {}
    for sprint, project_name in await SprintRepository(db).list_for_org(org_id):
        sprints[f"{project_name}:{sprint.name}".lower()] = sprint.id
        sprints.setdefault(sprint.name.lower(), sprint.id)
    from app.repositories import CustomFieldRepository, ProjectRepository

    custom_fields_by_key: dict[str, uuid.UUID] = {}
    projects, _total = await ProjectRepository(db).list_for_org(org_id, limit=200)
    for project in projects:
        for field in await CustomFieldRepository(db).list_for_project(project.id):
            custom_fields_by_key.setdefault(field.key.lower(), field.id)
    return parse_teamql(
        query,
        me_id=me_id,
        members_by_email=members_by_email,
        labels_by_name=labels_by_name,
        sprints_by_name=sprints,
        custom_fields_by_key=custom_fields_by_key,
    )


@org_task_router.post(
    "/bulk",
    response_model=BulkTaskResult,
    summary="Multi-select action: update, move, clone, delete, archive, move project",
)
async def bulk_tasks(
    data: BulkTaskRequest,
    membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> BulkTaskResult:
    org, m = membership
    return await bulk_service.bulk_operate(
        db, current_user, org, m, data, ip=_ip(request)
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


@task_router.post("/{task_id}/archive", response_model=TaskRead)
async def archive_task(
    task_access: TaskAccess,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> TaskRead:
    task, org, _m = task_access
    archived = await task_service.archive_task(db, current_user, org, task, ip=_ip(request))
    return (await _serialize_many(db, [archived]))[0]


@task_router.post("/{task_id}/restore", response_model=TaskRead)
async def restore_task(
    task_access: TaskAccess,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> TaskRead:
    task, org, _m = task_access
    restored = await task_service.restore_task(db, current_user, org, task, ip=_ip(request))
    return (await _serialize_many(db, [restored]))[0]


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
    read.sprint_name = task.sprint.name if task.sprint else None
    return read


async def _serialize_many(db: DB, tasks: list[Task]) -> list[TaskRead]:
    """Serialize tasks with batched M2 projections (child progress, custom
    field values, assignees, checklist totals, logged time, dependency flags)."""
    from app.services import custom_fields as custom_field_service
    from app.services import task_links as link_service

    if not tasks:
        return []
    stats: dict[uuid.UUID, tuple[int, int]] = {}
    by_org: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for task in tasks:
        by_org[task.organization_id].append(task.id)
    repo = TaskRepository(db)
    for org_id, task_ids in by_org.items():
        stats.update(await repo.child_stats(org_id, task_ids))

    task_ids = [task.id for task in tasks]
    custom_values: dict[uuid.UUID, list[dict]] = {}
    by_project: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for task in tasks:
        by_project[task.project_id].append(task.id)
    for project_id, ids in by_project.items():
        custom_values.update(
            await custom_field_service.values_for_tasks(db, ids, project_id)
        )
    assignee_rows = await TaskAssigneeRepository(db).list_for_tasks(task_ids)
    assignees_by_task: dict[uuid.UUID, list[dict]] = defaultdict(list)
    for row in assignee_rows:
        user = row.user
        assignees_by_task[row.task_id].append(
            {
                "user_id": row.user_id,
                "name": (user.full_name or user.email) if user else "(removed)",
                "email": user.email if user else "",
                "role": row.role,
            }
        )
    checklist_stats = await ChecklistRepository(db).stats_for_tasks(task_ids)
    logged_minutes = await WorklogRepository(db).total_minutes_for_tasks(task_ids)
    links = await link_service.link_stats(db, task_ids)

    reads: list[TaskRead] = []
    for task in tasks:
        read = _serialize(task)
        read.child_count, read.done_child_count = stats.get(task.id, (0, 0))
        read.custom_fields = [
            CustomFieldValueRead.model_validate(entry)
            for entry in custom_values.get(task.id, [])
        ]
        read.assignees = [
            TaskAssigneeRead.model_validate(entry)
            for entry in assignees_by_task.get(task.id, [])
        ]
        total, done = checklist_stats.get(task.id, (0, 0))
        read.checklist_total = total
        read.checklist_done = done
        read.logged_minutes = logged_minutes.get(task.id, 0)
        is_blocked, blocks_count, blocked_by_count = links.get(task.id, (False, 0, 0))
        read.is_blocked = is_blocked
        read.blocks_count = blocks_count
        read.blocked_by_count = blocked_by_count
        reads.append(read)
    return reads
