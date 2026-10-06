"""Task links, dependencies and status history.

Links are stored once with a canonical direction:
  - `blocks`:      from blocks to (inverse: "is blocked by")
  - `relates_to`, `duplicates`, `clones`: symmetric
`is_blocked` is derived: a task is blocked when another task `blocks` it and
that blocker is not done.

Status history is appended on every transition (including bulk moves) and
powers cumulative-flow, cycle-time and lead-time reports.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy import Uuid as SAUuid
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import TimeStampedMixin, UUIDMixin, utcnow

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.task import Task
    from app.models.user import User


class TaskLinkType:
    BLOCKS = "blocks"
    RELATES_TO = "relates_to"
    DUPLICATES = "duplicates"
    CLONES = "clones"

    ALL = (BLOCKS, RELATES_TO, DUPLICATES, CLONES)


class TaskLink(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "task_links"
    __table_args__ = (
        UniqueConstraint(
            "from_task_id", "to_task_id", "link_type", name="uq_task_link"
        ),
        Index("ix_task_links_from", "from_task_id"),
        Index("ix_task_links_to", "to_task_id"),
    )

    organization_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    from_task_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    to_task_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    link_type: str = Field(sa_column=Column(String(16), nullable=False))
    created_by_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    organization: Optional["Organization"] = Relationship()
    from_task: Optional["Task"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "TaskLink.from_task_id"}
    )
    to_task: Optional["Task"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "TaskLink.to_task_id"}
    )

    def __repr__(self) -> str:
        return f"{self.from_task_id} {self.link_type} {self.to_task_id}"


class TaskStatusHistory(UUIDMixin, SQLModel, table=True):
    __tablename__ = "task_status_history"
    __table_args__ = (
        Index("ix_task_status_history_task_changed", "task_id", "changed_at"),
        Index("ix_task_status_history_org_changed", "organization_id", "changed_at"),
    )

    organization_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    task_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    from_status: str = Field(sa_column=Column(String(32), nullable=False))
    to_status: str = Field(sa_column=Column(String(32), nullable=False))
    from_category: str = Field(sa_column=Column(String(16), nullable=False))
    to_category: str = Field(sa_column=Column(String(16), nullable=False))
    changed_by_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    changed_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    changed_by: Optional["User"] = Relationship()
