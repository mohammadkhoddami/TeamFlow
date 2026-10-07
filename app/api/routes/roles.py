"""Custom role routes (M4 governance).

Org-scoped CRUD for named permission bundles; assignable to a membership via
`PATCH /organizations/{slug}/members/{user_id}` (`custom_role_id`).
Admin/owner only.
"""

import uuid

from fastapi import APIRouter, Request, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import DB, CurrentUser, OrgMembership
from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from app.models import CustomRole, MembershipRole
from app.schemas.role import CustomRoleCreate, CustomRoleRead, CustomRoleUpdate
from app.services import audit, permissions

router = APIRouter(prefix="/organizations/{slug}/roles", tags=["roles"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _require_admin(membership) -> None:
    if membership.role not in (MembershipRole.ADMIN, MembershipRole.OWNER):
        raise PermissionDeniedError("Only admins and owners can manage custom roles")


async def _get_role(db: AsyncSession, org_id: uuid.UUID, role_id: uuid.UUID) -> CustomRole:
    role = await db.get(CustomRole, role_id)
    if role is None or role.organization_id != org_id:
        raise NotFoundError("Custom role not found")
    return role


async def _name_taken(
    db: AsyncSession, org_id: uuid.UUID, name: str, exclude_id: uuid.UUID | None = None
) -> bool:
    statement = select(CustomRole.id).where(
        CustomRole.organization_id == org_id, CustomRole.name == name
    )
    if exclude_id is not None:
        statement = statement.where(CustomRole.id != exclude_id)
    return (await db.execute(statement)).scalars().first() is not None


@router.get("", response_model=list[CustomRoleRead])
async def list_roles(membership: OrgMembership, db: DB) -> list[CustomRoleRead]:
    org, m = membership
    _require_admin(m)
    statement = (
        select(CustomRole)
        .where(CustomRole.organization_id == org.id)
        .order_by(CustomRole.created_at.asc())
    )
    roles = list((await db.execute(statement)).scalars().all())
    return [CustomRoleRead.model_validate(role) for role in roles]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=CustomRoleRead)
async def create_role(
    data: CustomRoleCreate,
    membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> CustomRoleRead:
    org, m = membership
    _require_admin(m)
    if await _name_taken(db, org.id, data.name):
        raise ConflictError("A custom role with this name already exists")
    role = CustomRole(
        organization_id=org.id,
        name=data.name,
        description=data.description,
        permissions=permissions.validate_permissions(data.permissions),
        created_by_id=current_user.id,
    )
    db.add(role)
    await db.flush()
    await audit.log(
        db, "role.created", actor_id=current_user.id,
        organization_id=org.id, target_type="custom_role", target_id=role.id,
        ip=_ip(request), meta={"name": role.name},
    )
    await db.commit()
    await db.refresh(role)
    return CustomRoleRead.model_validate(role)


@router.patch("/{role_id}", response_model=CustomRoleRead)
async def update_role(
    role_id: uuid.UUID,
    data: CustomRoleUpdate,
    membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> CustomRoleRead:
    org, m = membership
    _require_admin(m)
    role = await _get_role(db, org.id, role_id)
    changed = data.model_fields_set
    if "name" in changed and data.name is not None and data.name != role.name:
        if await _name_taken(db, org.id, data.name, exclude_id=role.id):
            raise ConflictError("A custom role with this name already exists")
        role.name = data.name
    if "description" in changed:
        role.description = data.description
    if "permissions" in changed and data.permissions is not None:
        role.permissions = permissions.validate_permissions(data.permissions)
    db.add(role)
    await db.flush()
    await audit.log(
        db, "role.updated", actor_id=current_user.id,
        organization_id=org.id, target_type="custom_role", target_id=role.id,
        ip=_ip(request), meta={"fields": sorted(changed)},
    )
    await db.commit()
    await db.refresh(role)
    return CustomRoleRead.model_validate(role)


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: uuid.UUID,
    membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> None:
    org, m = membership
    _require_admin(m)
    role = await _get_role(db, org.id, role_id)
    await audit.log(
        db, "role.deleted", actor_id=current_user.id,
        organization_id=org.id, target_type="custom_role", target_id=role.id,
        ip=_ip(request), meta={"name": role.name},
    )
    await db.delete(role)
    await db.commit()
