"""Organization + member routes."""

import uuid

from fastapi import APIRouter, Query, Request, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app import services
from app.api.deps import DB, CurrentUser, OrgMembership
from app.models import CustomRole
from app.schemas import (
    MembershipCreate,
    MembershipRead,
    MembershipUpdate,
    OrganizationCreate,
    OrganizationMemberRead,
    OrganizationRead,
    OrganizationUpdate,
)
from app.services import auth  # noqa: F401  (auth imported for parity)

router = APIRouter(prefix="/organizations", tags=["organizations"])

MEMBER_TAGS = ["members"]


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("", status_code=status.HTTP_201_CREATED, response_model=OrganizationRead)
async def create_organization(
    data: OrganizationCreate, current_user: CurrentUser, request: Request, db: DB
) -> OrganizationRead:
    org = await services.create_organization(db, current_user, data, ip=_ip(request))
    return OrganizationRead.model_validate(org).model_copy(update={"my_role": "owner"})


@router.get("", response_model=list[OrganizationMemberRead])
async def list_organizations(
    current_user: CurrentUser,
    db: DB,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[OrganizationMemberRead]:
    orgs, roles, _total = await services.list_organizations(
        db, current_user, offset=offset, limit=limit
    )
    return [
        OrganizationMemberRead(
            organization=OrganizationRead.model_validate(org), role=role
        )
        for org, role in zip(orgs, roles, strict=True)
    ]


@router.get("/{slug}", response_model=OrganizationRead)
async def get_organization(membership: OrgMembership, current_user: CurrentUser) -> OrganizationRead:
    org, my_membership = membership
    return OrganizationRead.model_validate(org).model_copy(
        update={"my_role": my_membership.role}
    )


@router.patch("/{slug}", response_model=OrganizationRead)
async def update_organization(
    data: OrganizationUpdate,
    membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> OrganizationRead:
    org, _m = membership
    updated = await services.organizations.update_organization(
        db, current_user, org.slug, data, ip=_ip(request)
    )
    return OrganizationRead.model_validate(updated)


@router.delete("/{slug}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organization(
    membership: OrgMembership, current_user: CurrentUser, request: Request, db: DB
) -> None:
    org, _m = membership
    await services.organizations.delete_organization(
        db, current_user, org.slug, ip=_ip(request)
    )


# ---------- Members within an org ----------

members_router = APIRouter(prefix="/organizations/{slug}/members", tags=MEMBER_TAGS)


async def _serialize_membership(db: AsyncSession, membership) -> MembershipRead:
    payload = MembershipRead.model_validate(membership)
    if membership.custom_role_id:
        custom_role = await db.get(CustomRole, membership.custom_role_id)
        payload.custom_role_name = custom_role.name if custom_role else None
    return payload


@members_router.get("", response_model=list[MembershipRead])
async def list_members(
    membership: OrgMembership,
    db: DB,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[MembershipRead]:
    org, _m = membership
    items = await services.organizations.list_members(db, org.id, offset=offset, limit=limit)
    role_ids = {m.custom_role_id for m in items if m.custom_role_id}
    names: dict[uuid.UUID, str] = {}
    if role_ids:
        roles = (
            await db.execute(select(CustomRole).where(CustomRole.id.in_(role_ids)))
        ).scalars()
        names = {role.id: role.name for role in roles}
    return [
        MembershipRead.model_validate(m).model_copy(
            update={"custom_role_name": names.get(m.custom_role_id)}
        )
        for m in items
    ]


@members_router.post("", status_code=status.HTTP_201_CREATED, response_model=MembershipRead)
async def add_member(
    data: MembershipCreate,
    membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> MembershipRead:
    org, _m = membership
    m = await services.organizations.add_member_direct(
        db, current_user, org.slug, data.user_email, data.role, ip=_ip(request)
    )
    return MembershipRead.model_validate(m)


@members_router.patch("/{user_id}", response_model=MembershipRead)
async def update_member(
    user_id: uuid.UUID,
    data: MembershipUpdate,
    membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> MembershipRead:
    org, _m = membership
    m = await services.organizations.update_member_role(
        db,
        current_user,
        org.slug,
        user_id,
        data.role,
        ip=_ip(request),
        custom_role_id=data.custom_role_id,
        update_custom_role="custom_role_id" in data.model_fields_set,
    )
    return await _serialize_membership(db, m)


@members_router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    user_id: uuid.UUID,
    membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> None:
    org, _m = membership
    await services.organizations.remove_member(
        db, current_user, org.slug, user_id, ip=_ip(request)
    )
