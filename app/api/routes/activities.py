"""Activity feed routes (M3 #21)."""

from fastapi import APIRouter, Query

from app.api.deps import DB, OrgMembership, ProjectAccess, TaskAccess
from app.schemas import ActivityRead
from app.services import activities as activity_service

task_activity_router = APIRouter(prefix="/tasks/{task_id}/activity", tags=["activity"])
project_activity_router = APIRouter(
    prefix="/projects/{project_id}/activity", tags=["activity"]
)
org_activity_router = APIRouter(
    prefix="/organizations/{slug}/activity", tags=["activity"]
)


@task_activity_router.get("", response_model=list[ActivityRead])
async def task_activity(
    task_access: TaskAccess,
    db: DB,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ActivityRead]:
    task, _org, _m = task_access
    items, _total = await activity_service.list_for_task(
        db, task.id, offset=offset, limit=limit
    )
    return [ActivityRead.model_validate(item) for item in items]


@project_activity_router.get("", response_model=list[ActivityRead])
async def project_activity(
    project_access: ProjectAccess,
    db: DB,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ActivityRead]:
    project, _org, _m = project_access
    items, _total = await activity_service.list_for_project(
        db, project.id, offset=offset, limit=limit
    )
    return [ActivityRead.model_validate(item) for item in items]


@org_activity_router.get("", response_model=list[ActivityRead])
async def org_activity(
    org_membership: OrgMembership,
    db: DB,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ActivityRead]:
    org, _m = org_membership
    items, _total = await activity_service.list_for_org(
        db, org.id, offset=offset, limit=limit
    )
    return [ActivityRead.model_validate(item) for item in items]
