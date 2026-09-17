"""Task model with link tables for labels (M2M) and watchers (M2M).

Tenant fields: every task carries organization_id *and* project_id; queries
filter on organization_id first so the tenant boundary is enforced even if a
project ID from another org is guessed. FKs are ON DELETE CASCADE so a project
or org delete is a single DB statement, not an ORM traversal (which would be
slow and awkward in async).

Relationships use eager strategies (`joined` for many-to-one, `selectin` for
collections) so list endpoints never emit N+1 queries from lazy loads.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy import Uuid as SAUuid
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import TimeStampedMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.label import Label
    from app.models.user import User


class TaskStatus:
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    DONE = "done"

    ALL = (TODO, IN_PROGRESS, IN_REVIEW, DONE)


class TaskPriority:
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"

    ALL = (LOW, MEDIUM, HIGH, URGENT)


class TaskLabelLink(SQLModel, table=True):
    __tablename__ = "task_labels"
    __table_args__ = (UniqueConstraint("task_id", "label_id", name="uq_task_label"),)

    task_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("tasks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    label_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("labels.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )


class TaskWatcherLink(SQLModel, table=True):
    __tablename__ = "task_watchers"
    __table_args__ = (UniqueConstraint("task_id", "user_id", name="uq_task_watcher"),)

    task_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("tasks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    user_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )


class Task(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_org_project_status", "organization_id", "project_id", "status"),
        Index("ix_tasks_org_status", "organization_id", "status"),
        Index("ix_tasks_assignee", "assignee_id"),
        Index("ix_tasks_due_date", "due_date"),
        Index("ix_tasks_created", "created_at"),
    )

    organization_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    project_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    title: str = Field(sa_column=Column(String(255), nullable=False))
    description: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    status: str = Field(sa_column=Column(String(16), nullable=False))
    priority: str = Field(sa_column=Column(String(16), nullable=False))
    due_date: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    created_by_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    assignee_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    completed_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

    # Two FKs point from tasks to users (creator/assignee); without explicit
    # foreign_keys SQLAlchemy cannot infer the join for either relationship.
    assignee: Optional["User"] = Relationship(
        sa_relationship_kwargs={"lazy": "joined", "foreign_keys": "Task.assignee_id"}
    )
    creator: Optional["User"] = Relationship(
        sa_relationship_kwargs={"lazy": "joined", "foreign_keys": "Task.created_by_id"}
    )
    labels: list["Label"] = Relationship(
        link_model=TaskLabelLink, sa_relationship_kwargs={"lazy": "selectin"}
    )
    watchers: list["User"] = Relationship(
        link_model=TaskWatcherLink, sa_relationship_kwargs={"lazy": "selectin"}
    )

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("status", TaskStatus.TODO)
        kwargs.setdefault("priority", TaskPriority.MEDIUM)
        super().__init__(**kwargs)
