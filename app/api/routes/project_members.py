"""Per-project membership routes (M4 permissions).

Explicit project members are how non-admin members gain access to `private`
projects (see `app.api.deps` visibility checks). Managing the roster requires
the `projects.manage` permission.
"""

import uuid

from fastapi import APIRouter, Request, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import DB, CurrentUser, ProjectAccess
from app.core.exceptions import ConflictError, NotFoundError, ValidationFailedError
from app.models import ProjectMember
from app.repositories import MembershipRepository, UserRepository
from app.schemas.role import (
    ProjectMemberCreate,
    ProjectMemberRead,
    ProjectMemberUpdate,
)
from app.services import audit, permissions

router = APIRouter(prefix="/projects/{project_id}/members", tags=["project-members"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


async def _refetch(db: AsyncSession, member_id: uuid.UUID) -> ProjectMember:
    statement = select(ProjectMember).where(ProjectMember.id == member_id)
    return (await db.execute(statement)).scalar_one()


async def _get_member(
    db: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID
) -> ProjectMember:
    statement = select(ProjectMember).where(
        ProjectMember.project_id == project_id, ProjectMember.user_id == user_id
    )
    member = (await db.execute(statement)).scalar_one_or_none()
    if member is None:
        raise NotFoundError("Project member not found")
    return member


@router.get("", response_model=list[ProjectMemberRead])
async def list_project_members(
    project_access: ProjectAccess, db: DB
) -> list[ProjectMemberRead]:
    project, _org, membership = project_access
    await permissions.require_permission(db, membership, "projects.manage")
    statement = (
        select(ProjectMember)
        .where(ProjectMember.project_id == project.id)
        .order_by(ProjectMember.created_at.asc())
    )
    members = list((await db.execute(statement)).scalars().all())
    return [ProjectMemberRead.model_validate(member) for member in members]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ProjectMemberRead)
async def add_project_member(
    data: ProjectMemberCreate,
    project_access: ProjectAccess,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> ProjectMemberRead:
    project, org, membership = project_access
    await permissions.require_permission(db, membership, "projects.manage")

    user = await UserRepository(db).get_by_email(data.user_email)
    if user is None:
        raise NotFoundError("User with that email does not exist")
    org_membership = await MembershipRepository(db).get_for_user(user.id, org.id)
    if org_membership is None or not org_membership.is_active:
        raise ValidationFailedError("User must be an active member of this organization")

    statement = select(ProjectMember.id).where(
        ProjectMember.project_id == project.id, ProjectMember.user_id == user.id
    )
    if (await db.execute(statement)).scalars().first() is not None:
        raise ConflictError("User is already a member of this project")

    member = ProjectMember(
        organization_id=org.id,
        project_id=project.id,
        user_id=user.id,
        role=data.role,
    )
    db.add(member)
    await db.flush()
    await audit.log(
        db, "project.member_added", actor_id=current_user.id,
        organization_id=org.id, target_type="project_member", target_id=member.id,
        ip=_ip(request), meta={"project_id": str(project.id), "user_id": str(user.id)},
    )
    await db.commit()
    return ProjectMemberRead.model_validate(await _refetch(db, member.id))


@router.patch("/{user_id}", response_model=ProjectMemberRead)
async def update_project_member(
    user_id: uuid.UUID,
    data: ProjectMemberUpdate,
    project_access: ProjectAccess,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> ProjectMemberRead:
    project, org, membership = project_access
    await permissions.require_permission(db, membership, "projects.manage")
    member = await _get_member(db, project.id, user_id)
    member.role = data.role
    db.add(member)
    await db.flush()
    await audit.log(
        db, "project.member_updated", actor_id=current_user.id,
        organization_id=org.id, target_type="project_member", target_id=member.id,
        ip=_ip(request), meta={"role": data.role},
    )
    await db.commit()
    return ProjectMemberRead.model_validate(await _refetch(db, member.id))


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_project_member(
    user_id: uuid.UUID,
    project_access: ProjectAccess,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> None:
    project, org, membership = project_access
    await permissions.require_permission(db, membership, "projects.manage")
    member = await _get_member(db, project.id, user_id)
    await audit.log(
        db, "project.member_removed", actor_id=current_user.id,
        organization_id=org.id, target_type="project_member", target_id=member.id,
        ip=_ip(request), meta={"user_id": str(user_id)},
    )
    await db.delete(member)
    await db.commit()
