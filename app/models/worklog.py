"""Time tracking: worklog entries per task and user.

`minutes` keeps billing arithmetic exact; `started_at` supports timesheets.
Task `actual_estimate` is kept in sync with the total logged time (hours).
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, Text
from sqlalchemy import Uuid as SAUuid
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import TimeStampedMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.task import Task
    from app.models.user import User


class Worklog(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "worklogs"
    __table_args__ = (
        Index("ix_worklogs_task_started", "task_id", "started_at"),
        Index("ix_worklogs_org_started", "organization_id", "started_at"),
        Index("ix_worklogs_user_started", "user_id", "started_at"),
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
    user_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    minutes: int = Field(sa_column=Column(Integer, nullable=False))
    started_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    description: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    organization: Optional["Organization"] = Relationship()
    task: Optional["Task"] = Relationship()
    user: Optional["User"] = Relationship(sa_relationship_kwargs={"lazy": "joined"})

    def __repr__(self) -> str:
        return f"{self.minutes}m on {self.task_id}"
