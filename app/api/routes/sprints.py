"""Sprint + backlog routes.

Backlog = tasks with no sprint, ordered by manual rank. An active sprint can
be filtered on the board via the standard task list (`?sprint_id=...`).
"""

from fastapi import APIRouter, Query, Request, status

from app.api.deps import DB, CurrentUser, ProjectAccess, SprintAccess
from app.api.routes.tasks import _serialize_many
from app.models import Sprint
from app.repositories import TaskFilters, TaskRepository
from app.schemas import (
    Page,
    SprintComplete,
    SprintCreate,
    SprintRead,
    SprintUpdate,
    TaskRead,
)
from app.services import sprints as sprint_service

project_sprint_router = APIRouter(prefix="/projects/{project_id}/sprints", tags=["sprints"])
sprint_router = APIRouter(prefix="/sprints", tags=["sprints"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _serialize(
    sprint: Sprint, aggregates: dict | None = None
) -> SprintRead:
    read = SprintRead.model_validate(sprint)
    stats = (aggregates or {}).get(sprint.id, {})
    read.task_count = int(stats.get("task_count", 0))
    read.done_task_count = int(stats.get("done_task_count", 0))
    read.total_estimate = float(stats.get("total_estimate", 0)) or None
    read.done_estimate = float(stats.get("done_estimate", 0)) or None
    return read


@project_sprint_router.post("", status_code=status.HTTP_201_CREATED, response_model=SprintRead)
async def create_sprint(
    data: SprintCreate,
    project_access: ProjectAccess,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> SprintRead:
    project, org, m = project_access
    sprint = await sprint_service.create_sprint(
        db, current_user, org, project, m, data, ip=_ip(request)
    )
    return _serialize(sprint)


@project_sprint_router.get("", response_model=list[SprintRead])
async def list_sprints(project_access: ProjectAccess, db: DB) -> list[SprintRead]:
    project, org, _m = project_access
    sprints, aggregates = await sprint_service.list_sprints(db, org.id, project.id)
    return [_serialize(sprint, aggregates) for sprint in sprints]


@project_sprint_router.get(
    "/backlog",
    response_model=Page[TaskRead],
    summary="Sprintless tasks ordered by manual backlog rank",
)
async def get_backlog(
    project_access: ProjectAccess,
    db: DB,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> Page[TaskRead]:
    project, org, _m = project_access
    filters = TaskFilters(project_id=project.id, backlog_only=True)
    items, total = await TaskRepository(db).list_for_org(
        org.id, filters, offset=offset, limit=limit, sort="backlog_rank"
    )
    return Page[TaskRead](
        items=await _serialize_many(db, items), total=total, offset=offset, limit=limit
    )


@sprint_router.get("/{sprint_id}", response_model=SprintRead)
async def get_sprint(sprint_access: SprintAccess, db: DB) -> SprintRead:
    sprint, org, _m = sprint_access
    _sprints, aggregates = await sprint_service.list_sprints(db, org.id, sprint.project_id)
    return _serialize(sprint, aggregates)


@sprint_router.patch("/{sprint_id}", response_model=SprintRead)
async def update_sprint(
    data: SprintUpdate,
    sprint_access: SprintAccess,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> SprintRead:
    sprint, org, m = sprint_access
    updated = await sprint_service.update_sprint(
        db, current_user, org, m, sprint, data, ip=_ip(request)
    )
    return _serialize(updated)


@sprint_router.post("/{sprint_id}/start", response_model=SprintRead)
async def start_sprint(
    sprint_access: SprintAccess,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> SprintRead:
    sprint, org, m = sprint_access
    started = await sprint_service.start_sprint(
        db, current_user, org, m, sprint, ip=_ip(request)
    )
    return _serialize(started)


@sprint_router.post("/{sprint_id}/complete", response_model=SprintRead)
async def complete_sprint(
    data: SprintComplete,
    sprint_access: SprintAccess,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> SprintRead:
    sprint, org, m = sprint_access
    completed, moved = await sprint_service.complete_sprint(
        db, current_user, org, m, sprint, data, ip=_ip(request)
    )
    read = _serialize(completed)
    read.carried_over_count = moved
    return read


@sprint_router.delete("/{sprint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sprint(
    sprint_access: SprintAccess,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> None:
    sprint, org, m = sprint_access
    await sprint_service.delete_sprint(db, current_user, org, m, sprint, ip=_ip(request))
