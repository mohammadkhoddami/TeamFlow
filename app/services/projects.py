"""Project service: CRUD with org-scoped authorization and side effects."""

import uuid

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.models import (
    AuditAction,
    Membership,
    MembershipRole,
    Organization,
    Project,
    User,
)
from app.repositories import ProjectRepository
from app.schemas import ProjectCreate, ProjectUpdate
from app.services import audit, cache


def _require_write(membership: Membership) -> None:
    if membership.role == MembershipRole.MEMBER:
        # Members work on tasks; only managers and above manage projects.
        raise PermissionDeniedError("Only managers and above can manage projects")


async def create_project(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    data: ProjectCreate,
    ip: str | None = None,
) -> Project:
    _require_write(membership)
    project = Project(
        organization_id=org.id,
        name=data.name,
        description=data.description,
        owner_id=actor.id,
    )
    project = await ProjectRepository(db).add(project)
    await audit.log(
        db, AuditAction.PROJECT_CREATED, actor_id=actor.id,
        organization_id=org.id, target_type="project", target_id=project.id, ip=ip,
        meta={"name": data.name},
    )
    await db.commit()
    await db.refresh(project)
    return project


async def list_projects(
    db: AsyncSession,
    organization_id: uuid.UUID,
    *,
    status: str | None = None,
    offset: int = 0,
    limit: int = 20,
) -> tuple[list[Project], int]:
    return await ProjectRepository(db).list_for_org(
        organization_id, status=status, offset=offset, limit=limit
    )


async def get_project_for_org(
    db: AsyncSession, project_id: uuid.UUID, organization_id: uuid.UUID
) -> Project:
    project = await ProjectRepository(db).get_in_org(project_id, organization_id)
    if not project:
        # 404 hides cross-org existence (IDOR containment).
        raise NotFoundError("Project not found")
    return project


async def update_project(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    project: Project,
    data: ProjectUpdate,
    ip: str | None = None,
) -> Project:
    _require_write(membership)
    if data.name is not None:
        project.name = data.name
    if data.description is not None:
        project.description = data.description
    if data.status is not None:
        project.status = data.status
    project = await ProjectRepository(db).update(project)
    await audit.log(
        db, AuditAction.PROJECT_UPDATED, actor_id=actor.id,
        organization_id=org.id, target_type="project", target_id=project.id, ip=ip,
        meta={"fields": sorted(data.model_fields_set)},
    )
    await db.commit()
    await cache.invalidate_dashboard(org.id)
    return project


async def delete_project(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    project: Project,
    ip: str | None = None,
) -> None:
    _require_write(membership)
    await audit.log(
        db, AuditAction.PROJECT_DELETED, actor_id=actor.id,
        organization_id=org.id, target_type="project", target_id=project.id, ip=ip,
    )
    await ProjectRepository(db).delete(project)
    await db.commit()
    await cache.invalidate_dashboard(org.id)
