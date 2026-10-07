"""Notification schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel
from sqlmodel import SQLModel


class NotificationRead(SQLModel):
    id: uuid.UUID
    user_id: uuid.UUID
    organization_id: uuid.UUID | None
    project_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    type: str
    title: str
    body: str | None
    data: dict | None
    read_at: datetime | None
    created_at: datetime


class NotificationMuteCreate(SQLModel):
    project_id: uuid.UUID


class NotificationMuteRead(SQLModel):
    id: uuid.UUID
    project_id: uuid.UUID
    organization_id: uuid.UUID
    created_at: datetime


class UnreadCount(BaseModel):
    unread: int
