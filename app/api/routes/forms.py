"""Form/request-intake routes (M4).

Authenticated CRUD lives under the project; the public router exposes only
the slug-addressed GET (definition) and POST (submission, rate-limited).
"""

import uuid

from fastapi import APIRouter, Depends, status

from app.api.deps import DB, CurrentUser, ProjectAccess
from app.core.rate_limit import ip_rate_limiter
from app.schemas.form import (
    FormCreate,
    FormRead,
    FormSubmissionCreate,
    FormSubmissionRead,
    FormSubmitted,
    FormUpdate,
    PublicFormRead,
)
from app.services import forms as form_service

form_router = APIRouter(prefix="/projects/{project_id}/forms", tags=["forms"])
public_form_router = APIRouter(prefix="/forms", tags=["forms"])


@form_router.get("", response_model=list[FormRead])
async def list_forms(project_access: ProjectAccess, db: DB) -> list[FormRead]:
    project, _org, _m = project_access
    forms = await form_service.list_forms(db, project.id)
    return [FormRead.model_validate(form) for form in forms]


@form_router.post("", status_code=status.HTTP_201_CREATED, response_model=FormRead)
async def create_form(
    data: FormCreate,
    project_access: ProjectAccess,
    current_user: CurrentUser,
    db: DB,
) -> FormRead:
    project, org, _m = project_access
    form = await form_service.create_form(db, current_user, org, project, data)
    return FormRead.model_validate(form)


@form_router.get("/{form_id}", response_model=FormRead)
async def get_form(
    form_id: uuid.UUID, project_access: ProjectAccess, db: DB
) -> FormRead:
    project, _org, _m = project_access
    form = await form_service.get_form_for_project(db, form_id, project.id)
    return FormRead.model_validate(form)


@form_router.patch("/{form_id}", response_model=FormRead)
async def update_form(
    form_id: uuid.UUID,
    data: FormUpdate,
    project_access: ProjectAccess,
    current_user: CurrentUser,
    db: DB,
) -> FormRead:
    project, org, _m = project_access
    form = await form_service.get_form_for_project(db, form_id, project.id)
    updated = await form_service.update_form(db, current_user, org, form, data)
    return FormRead.model_validate(updated)


@form_router.delete("/{form_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_form(
    form_id: uuid.UUID,
    project_access: ProjectAccess,
    current_user: CurrentUser,
    db: DB,
) -> None:
    project, org, _m = project_access
    form = await form_service.get_form_for_project(db, form_id, project.id)
    await form_service.delete_form(db, current_user, org, form)


@form_router.get("/{form_id}/submissions", response_model=list[FormSubmissionRead])
async def list_form_submissions(
    form_id: uuid.UUID, project_access: ProjectAccess, db: DB
) -> list[FormSubmissionRead]:
    project, _org, _m = project_access
    await form_service.get_form_for_project(db, form_id, project.id)
    submissions = await form_service.list_submissions(db, form_id)
    return [FormSubmissionRead.model_validate(entry) for entry in submissions]


@public_form_router.get("/{slug}", response_model=PublicFormRead)
async def get_public_form(slug: str, db: DB) -> PublicFormRead:
    form = await form_service.get_public_form(db, slug)
    return PublicFormRead(
        name=form.name,
        description=form.description,
        fields=form.fields,
        project_name=form.project.name if form.project else "",
        slug=form.slug,
    )


@public_form_router.post(
    "/{slug}",
    status_code=status.HTTP_201_CREATED,
    response_model=FormSubmitted,
    dependencies=[Depends(ip_rate_limiter("form_submit", 30, 60))],
)
async def submit_form(
    slug: str, data: FormSubmissionCreate, db: DB
) -> FormSubmitted:
    form = await form_service.get_public_form(db, slug)
    result = await form_service.submit_form(db, form, data.data)
    return FormSubmitted.model_validate(result)
