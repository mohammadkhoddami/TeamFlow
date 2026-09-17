"""Shared model building blocks.

UUIDMixin / TimeStampedMixin keep every table consistent without deep
inheritance. Note the `sa_type` choice: SQLAlchemy's cross-dialect `Uuid`
renders as native UUID on PostgreSQL and CHAR(32) on SQLite (used by a subset
of unit tests), so the same models run in tests and production.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Uuid
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


class UUIDMixin(SQLModel):
    # `sa_type` (not `sa_column`) is important in a mixin: a `sa_column` object
    # can only ever be attached to one table, so shared columns in mixins blow
    # up the moment a second table inherits them.
    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_type=Uuid(as_uuid=True),
        primary_key=True,
    )


class TimeStampedMixin(SQLModel):
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_type=DateTime(timezone=True),
        nullable=False,
    )
    updated_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"onupdate": utcnow},
    )
