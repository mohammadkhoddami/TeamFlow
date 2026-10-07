"""Form/request-intake service (M4).

Authed CRUD is project-scoped; submissions are validated (required fields),
turned into a task through the regular task service (so automations, events
and activity recording all apply), and recorded as `FormSubmission` rows.
"""

import secrets
import uuid

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import NotFoundError, ValidationFailedError
from app.models import (
    Form,
    FormSubmission,
    Organization,
    Project,
    TaskPriority,
    TaskType,
    User,
)
from app.schemas import TaskCreate
from app.schemas.form import FormCreate, FormUpdate
from app.services import tasks as task_service

PRIORITY_VALUES = {
    TaskPriority.LOW,
    TaskPriority.MEDIUM,
    TaskPriority.HIGH,
    TaskPriority.URGENT,
}
TITLE_MAX = 200
SUBMISSIONS_LIMIT = 100


def _slugify(name: str) -> str:
    base = "".join(
        char.lower() if char.isalnum() else "-" for char in name.strip()
    ).strip("-")
    while "--" in base:
        base = base.replace("--", "-")
    return base[:48] or "form"


async def _unique_slug(db: AsyncSession, name: str) -> str:
    base = _slugify(name)
    while True:
        slug = f"{base}-{secrets.token_hex(3)}"
        exists = (
            await db.execute(select(Form.id).where(Form.slug == slug))
        ).first()
        if not exists:
            return slug


async def create_form(
    db: AsyncSession,
    actor: User,
    org: Organization,
    project: Project,
    data: FormCreate,
) -> Form:
    form = Form(
        organization_id=org.id,
        project_id=project.id,
        name=data.name,
        description=data.description,
        slug=await _unique_slug(db, data.name),
        fields=[field.model_dump() for field in data.fields],
        is_public=data.is_public,
        created_by_id=actor.id,
    )
    db.add(form)
    await db.flush()
    await db.commit()
    return form


async def list_forms(db: AsyncSession, project_id: uuid.UUID) -> list[Form]:
    statement = (
        select(Form)
        .where(Form.project_id == project_id)
        .order_by(Form.created_at.desc())
    )
    return list((await db.execute(statement)).scalars().all())


async def get_form_for_project(
    db: AsyncSession, form_id: uuid.UUID, project_id: uuid.UUID
) -> Form:
    statement = select(Form).where(Form.id == form_id, Form.project_id == project_id)
    form = (await db.execute(statement)).scalar_one_or_none()
    if form is None:
        raise NotFoundError("Form not found")
    return form


async def update_form(
    db: AsyncSession,
    actor: User,
    org: Organization,
    form: Form,
    data: FormUpdate,
) -> Form:
    changed = data.model_fields_set
    if "name" in changed and data.name is not None:
        form.name = data.name
    if "description" in changed:
        form.description = data.description
    if "fields" in changed and data.fields is not None:
        form.fields = [field.model_dump() for field in data.fields]
    if "is_public" in changed and data.is_public is not None:
        form.is_public = data.is_public
    db.add(form)
    await db.flush()
    await db.commit()
    return form


async def delete_form(
    db: AsyncSession, actor: User, org: Organization, form: Form
) -> None:
    await db.delete(form)
    await db.commit()


async def list_submissions(
    db: AsyncSession, form_id: uuid.UUID
) -> list[FormSubmission]:
    statement = (
        select(FormSubmission)
        .where(FormSubmission.form_id == form_id)
        .order_by(FormSubmission.created_at.desc())
        .limit(SUBMISSIONS_LIMIT)
    )
    return list((await db.execute(statement)).scalars().all())


async def get_public_form(db: AsyncSession, slug: str) -> Form:
    statement = select(Form).where(Form.slug == slug, Form.is_public.is_(True))
    form = (await db.execute(statement)).scalar_one_or_none()
    if form is None:
        raise NotFoundError("Form not found")
    return form


def _is_blank(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def _format_value(value: object) -> str:
    if _is_blank(value):
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        return ", ".join(str(entry) for entry in value)
    return str(value)


def _task_title(form: Form, data: dict) -> str:
    for field in form.fields:
        if field.get("type") in ("text", "textarea"):
            value = data.get(field.get("key"))
            if isinstance(value, str) and value.strip():
                return value.strip()[:TITLE_MAX]
    return form.name[:TITLE_MAX]


def _task_description(form: Form, data: dict) -> str:
    lines = [
        f"- **{field.get('label')}:** {_format_value(data.get(field.get('key')))}"
        for field in form.fields
    ]
    body = "\n".join(lines)
    if body:
        body += "\n\n"
    return f"{body}Submitted via form {form.name}"


def _task_priority(form: Form, data: dict) -> str:
    for field in form.fields:
        if field.get("type") == "priority":
            value = data.get(field.get("key"))
            if isinstance(value, str) and value.lower() in PRIORITY_VALUES:
                return value.lower()
            return TaskPriority.MEDIUM
    return TaskPriority.MEDIUM


async def submit_form(db: AsyncSession, form: Form, data: dict) -> dict:
    """Validates answers and creates the intake task + submission row."""
    for field in form.fields:
        if field.get("required") and _is_blank(data.get(field.get("key"))):
            label = field.get("label") or field.get("key")
            raise ValidationFailedError(f"'{label}' is required")

    actor = await db.get(User, form.created_by_id) if form.created_by_id else None
    if actor is None:
        raise ValidationFailedError("The form owner no longer exists")
    project = await db.get(Project, form.project_id)
    if project is None:
        raise NotFoundError("Project not found")
    org = await db.get(Organization, form.organization_id)
    if org is None:
        raise NotFoundError("Organization not found")

    task = await task_service.create_task(
        db,
        actor,
        org,
        project,
        TaskCreate(
            title=_task_title(form, data),
            description=_task_description(form, data),
            priority=_task_priority(form, data),
            type=TaskType.TASK,
        ),
        run_automations=True,
    )
    submission = FormSubmission(
        organization_id=form.organization_id,
        form_id=form.id,
        task_id=task.id,
        data=data,
    )
    db.add(submission)
    form.submit_count = (form.submit_count or 0) + 1
    db.add(form)
    await db.commit()
    return {
        "task_id": task.id,
        "task_key": task.key,
        "detail": f"Submitted via form {form.name}",
    }
