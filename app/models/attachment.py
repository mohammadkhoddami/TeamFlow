"""Attachment model: metadata only, file bytes live in object storage."""

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, ForeignKey, Index, Integer, String
from sqlalchemy import Uuid as SAUuid
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import TimeStampedMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.task import Task
    from app.models.user import User


class AttachmentStatus:
    PENDING = "pending"  # upload URL issued, object not yet stored
    AVAILABLE = "available"
    FAILED = "failed"

    ALL = (PENDING, AVAILABLE, FAILED)


class Attachment(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "attachments"
    __table_args__ = (Index("ix_attachments_task", "task_id", "created_at"),)

    organization_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    task_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    uploader_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    filename: str = Field(sa_column=Column(String(255), nullable=False))
    content_type: str = Field(sa_column=Column(String(128), nullable=False))
    size: int = Field(sa_column=Column(Integer, nullable=False))
    storage_key: str = Field(
        sa_column=Column(String(512), unique=True, nullable=False)
    )
    status: str = Field(sa_column=Column(String(16), nullable=False))

    organization: Optional["Organization"] = Relationship()
    task: Optional["Task"] = Relationship()
    uploader: Optional["User"] = Relationship()

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("status", AttachmentStatus.PENDING)
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return self.filename

    def __str__(self) -> str:
        return self.__repr__()
