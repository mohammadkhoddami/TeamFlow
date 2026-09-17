"""Idempotency key store.

Rows are created *before* the operation runs (INSERT with a unique key), so a
concurrent duplicate hits the database constraint, not a post-hoc check. State
machine: `in_progress` -> `completed` (replayable) or `failed` (retryable).
Rows expire after `settings.idempotency_ttl_hours` (cleanup via Celery Beat).
"""

import uuid

from sqlalchemy import (
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy import Uuid as SAUuid
from sqlmodel import Field, SQLModel

from app.models.base import TimeStampedMixin, UUIDMixin


class IdempotencyStatus:
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class IdempotencyKey(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "idempotency_keys"
    __table_args__ = (Index("ix_idempotency_created", "created_at"),)

    key: str = Field(sa_column=Column(String(128), unique=True, nullable=False))
    user_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    method: str = Field(sa_column=Column(String(8), nullable=False))
    path: str = Field(sa_column=Column(String(512), nullable=False))
    request_hash: str = Field(sa_column=Column(String(64), nullable=False))
    status: str = Field(sa_column=Column(String(16), nullable=False))
    response_status: int | None = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    content_type: str | None = Field(
        default=None, sa_column=Column(String(128), nullable=True)
    )
    response_body: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("status", IdempotencyStatus.IN_PROGRESS)
        super().__init__(**kwargs)
