"""Notification schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel
from sqlmodel import SQLModel


class NotificationRead(SQLModel):
    id: uuid.UUID
    user_id: uuid.UUID
    organization_id: uuid.UUID | None
    type: str
    title: str
    body: str | None
    data: dict | None
    read_at: datetime | None
    created_at: datetime


class UnreadCount(BaseModel):
    unread: int
