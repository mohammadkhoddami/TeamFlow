"""Custom field service: definitions, typed value validation, task values."""

import uuid
from datetime import date, datetime

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationFailedError,
)
from app.models import (
    CustomField,
    CustomFieldType,
    CustomFieldValue,
    Membership,
    MembershipRole,
    Organization,
    Project,
    User,
)
from app.repositories import CustomFieldRepository, CustomFieldValueRepository
from app.schemas import CustomFieldCreate, CustomFieldUpdate, slugify_key


def _require_manage(membership: Membership) -> None:
    if membership.role == MembershipRole.MEMBER:
        raise PermissionDeniedError("Only managers and above can manage custom fields")


async def list_fields(db: AsyncSession, project_id: uuid.UUID) -> list[CustomField]:
    return await CustomFieldRepository(db).list_for_project(project_id)


async def get_field_for_project(
    db: AsyncSession, field_id: uuid.UUID, project_id: uuid.UUID
) -> CustomField:
    field = await CustomFieldRepository(db).get_in_project(field_id, project_id)
    if not field:
        raise NotFoundError("Custom field not found")
    return field


async def create_field(
    db: AsyncSession,
    actor: User,
    org: Organization,
    project: Project,
    membership: Membership,
    data: CustomFieldCreate,
) -> CustomField:
    _require_manage(membership)
    if data.field_type not in CustomFieldType.ALL:
        raise ValidationFailedError(f"Unknown field type '{data.field_type}'")
    if data.field_type in (CustomFieldType.SELECT, CustomFieldType.MULTI_SELECT) and not data.options:
        raise ValidationFailedError("Select fields need at least one option")
    key = data.key or slugify_key(data.name)
    repo = CustomFieldRepository(db)
    if await repo.get_by_key(project.id, key):
        raise ConflictError(f"A custom field with key '{key}' already exists")
    field = await repo.add(
        CustomField(
            organization_id=org.id,
            project_id=project.id,
            name=data.name,
            key=key,
            field_type=data.field_type,
            options=list(data.options),
            is_required=data.is_required,
            position=len(await repo.list_for_project(project.id)),
        )
    )
    await db.commit()
    return field


async def update_field(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    field: CustomField,
    data: CustomFieldUpdate,
) -> CustomField:
    _require_manage(membership)
    changed = data.model_fields_set
    if "name" in changed and data.name is not None:
        field.name = data.name
    if "options" in changed and data.options is not None:
        if field.field_type in (CustomFieldType.SELECT, CustomFieldType.MULTI_SELECT):
            if not data.options:
                raise ValidationFailedError("Select fields need at least one option")
        field.options = list(data.options)
    if "is_required" in changed and data.is_required is not None:
        field.is_required = data.is_required
    if "position" in changed and data.position is not None:
        field.position = data.position
    field = await CustomFieldRepository(db).update(field)
    await db.commit()
    return field


async def delete_field(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    field: CustomField,
) -> None:
    _require_manage(membership)
    await CustomFieldRepository(db).delete(field)
    await db.commit()


def validate_value(field: CustomField, raw: object) -> object:
    """Validates + normalizes one value for a field type."""
    if raw is None or raw == "":
        return None
    if field.field_type == CustomFieldType.TEXT:
        if not isinstance(raw, str):
            raise ValidationFailedError(f"'{field.name}' expects text")
        if len(raw) > 2000:
            raise ValidationFailedError(f"'{field.name}' is too long (max 2000)")
        return raw
    if field.field_type == CustomFieldType.NUMBER:
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ValidationFailedError(f"'{field.name}' expects a number")
        return float(raw)
    if field.field_type == CustomFieldType.CHECKBOX:
        if not isinstance(raw, bool):
            raise ValidationFailedError(f"'{field.name}' expects true/false")
        return raw
    if field.field_type == CustomFieldType.DATE:
        if isinstance(raw, datetime):
            return raw.isoformat()
        if isinstance(raw, date):
            return raw.isoformat()
        if not isinstance(raw, str):
            raise ValidationFailedError(f"'{field.name}' expects a date")
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            raise ValidationFailedError(f"'{field.name}' expects an ISO date") from None
        return parsed.date().isoformat()
    if field.field_type == CustomFieldType.SELECT:
        if not isinstance(raw, str) or raw not in field.options:
            raise ValidationFailedError(
                f"'{field.name}' must be one of: {', '.join(field.options)}"
            )
        return raw
    if field.field_type == CustomFieldType.MULTI_SELECT:
        if not isinstance(raw, list) or not all(isinstance(entry, str) for entry in raw):
            raise ValidationFailedError(f"'{field.name}' expects a list of options")
        invalid = [entry for entry in raw if entry not in field.options]
        if invalid:
            raise ValidationFailedError(
                f"'{field.name}' has invalid options: {', '.join(invalid)}"
            )
        return raw
    if field.field_type == CustomFieldType.USER:
        if not isinstance(raw, str):
            raise ValidationFailedError(f"'{field.name}' expects a user id")
        try:
            return str(uuid.UUID(raw))
        except ValueError:
            raise ValidationFailedError(f"'{field.name}' expects a valid user id") from None
    raise ValidationFailedError(f"Unsupported field type '{field.field_type}'")


async def resolve_values(
    db: AsyncSession, project: Project, values: dict[str, object]
) -> dict[uuid.UUID, object]:
    """Maps `{field key or id: value}` to `{field_id: validated value}`."""
    repo = CustomFieldRepository(db)
    resolved: dict[uuid.UUID, object] = {}
    for key, raw in values.items():
        field = None
        try:
            field = await repo.get_in_project(uuid.UUID(str(key)), project.id)
        except ValueError:
            field = None
        if field is None:
            field = await repo.get_by_key(project.id, str(key))
        if field is None:
            raise ValidationFailedError(f"Unknown custom field '{key}'")
        resolved[field.id] = validate_value(field, raw)
    return resolved


async def assert_required_present(
    db: AsyncSession, project: Project, values: dict[uuid.UUID, object]
) -> None:
    for field in await list_fields(db, project.id):
        if field.is_required and not values.get(field.id):
            raise ValidationFailedError(f"'{field.name}' is required")


async def assert_required_satisfied(
    db: AsyncSession, project: Project, task_id: uuid.UUID
) -> None:
    """Creation must not leave required fields empty."""
    rows = await CustomFieldValueRepository(db).list_for_tasks([task_id])
    stored = {row.field_id: row.value for row in rows}
    for field in await list_fields(db, project.id):
        if not field.is_required:
            continue
        if stored.get(field.id) in (None, "", []):
            raise ValidationFailedError(f"'{field.name}' is required")


async def assert_required_not_cleared(
    db: AsyncSession, project: Project, values: dict[uuid.UUID, object]
) -> None:
    """Partial updates may not clear a required field (untouched fields stay)."""
    for field in await list_fields(db, project.id):
        if field.is_required and field.id in values and values[field.id] is None:
            raise ValidationFailedError(f"'{field.name}' is required")


async def set_task_values(
    db: AsyncSession,
    organization_id: uuid.UUID,
    task_id: uuid.UUID,
    values: dict[uuid.UUID, object],
) -> None:
    repo = CustomFieldValueRepository(db)
    for field_id, value in values.items():
        existing = await repo.get(task_id, field_id)
        if value is None:
            if existing:
                await repo.delete(existing)
            continue
        if existing:
            existing.value = value
            await repo.update(existing)
        else:
            await repo.add(
                CustomFieldValue(
                    organization_id=organization_id,
                    task_id=task_id,
                    field_id=field_id,
                    value=value,
                )
            )


async def values_for_tasks(
    db: AsyncSession, task_ids: list[uuid.UUID], project_id: uuid.UUID
) -> dict[uuid.UUID, list[dict]]:
    """`task_id -> [{field_id,key,name,field_type,value}]` (batched)."""
    rows = await CustomFieldValueRepository(db).list_for_tasks(task_ids)
    if not rows:
        return {}
    fields = {field.id: field for field in await list_fields(db, project_id)}
    result: dict[uuid.UUID, list[dict]] = {}
    for row in rows:
        field = fields.get(row.field_id)
        if field is None:
            continue
        result.setdefault(row.task_id, []).append(
            {
                "field_id": field.id,
                "key": field.key,
                "name": field.name,
                "field_type": field.field_type,
                "value": row.value,
            }
        )
    return result
