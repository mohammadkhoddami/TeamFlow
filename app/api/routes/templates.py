"""Project + task template routes."""

import uuid

from fastapi import APIRouter, Query, Request, status

from app.api.deps import DB, CurrentUser, OrgMembership, ProjectAccess
from app.api.routes.tasks import _serialize_many
from app.schemas import (
    ProjectFromTemplate,
    ProjectRead,
    ProjectTemplateRead,
    SaveProjectTemplate,
    TaskFromTemplate,
    TaskRead,
    TaskTemplateCreate,
    TaskTemplateRead,
)
from app.services import templates as template_service

org_template_router = APIRouter(
    prefix="/organizations/{slug}/project-templates", tags=["templates"]
)
project_template_router = APIRouter(
    prefix="/projects/{project_id}/save-as-template", tags=["templates"]
)
project_from_template_router = APIRouter(
    prefix="/organizations/{slug}/projects/from-template", tags=["templates"]
)
task_template_router = APIRouter(
    prefix="/organizations/{slug}/task-templates", tags=["templates"]
)
task_template_apply_router = APIRouter(
    prefix="/organizations/{slug}/task-templates", tags=["templates"]
)


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@org_template_router.get("", response_model=list[ProjectTemplateRead])
async def list_project_templates(
    membership: OrgMembership, db: DB
) -> list[ProjectTemplateRead]:
    org, _m = membership
    rows = await template_service.list_project_templates(db, org.id)
    return [ProjectTemplateRead.model_validate(row) for row in rows]


@project_from_template_router.post(
    "", status_code=status.HTTP_201_CREATED, response_model=ProjectRead
)
async def create_project_from_template(
    data: ProjectFromTemplate,
    membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> ProjectRead:
    org, m = membership
    project = await template_service.create_project_from_template(
        db, current_user, org, m, data, ip=_ip(request)
    )
    return ProjectRead.model_validate(project)


@project_template_router.post(
    "", status_code=status.HTTP_201_CREATED, response_model=ProjectTemplateRead
)
async def save_project_as_template(
    data: SaveProjectTemplate,
    project_access: ProjectAccess,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> ProjectTemplateRead:
    project, org, m = project_access
    template = await template_service.save_project_as_template(
        db, current_user, org, project, m, data
    )
    return ProjectTemplateRead(
        id=str(template.id),
        name=template.name,
        description=template.description,
        is_builtin=False,
        project_id=project.id,
    )


@org_template_router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project_template(
    template_id: uuid.UUID,
    membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> None:
    org, m = membership
    template = await template_service.get_project_template_for_org(
        db, template_id, org.id
    )
    await template_service.delete_project_template(db, current_user, org, m, template)


@task_template_router.get("", response_model=list[TaskTemplateRead])
async def list_task_templates(
    membership: OrgMembership,
    db: DB,
    project_id: uuid.UUID | None = Query(default=None),
) -> list[TaskTemplateRead]:
    org, _m = membership
    rows = await template_service.list_task_templates(db, org.id, project_id)
    return [TaskTemplateRead.model_validate(row) for row in rows]


@task_template_router.post(
    "", status_code=status.HTTP_201_CREATED, response_model=TaskTemplateRead
)
async def create_task_template(
    data: TaskTemplateCreate,
    membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> TaskTemplateRead:
    org, m = membership
    template = await template_service.create_task_template(
        db, current_user, org, m, data
    )
    return TaskTemplateRead.model_validate(template)


@task_template_router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task_template(
    template_id: uuid.UUID,
    membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> None:
    org, m = membership
    template = await template_service.get_task_template_for_org(db, template_id, org.id)
    await template_service.delete_task_template(db, current_user, org, m, template)


@task_template_apply_router.post(
    "/{template_id}/apply", status_code=status.HTTP_201_CREATED, response_model=TaskRead
)
async def apply_task_template(
    template_id: uuid.UUID,
    data: TaskFromTemplate,
    membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> TaskRead:
    org, m = membership
    template = await template_service.get_task_template_for_org(db, template_id, org.id)
    task = await template_service.apply_task_template(
        db, current_user, org, m, template, data, ip=_ip(request)
    )
    return (await _serialize_many(db, [task]))[0]
