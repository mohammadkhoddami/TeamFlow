"""Checklist items and additional task assignees.

`Task.assignee_id` remains the primary assignee for backwards compatibility;
`TaskAssignee` adds role-bearing assignees (assignee/approver).
"""

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy import Uuid as SAUuid
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import TimeStampedMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.task import Task
    from app.models.user import User


class AssigneeRole:
    ASSIGNEE = "assignee"
    APPROVER = "approver"

    ALL = (ASSIGNEE, APPROVER)


class TaskAssignee(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "task_assignees"
    __table_args__ = (
        UniqueConstraint("task_id", "user_id", name="uq_task_assignee"),
        Index("ix_task_assignees_user", "user_id"),
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
            index=True,
        ),
    )
    user_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    role: str = Field(sa_column=Column(String(16), nullable=False))

    user: Optional["User"] = Relationship(sa_relationship_kwargs={"lazy": "joined"})

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("role", AssigneeRole.ASSIGNEE)
        super().__init__(**kwargs)


class ChecklistItem(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "checklist_items"
    __table_args__ = (Index("ix_checklist_items_task_position", "task_id", "position"),)

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
    text: str = Field(sa_column=Column(String(500), nullable=False))
    is_done: bool = Field(sa_column=Column(Boolean, nullable=False))
    position: int = Field(sa_column=Column(Integer, nullable=False, server_default="0"))
    created_by_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    task: Optional["Task"] = Relationship()

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("is_done", False)
        kwargs.setdefault("position", 0)
        super().__init__(**kwargs)
