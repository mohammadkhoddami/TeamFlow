"""Per-project notification mutes (M3 #25)."""

import uuid

from sqlalchemy import Column, ForeignKey, Index, UniqueConstraint
from sqlalchemy import Uuid as SAUuid
from sqlmodel import Field, SQLModel

from app.models.base import TimeStampedMixin, UUIDMixin


class NotificationMute(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "notification_mutes"
    __table_args__ = (
        UniqueConstraint("user_id", "project_id", name="uq_notification_mute"),
        Index("ix_notification_mutes_user", "user_id"),
    )

    user_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    organization_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    project_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
