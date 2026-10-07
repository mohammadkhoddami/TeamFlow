"""Granular permissions (M4): effective permission resolution.

Roles are coarse (owner/admin/manager/member); a Membership may additionally
carry a `custom_role_id` pointing at an org-defined `CustomRole`, whose
`permissions` list is *unioned* on top of the base role's set. Call sites gate
actions with `require_permission(...)` so programmatic callers get identical
rules to HTTP routes.

`PERMISSIONS` is the closed vocabulary accepted in custom roles; unknown keys
must be rejected at creation time so typos can never silently grant nothing
(or, worse, be stored and misinterpreted later).
"""

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import PermissionDeniedError, ValidationFailedError
from app.models import CustomRole, Membership, MembershipRole

PERMISSIONS: tuple[str, ...] = (
    "tasks.delete",
    "tasks.manage",
    "projects.manage",
    "members.manage",
    "org.manage",
    "audit.view",
    "integrations.manage",
)

_ALL = set(PERMISSIONS)

# Base role -> permissions. Owner/admin hold everything; manager is the
# "operator" role (projects, integrations, task deletion); member can work on
# tasks and may be extended through a custom role.
BASE_BY_ROLE: dict[str, set[str]] = {
    MembershipRole.OWNER: set(_ALL),
    MembershipRole.ADMIN: set(_ALL),
    MembershipRole.MANAGER: {
        "tasks.delete",
        "tasks.manage",
        "projects.manage",
        "integrations.manage",
    },
    MembershipRole.MEMBER: {"tasks.manage"},
}


def validate_permissions(permissions: list[str] | None) -> list[str]:
    """Dedupes and rejects anything outside the closed vocabulary."""
    normalized: list[str] = []
    for key in permissions or []:
        if key not in _ALL:
            raise ValidationFailedError(f"Unknown permission: {key}")
        if key not in normalized:
            normalized.append(key)
    return normalized


async def effective_permissions(
    db: AsyncSession, membership: Membership
) -> set[str]:
    """Base role permissions union any attached custom role's permissions."""
    permissions = set(BASE_BY_ROLE.get(membership.role, set()))
    if membership.custom_role_id is not None:
        custom_role: CustomRole | None = await db.get(
            CustomRole, membership.custom_role_id
        )
        if (
            custom_role is not None
            and custom_role.organization_id == membership.organization_id
        ):
            permissions |= set(custom_role.permissions or [])
    return permissions


async def has_permission(
    db: AsyncSession, membership: Membership, key: str
) -> bool:
    return key in await effective_permissions(db, membership)


async def require_permission(
    db: AsyncSession, membership: Membership, key: str
) -> None:
    if not await has_permission(db, membership, key):
        raise PermissionDeniedError(f"Missing permission: {key}")
