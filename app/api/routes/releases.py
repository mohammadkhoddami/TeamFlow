"""Release + roadmap routes (M3 #16)."""

import uuid

from fastapi import APIRouter, Request, status

from app.api.deps import DB, CurrentUser, ProjectAccess
from app.schemas import ReleaseCreate, ReleaseRead, ReleaseUpdate, RoadmapResponse
from app.services import releases as release_service

project_release_router = APIRouter(
    prefix="/projects/{project_id}/releases", tags=["releases"]
)
project_roadmap_router = APIRouter(
    prefix="/projects/{project_id}/roadmap", tags=["releases"]
)


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _read(release, total: int = 0, done: int = 0) -> ReleaseRead:
    payload = ReleaseRead.model_validate(release)
    payload.task_count = total
    payload.done_task_count = done
    return payload


async def _counts_for(db, project, release_id: uuid.UUID) -> tuple[int, int]:
    entries = await release_service.list_releases(db, project)
    for release, total, done in entries:
        if release.id == release_id:
            return total, done
    return 0, 0


@project_release_router.get("", response_model=list[ReleaseRead])
async def list_releases(project_access: ProjectAccess, db: DB) -> list[ReleaseRead]:
    project, _org, _m = project_access
    entries = await release_service.list_releases(db, project)
    return [_read(release, total, done) for release, total, done in entries]


@project_release_router.post(
    "", status_code=status.HTTP_201_CREATED, response_model=ReleaseRead
)
async def create_release(
    data: ReleaseCreate,
    project_access: ProjectAccess,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> ReleaseRead:
    project, org, _m = project_access
    release = await release_service.create_release(
        db, current_user, org, project, data, ip=_ip(request)
    )
    return _read(release)


@project_release_router.get("/{release_id}", response_model=ReleaseRead)
async def get_release(
    release_id: uuid.UUID, project_access: ProjectAccess, db: DB
) -> ReleaseRead:
    project, org, _m = project_access
    release = await release_service.get_release_for_org(
        db, release_id, org.id, project.id
    )
    total, done = await _counts_for(db, project, release.id)
    return _read(release, total, done)


@project_release_router.patch("/{release_id}", response_model=ReleaseRead)
async def update_release(
    release_id: uuid.UUID,
    data: ReleaseUpdate,
    project_access: ProjectAccess,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> ReleaseRead:
    project, org, _m = project_access
    release = await release_service.get_release_for_org(
        db, release_id, org.id, project.id
    )
    updated = await release_service.update_release(
        db, current_user, org, release, data, ip=_ip(request)
    )
    total, done = await _counts_for(db, project, updated.id)
    return _read(updated, total, done)


@project_release_router.delete(
    "/{release_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_release(
    release_id: uuid.UUID,
    project_access: ProjectAccess,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> None:
    project, org, _m = project_access
    release = await release_service.get_release_for_org(
        db, release_id, org.id, project.id
    )
    await release_service.delete_release(db, current_user, org, release, ip=_ip(request))


@project_roadmap_router.get("", response_model=RoadmapResponse)
async def roadmap(project_access: ProjectAccess, db: DB) -> RoadmapResponse:
    project, org, _m = project_access
    return RoadmapResponse.model_validate(
        await release_service.roadmap(db, org, project)
    )
