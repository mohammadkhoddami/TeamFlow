"""Organization + membership services.

Authorization model (documented once, enforced everywhere):
  rank: member=1, manager=2, admin=3, owner=4
  - org update:              admin+
  - org delete:              owner only
  - list members:            any member
  - change member role:      actor strictly outranks target AND new role
  - remove member:           actor outranks target, or member removes self
  - owner cannot be removed or demoted (ownership transfer out of scope)

Tenant boundary: every call resolves (org, membership) via
`get_organization_for_user`, which 404s instead of 403 for non-members so
outside users cannot even confirm an org slug exists. Invitation flows live
in `app.services.invitations`.
"""

import uuid

from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationFailedError,
)
from app.models import (
    AuditAction,
    Membership,
    MembershipRole,
    Organization,
    User,
)
from app.repositories import (
    MembershipRepository,
    OrganizationRepository,
    UserRepository,
)
from app.schemas import OrganizationCreate, OrganizationUpdate
from app.services import audit

ROLE_RANK = {
    MembershipRole.MEMBER: 1,
    MembershipRole.MANAGER: 2,
    MembershipRole.ADMIN: 3,
    MembershipRole.OWNER: 4,
}


def role_rank(role: str) -> int:
    return ROLE_RANK.get(role, -1)


# ---------- Organizations ----------


async def create_organization(
    db: AsyncSession, owner: User, data: OrganizationCreate, ip: str | None = None
) -> Organization:
    org_repo = OrganizationRepository(db)
    if await org_repo.get_by_slug(data.slug):
        raise ConflictError("An organization with this slug already exists")

    # Org + owner membership commit atomically: one unit of work.
    org = Organization(name=data.name, slug=data.slug, created_by_id=owner.id)
    org = await org_repo.add(org)
    await MembershipRepository(db).add(
        Membership(user_id=owner.id, organization_id=org.id, role=MembershipRole.OWNER)
    )
    await audit.log(
        db, AuditAction.ORG_CREATED, actor_id=owner.id,
        organization_id=org.id, target_type="organization", target_id=org.id, ip=ip,
    )
    await db.commit()
    await db.refresh(org)
    return org


async def list_organizations(
    db: AsyncSession,
    user: User,
    *,
    offset: int = 0,
    limit: int = 20,
) -> tuple[list[Organization], list[str], int]:
    org_repo = OrganizationRepository(db)
    orgs, roles = await org_repo.list_for_user(user.id, offset=offset, limit=limit)
    total = await org_repo.count_for_user(user.id)
    return orgs, roles, total


async def get_organization_for_user(
    db: AsyncSession, user: User, slug_or_id: str | uuid.UUID
) -> tuple[Organization, Membership]:
    """Tenant boundary check: raises unless `user` belongs to the org.
    404 (not 403) for non-members so org existence is not confirmed to outsiders."""
    org: Organization | None
    if isinstance(slug_or_id, uuid.UUID):
        org = await OrganizationRepository(db).get(slug_or_id)
    else:
        org = await OrganizationRepository(db).get_by_slug(str(slug_or_id))
    if not org:
        raise NotFoundError("Organization not found")
    membership = await MembershipRepository(db).get_for_user(user.id, org.id)
    if not membership or not membership.is_active:
        raise NotFoundError("Organization not found")
    return org, membership


async def update_organization(
    db: AsyncSession,
    actor: User,
    slug: str,
    data: OrganizationUpdate,
    ip: str | None = None,
) -> Organization:
    org, membership = await get_organization_for_user(db, actor, slug)
    if role_rank(membership.role) < role_rank(MembershipRole.ADMIN):
        raise PermissionDeniedError("Only admins and owners can update an organization")

    if data.name is not None:
        org.name = data.name
    if data.is_active is not None:
        org.is_active = data.is_active
    org = await OrganizationRepository(db).update(org)
    await audit.log(
        db, AuditAction.ORG_UPDATED, actor_id=actor.id,
        organization_id=org.id, target_type="organization", target_id=org.id, ip=ip,
        meta={"fields": sorted(data.model_fields_set)},
    )
    await db.commit()
    return org


async def delete_organization(
    db: AsyncSession, actor: User, slug: str, ip: str | None = None
) -> None:
    org, membership = await get_organization_for_user(db, actor, slug)
    if membership.role != MembershipRole.OWNER:
        raise PermissionDeniedError("Only the owner can delete an organization")
    org_id = org.id
    await audit.log(
        db, AuditAction.ORG_DELETED, actor_id=actor.id,
        organization_id=org_id, target_type="organization", target_id=org_id, ip=ip,
    )
    await OrganizationRepository(db).delete(org)
    await db.commit()


# ---------- Members ----------


async def list_members(
    db: AsyncSession, organization_id: uuid.UUID, *, offset: int = 0, limit: int = 50
) -> list[Membership]:
    return await MembershipRepository(db).list_for_org(
        organization_id, offset=offset, limit=limit
    )


async def add_member_direct(
    db: AsyncSession,
    actor: User,
    slug: str,
    user_email: str,
    role: str = MembershipRole.MEMBER,
    ip: str | None = None,
) -> Membership:
    """Directly adds an existing user (used internally; invitations are the
    user-facing path). Kept for tests and admin flows."""
    if role not in MembershipRole.ALL:
        raise ValidationFailedError(f"Invalid role: {role}")

    org, actor_membership = await get_organization_for_user(db, actor, slug)
    if role_rank(actor_membership.role) < role_rank(MembershipRole.ADMIN):
        raise PermissionDeniedError("Only admins and owners can add members directly")
    if role == MembershipRole.OWNER:
        raise ValidationFailedError("Ownership transfer is not supported")

    user = await UserRepository(db).get_by_email(user_email)
    if not user:
        raise NotFoundError("User with that email does not exist")

    membership_repo = MembershipRepository(db)
    if await membership_repo.get_for_user(user.id, org.id):
        raise ConflictError("User is already a member of this organization")

    membership = await membership_repo.add(
        Membership(user_id=user.id, organization_id=org.id, role=role)
    )
    await db.commit()
    # Re-select so the joined-eager `user` relationship is loaded (fresh
    # instances do not trigger eager strategies; implicit lazy loads are
    # unsafe in async sessions).
    return (await db.execute(select(Membership).where(Membership.id == membership.id))).scalar_one()


async def update_member_role(
    db: AsyncSession,
    actor: User,
    slug: str,
    target_user_id: uuid.UUID,
    new_role: str,
    ip: str | None = None,
) -> Membership:
    if new_role not in MembershipRole.ALL:
        raise ValidationFailedError(f"Invalid role: {new_role}")

    org, actor_membership = await get_organization_for_user(db, actor, slug)
    target = await MembershipRepository(db).get_for_user(target_user_id, org.id)
    if not target:
        raise NotFoundError("Membership not found")

    # Nobody (not even the owner) edits their own role via this endpoint.
    if target.user_id == actor.id:
        raise PermissionDeniedError("You cannot change your own role")
    if target.role == MembershipRole.OWNER:
        raise PermissionDeniedError("The owner's role cannot be changed")
    if new_role == MembershipRole.OWNER:
        raise PermissionDeniedError("Ownership transfer is not supported")
    # Actor must strictly outrank both the target and the role being granted.
    if role_rank(actor_membership.role) <= max(
        role_rank(target.role), role_rank(new_role)
    ):
        raise PermissionDeniedError("Not enough permissions to assign that role")

    old_role = target.role
    target.role = new_role
    target = await MembershipRepository(db).update(target)
    await audit.log(
        db, AuditAction.MEMBER_ROLE_CHANGED, actor_id=actor.id,
        organization_id=org.id, target_type="membership", target_id=target.id, ip=ip,
        meta={"user_id": str(target.user_id), "old_role": old_role, "new_role": new_role},
    )
    await db.commit()
    return target


async def remove_member(
    db: AsyncSession,
    actor: User,
    slug: str,
    target_user_id: uuid.UUID,
    ip: str | None = None,
) -> None:
    org, actor_membership = await get_organization_for_user(db, actor, slug)
    target = await MembershipRepository(db).get_for_user(target_user_id, org.id)
    if not target:
        raise NotFoundError("Membership not found")

    if target.role == MembershipRole.OWNER:
        raise PermissionDeniedError("The owner cannot be removed")
    # A member may leave the org themselves; otherwise actor must outrank target.
    if target.user_id != actor.id and role_rank(actor_membership.role) <= role_rank(
        target.role
    ):
        raise PermissionDeniedError("Not enough permissions to remove that member")

    removed_user_id = target.user_id
    await MembershipRepository(db).delete(target)
    await audit.log(
        db, AuditAction.MEMBER_REMOVED, actor_id=actor.id,
        organization_id=org.id, target_type="membership", target_id=target.id, ip=ip,
        meta={"removed_user_id": str(removed_user_id), "self_leave": removed_user_id == actor.id},
    )
    await db.commit()
