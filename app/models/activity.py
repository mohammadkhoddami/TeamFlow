"""Activity feed entries (M3 #21).

One row per user-visible event on a task/project. Written by the task, comment
and automation services; read back as per-task and per-project feeds.
"""

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import JSON, Column, ForeignKey, Index, String
from sqlalchemy import Uuid as SAUuid
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import TimeStampedMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.project import Project
    from app.models.task import Task
    from app.models.user import User


class ActivityVerb:
    TASK_CREATED = "task_created"
    TASK_UPDATED = "task_updated"
    STATUS_CHANGED = "status_changed"
    TASK_ASSIGNED = "task_assigned"
    TASK_COMPLETED = "task_completed"
    COMMENT_CREATED = "comment_created"
    REACTION_ADDED = "reaction_added"
    RELEASE_CREATED = "release_created"
    RELEASE_PUBLISHED = "release_published"
    AUTOMATION_RAN = "automation_ran"

    ALL = (
        TASK_CREATED,
        TASK_UPDATED,
        STATUS_CHANGED,
        TASK_ASSIGNED,
        TASK_COMPLETED,
        COMMENT_CREATED,
        REACTION_ADDED,
        RELEASE_CREATED,
        RELEASE_PUBLISHED,
        AUTOMATION_RAN,
    )


class Activity(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "activities"
    __table_args__ = (
        Index("ix_activities_org_created", "organization_id", "created_at"),
        Index("ix_activities_project_created", "project_id", "created_at"),
        Index("ix_activities_task_created", "task_id", "created_at"),
    )

    organization_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    project_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    task_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    # NULL actor = system (automation, import, recurrence).
    actor_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    verb: str = Field(sa_column=Column(String(32), nullable=False))
    summary: str = Field(sa_column=Column(String(255), nullable=False))
    data: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))

    organization: Optional["Organization"] = Relationship()
    project: Optional["Project"] = Relationship()
    task: Optional["Task"] = Relationship()
    actor: Optional["User"] = Relationship(sa_relationship_kwargs={"lazy": "joined"})
