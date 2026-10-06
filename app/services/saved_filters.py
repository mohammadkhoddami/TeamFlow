"""Saved filter service: per-user / shared TeamQL views."""

import uuid

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from app.models import Membership, Organization, SavedFilter, User
from app.repositories import (
    LabelRepository,
    MembershipRepository,
    ProjectRepository,
    SavedFilterRepository,
    SprintRepository,
)
from app.schemas import SavedFilterCreate, SavedFilterUpdate
from app.services.teamql import parse_teamql


async def _validate_query(db: AsyncSession, org_id: uuid.UUID, query: str) -> None:
    """Parse eagerly so broken filters are rejected at save time."""
    members = await MembershipRepository(db).list_for_org(org_id, limit=1000)
    emails = {
        (m.user.email.lower() if m.user else ""): m.user_id
        for m in members
        if m.user is not None
    }
    labels = await LabelRepository(db).list_for_org(org_id)
    labels_by_name = {label.name.lower(): label.id for label in labels}
    sprints: dict[str, uuid.UUID] = {}
    for sprint, project_name in await SprintRepository(db).list_for_org(org_id):
        sprints[f"{project_name}:{sprint.name}".lower()] = sprint.id
        sprints.setdefault(sprint.name.lower(), sprint.id)
    parse_teamql(
        query,
        members_by_email=emails,
        labels_by_name=labels_by_name,
        sprints_by_name=sprints,
    )


async def create_saved_filter(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    data: SavedFilterCreate,
) -> SavedFilter:
    if data.project_id is not None:
        project = await ProjectRepository(db).get_in_org(data.project_id, org.id)
        if project is None:
            raise NotFoundError("Project not found")
    await _validate_query(db, org.id, data.query)
    repo = SavedFilterRepository(db)
    if await _exists(db, org.id, actor.id, data.project_id, data.name, exclude_id=None):
        raise ConflictError("You already have a saved filter with this name")
    saved = await repo.add(
        SavedFilter(
            organization_id=org.id,
            project_id=data.project_id,
            owner_id=actor.id,
            name=data.name,
            query=data.query,
            is_shared=data.is_shared,
        )
    )
    await db.commit()
    return saved


async def _exists(
    db: AsyncSession,
    org_id: uuid.UUID,
    owner_id: uuid.UUID,
    project_id: uuid.UUID | None,
    name: str,
    exclude_id: uuid.UUID | None,
) -> bool:
    from sqlmodel import select

    statement = select(SavedFilter).where(
        SavedFilter.organization_id == org_id,
        SavedFilter.owner_id == owner_id,
        SavedFilter.name == name,
    )
    if project_id is None:
        statement = statement.where(SavedFilter.project_id.is_(None))
    else:
        statement = statement.where(SavedFilter.project_id == project_id)
    if exclude_id is not None:
        statement = statement.where(SavedFilter.id != exclude_id)
    return (await db.execute(statement)).scalars().first() is not None


async def list_saved_filters(
    db: AsyncSession, org_id: uuid.UUID, actor: User
) -> list[SavedFilter]:
    return await SavedFilterRepository(db).list_visible(org_id, actor.id)


async def get_saved_filter_for_org(
    db: AsyncSession, saved_filter_id: uuid.UUID, organization_id: uuid.UUID
) -> SavedFilter:
    saved = await SavedFilterRepository(db).get_in_org(saved_filter_id, organization_id)
    if not saved:
        raise NotFoundError("Saved filter not found")
    return saved


async def update_saved_filter(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    saved: SavedFilter,
    data: SavedFilterUpdate,
) -> SavedFilter:
    if saved.owner_id != actor.id:
        raise PermissionDeniedError("Only the owner can edit a saved filter")
    if data.query is not None:
        await _validate_query(db, org.id, data.query)
        saved.query = data.query
    if data.name is not None:
        saved.name = data.name
    if data.is_shared is not None:
        saved.is_shared = data.is_shared
    saved = await SavedFilterRepository(db).update(saved)
    await db.commit()
    return saved


async def delete_saved_filter(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    saved: SavedFilter,
) -> None:
    if saved.owner_id != actor.id:
        raise PermissionDeniedError("Only the owner can delete a saved filter")
    await SavedFilterRepository(db).delete(saved)
    await db.commit()
