"""Project service: CRUD with org-scoped authorization and side effects."""

import re
import uuid

from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import (
    ConflictError,
    NotFoundError,
)
from app.models import (
    AuditAction,
    EstimationUnit,
    Membership,
    MembershipRole,
    Organization,
    Project,
    ProjectMember,
    User,
)
from app.repositories import ProjectRepository
from app.schemas import ProjectCreate, ProjectUpdate
from app.services import audit, cache, permissions


async def _require_write(db: AsyncSession, membership: Membership) -> None:
    # Members work on tasks; only the projects.manage permission (managers+ or
    # a custom role) manages projects.
    await permissions.require_permission(db, membership, "projects.manage")


def derive_project_key(name: str) -> str:
    """TEAM from "TeamFlow" (letters/digits only, max 4, must start with a letter)."""
    letters = re.sub(r"[^A-Za-z0-9]", "", name).upper()
    base = letters[:4] or "PRJ"
    if base[0].isdigit():
        base = f"P{base}"[:4]
    return base


async def _unique_project_key(
    db: AsyncSession, org_id: uuid.UUID, base: str, exclude_id: uuid.UUID | None = None
) -> str:
    statement = select(Project.key).where(
        Project.organization_id == org_id, Project.key.is_not(None)
    )
    if exclude_id is not None:
        statement = statement.where(Project.id != exclude_id)
    used = {row.upper() for row in (await db.execute(statement)).scalars()}
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base[:2]}{suffix}"
        suffix += 1
    return candidate


async def _project_key_taken(db: AsyncSession, org_id: uuid.UUID, key: str) -> bool:
    statement = select(Project.id).where(
        Project.organization_id == org_id,
        Project.key == key,
    )
    return (await db.execute(statement)).scalars().first() is not None


async def create_project(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    data: ProjectCreate,
    ip: str | None = None,
) -> Project:
    await _require_write(db, membership)
    key = data.key or derive_project_key(data.name)
    key = (await _unique_project_key(db, org.id, key)).upper()
    project = Project(
        organization_id=org.id,
        name=data.name,
        description=data.description,
        owner_id=actor.id,
        key=key,
        estimation_unit=data.estimation_unit or EstimationUnit.POINTS,
    )
    project = await ProjectRepository(db).add(project)
    await audit.log(
        db, AuditAction.PROJECT_CREATED, actor_id=actor.id,
        organization_id=org.id, target_type="project", target_id=project.id, ip=ip,
        meta={"name": data.name, "key": key},
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
    membership: Membership | None = None,
) -> tuple[list[Project], int]:
    projects, total = await ProjectRepository(db).list_for_org(
        organization_id, status=status, offset=offset, limit=limit
    )
    # Private projects are hidden from non-admin/owner members who are not on
    # the project roster. (Rows are concealed, not just permission-gated.)
    if membership is None or membership.role in (
        MembershipRole.ADMIN,
        MembershipRole.OWNER,
    ):
        return projects, total
    member_project_ids = set(
        (
            await db.execute(
                select(ProjectMember.project_id).where(
                    ProjectMember.organization_id == organization_id,
                    ProjectMember.user_id == membership.user_id,
                )
            )
        ).scalars()
    )
    hidden_ids = [
        project.id
        for project in projects
        if project.visibility == "private" and project.id not in member_project_ids
    ]
    if not hidden_ids:
        return projects, total
    visible = [project for project in projects if project.id not in hidden_ids]
    hidden_count_stmt = select(func.count(Project.id)).where(
        Project.organization_id == organization_id,
        Project.visibility == "private",
        Project.id.not_in(
            select(ProjectMember.project_id).where(
                ProjectMember.organization_id == organization_id,
                ProjectMember.user_id == membership.user_id,
            )
        ),
    )
    if status:
        hidden_count_stmt = hidden_count_stmt.where(Project.status == status)
    hidden_total = (await db.execute(hidden_count_stmt)).scalar_one()
    return visible, max(0, total - hidden_total)


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
    await _require_write(db, membership)
    if data.name is not None:
        project.name = data.name
    if data.description is not None:
        project.description = data.description
    if data.status is not None:
        project.status = data.status
    if data.visibility is not None:
        project.visibility = data.visibility
    if data.key is not None:
        new_key = data.key.upper()
        if new_key != (project.key or "").upper():
            if await _project_key_taken(db, org.id, new_key):
                raise ConflictError(f"Issue key '{new_key}' is already used in this org")
            project.key = new_key
    if data.estimation_unit is not None:
        project.estimation_unit = data.estimation_unit
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
    await _require_write(db, membership)
    await audit.log(
        db, AuditAction.PROJECT_DELETED, actor_id=actor.id,
        organization_id=org.id, target_type="project", target_id=project.id, ip=ip,
    )
    await ProjectRepository(db).delete(project)
    await db.commit()
    await cache.invalidate_dashboard(org.id)
