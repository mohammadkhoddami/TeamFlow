"""Webhook registration and delivery tracking models."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy import Uuid as SAUuid
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import TimeStampedMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.user import User


class WebhookEvent:
    TASK_CREATED = "task.created"
    TASK_UPDATED = "task.updated"
    TASK_COMPLETED = "task.completed"
    COMMENT_CREATED = "comment.created"
    MEMBER_JOINED = "member.joined"

    ALL = (TASK_CREATED, TASK_UPDATED, TASK_COMPLETED, COMMENT_CREATED, MEMBER_JOINED)


class Webhook(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "webhooks"

    organization_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    url: str = Field(sa_column=Column(String(2048), nullable=False))
    secret: str = Field(sa_column=Column(String(128), nullable=False))
    events: list[str] = Field(sa_column=Column(JSON, nullable=False))
    is_active: bool = Field(sa_column=Column(Boolean, nullable=False))
    description: str | None = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )
    created_by_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    organization: Optional["Organization"] = Relationship()
    created_by: Optional["User"] = Relationship()

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("is_active", True)
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return self.url


class DeliveryStatus:
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"

    ALL = (PENDING, SUCCESS, FAILED)


class WebhookDelivery(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        Index("ix_deliveries_webhook_created", "webhook_id", "created_at"),
    )

    webhook_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("webhooks.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    event: str = Field(sa_column=Column(String(64), nullable=False))
    payload: dict = Field(sa_column=Column(JSON, nullable=False))
    status: str = Field(sa_column=Column(String(16), nullable=False))
    attempts: int = Field(sa_column=Column(Integer, nullable=False))
    response_status: int | None = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    last_error: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    delivered_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

    webhook: Optional["Webhook"] = Relationship()

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("status", DeliveryStatus.PENDING)
        kwargs.setdefault("attempts", 0)
        super().__init__(**kwargs)
