"""Notification routes: inbox list, unread count, mark read."""

import uuid

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.api.deps import DB, CurrentUser
from app.schemas import NotificationRead, Page, UnreadCount
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


@router.post("/{notification_id}/read", response_model=NotificationRead)
async def mark_read(
    notification_id: uuid.UUID, current_user: CurrentUser, db: DB
) -> NotificationRead:
    notification = await notification_service.mark_read(db, current_user, notification_id)
    return NotificationRead.model_validate(notification)


@router.post("/read-all", response_model=MarkAllReadResult)
async def mark_all_read(current_user: CurrentUser, db: DB) -> MarkAllReadResult:
    return MarkAllReadResult(marked=await notification_service.mark_all_read(db, current_user))

