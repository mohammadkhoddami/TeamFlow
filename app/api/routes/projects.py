"""Project routes."""

from fastapi import APIRouter, Query, Request, status

from app import services
from app.api.deps import DB, CurrentUser, OrgMembership, ProjectAccess
from app.schemas import ProjectCreate, ProjectRead, ProjectUpdate
from app.services import tasks as task_service  # noqa: F401  (import warm-up)

router = APIRouter(prefix="/organizations/{slug}/projects", tags=["projects"])
project_router = APIRouter(prefix="/projects", tags=["projects"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ProjectRead)
async def create_project(
    data: ProjectCreate,
    membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> ProjectRead:
    org, m = membership
    project = await services.projects.create_project(db, current_user, org, m, data, ip=_ip(request))
    return ProjectRead.model_validate(project)


@router.get("", response_model=list[ProjectRead])
async def list_projects(
    membership: OrgMembership,
    db: DB,
    status_filter: str | None = Query(default=None, alias="status"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[ProjectRead]:
    org, _m = membership
    projects, _total = await services.projects.list_projects(
        db, org.id, status=status_filter, offset=offset, limit=limit
    )
    return [ProjectRead.model_validate(p) for p in projects]


@project_router.get("/{project_id}", response_model=ProjectRead)
async def get_project(project_access: ProjectAccess) -> ProjectRead:
    project, _org, _m = project_access
    return ProjectRead.model_validate(project)


@project_router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(
    data: ProjectUpdate,
    project_access: ProjectAccess,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> ProjectRead:
    project, org, m = project_access
    updated = await services.projects.update_project(
        db, current_user, org, m, project, data, ip=_ip(request)
    )
    return ProjectRead.model_validate(updated)


@project_router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_access: ProjectAccess,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> None:
    project, org, m = project_access
    await services.projects.delete_project(db, current_user, org, m, project, ip=_ip(request))

