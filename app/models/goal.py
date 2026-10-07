"""Organization goals and their task links (M4).

A `Goal` is an org-level objective with a lifecycle (active/achieved/
cancelled); `GoalLink` attaches tasks to a goal so progress can be rolled up.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy import Uuid as SAUuid
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import TimeStampedMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.task import Task


class Goal(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "goals"
    __table_args__ = (Index("ix_goals_org_status", "organization_id", "status"),)

    organization_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    name: str = Field(sa_column=Column(String(128), nullable=False))
    description: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    status: str = Field(
        default="active",
        sa_column=Column(String(16), nullable=False, server_default="active"),
    )
    due_date: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    owner_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    created_by_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


class GoalLink(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "goal_links"
    __table_args__ = (
        UniqueConstraint("goal_id", "task_id", name="uq_goal_link"),
        Index("ix_goal_links_task", "task_id"),
    )

    goal_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("goals.id", ondelete="CASCADE"),
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

    goal: Optional["Goal"] = Relationship()
    task: Optional["Task"] = Relationship()
