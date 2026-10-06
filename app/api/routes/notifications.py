"""Notification routes: inbox list, unread count, mark read, project mutes."""

import uuid

from fastapi import APIRouter, Query, status
from pydantic import BaseModel

from app.api.deps import DB, CurrentUser
from app.core.exceptions import NotFoundError
from app.repositories import MembershipRepository, OrganizationRepository, ProjectRepository
from app.schemas import (
    NotificationMuteCreate,
    NotificationMuteRead,
    NotificationRead,
    Page,
    UnreadCount,
)
from app.services import mutes as mute_service
from app.services import notifications as notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


class MarkAllReadResult(BaseModel):
    marked: int


@router.get("", response_model=Page[NotificationRead])
async def list_notifications(
    current_user: CurrentUser,
    db: DB,
    unread_only: bool = Query(default=False),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> Page[NotificationRead]:
    items, total = await notification_service.list_notifications(
        db, current_user, unread_only=unread_only, offset=offset, limit=limit
    )
    return Page[NotificationRead](
        items=[NotificationRead.model_validate(n) for n in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/unread-count", response_model=UnreadCount)
async def unread_count(current_user: CurrentUser, db: DB) -> UnreadCount:
    return UnreadCount(unread=await notification_service.unread_count(db, current_user))


@router.get("/mutes", response_model=list[NotificationMuteRead])
async def list_mutes(current_user: CurrentUser, db: DB) -> list[NotificationMuteRead]:
    mutes = await mute_service.list_mutes(db, current_user)
    return [NotificationMuteRead.model_validate(mute) for mute in mutes]


@router.post(
    "/mutes", status_code=status.HTTP_201_CREATED, response_model=NotificationMuteRead
)
async def add_mute(
    data: NotificationMuteCreate, current_user: CurrentUser, db: DB
) -> NotificationMuteRead:
    # Mutes are per-user; the caller must still be a member of the project's org.
    project = await ProjectRepository(db).get(data.project_id)
    if project is None:
        raise NotFoundError("Project not found")
    membership = await MembershipRepository(db).get_for_user(
        current_user.id, project.organization_id
    )
    if membership is None or not membership.is_active:
        raise NotFoundError("Project not found")
    org = await OrganizationRepository(db).get(project.organization_id)
    if org is None:
        raise NotFoundError("Project not found")
    mute = await mute_service.add_mute(db, current_user, org, project)
    return NotificationMuteRead.model_validate(mute)


@router.delete("/mutes/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_mute(
    project_id: uuid.UUID, current_user: CurrentUser, db: DB
) -> None:
    await mute_service.remove_mute(db, current_user, project_id)


@router.post("/{notification_id}/read", response_model=NotificationRead)
async def mark_read(
    notification_id: uuid.UUID, current_user: CurrentUser, db: DB
) -> NotificationRead:
    notification = await notification_service.mark_read(db, current_user, notification_id)
    return NotificationRead.model_validate(notification)


@router.post("/read-all", response_model=MarkAllReadResult)
async def mark_all_read(current_user: CurrentUser, db: DB) -> MarkAllReadResult:
    return MarkAllReadResult(marked=await notification_service.mark_all_read(db, current_user))

