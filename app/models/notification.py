"""Notification model: persisted, per-user inbox entries."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy import Uuid as SAUuid
from sqlmodel import Field, SQLModel

from app.models.base import TimeStampedMixin, UUIDMixin

if TYPE_CHECKING:
    pass


class NotificationType:
    TASK_ASSIGNED = "task_assigned"
    TASK_COMPLETED = "task_completed"
    COMMENT_CREATED = "comment_created"
    MENTION = "mention"
    INVITATION = "invitation"
    TASK_DUE_SOON = "task_due_soon"

    ALL = (
        TASK_ASSIGNED,
        TASK_COMPLETED,
        COMMENT_CREATED,
        MENTION,
        INVITATION,
        TASK_DUE_SOON,
    )


class Notification(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_read", "user_id", "read_at"),)

    user_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    organization_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    type: str = Field(sa_column=Column(String(32), nullable=False))
    title: str = Field(sa_column=Column(String(255), nullable=False))
    body: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    data: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    read_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
