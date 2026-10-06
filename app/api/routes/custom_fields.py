"""Custom field routes (project-scoped definitions)."""

import uuid

from fastapi import APIRouter, Request, status

from app.api.deps import DB, CurrentUser, ProjectAccess
from app.schemas import CustomFieldCreate, CustomFieldRead, CustomFieldUpdate
from app.services import custom_fields as custom_field_service

router = APIRouter(prefix="/projects/{project_id}/custom-fields", tags=["custom-fields"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("", response_model=list[CustomFieldRead])
async def list_fields(project_access: ProjectAccess, db: DB) -> list[CustomFieldRead]:
    project, _org, _m = project_access
    fields = await custom_field_service.list_fields(db, project.id)
    return [CustomFieldRead.model_validate(field) for field in fields]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=CustomFieldRead)
async def create_field(
    data: CustomFieldCreate,
    project_access: ProjectAccess,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> CustomFieldRead:
    project, org, m = project_access
    field = await custom_field_service.create_field(
        db, current_user, org, project, m, data
    )
    return CustomFieldRead.model_validate(field)


@router.patch("/{field_id}", response_model=CustomFieldRead)
async def update_field(
    field_id: uuid.UUID,
    data: CustomFieldUpdate,
    project_access: ProjectAccess,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> CustomFieldRead:
    project, org, m = project_access
    field = await custom_field_service.get_field_for_project(db, field_id, project.id)
    updated = await custom_field_service.update_field(
        db, current_user, org, m, field, data
    )
    return CustomFieldRead.model_validate(updated)


@router.delete("/{field_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_field(
    field_id: uuid.UUID,
    project_access: ProjectAccess,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> None:
    project, org, m = project_access
    field = await custom_field_service.get_field_for_project(db, field_id, project.id)
    await custom_field_service.delete_field(db, current_user, org, m, field)
