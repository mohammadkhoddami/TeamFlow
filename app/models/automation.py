"""Automation rules and their execution log (M3 #14).

A rule = trigger + conditions + actions. The engine
(`app/services/automations.py`) evaluates rules on task/comment events and a
Celery beat job runs `schedule` triggers. Every evaluation is persisted to
`automation_executions` so non-engineers can see what ran and why.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy import Uuid as SAUuid
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import TimeStampedMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.project import Project
    from app.models.task import Task
    from app.models.user import User


class AutomationTrigger:
    TASK_CREATED = "task_created"
    TASK_UPDATED = "task_updated"
    STATUS_CHANGED = "status_changed"
    COMMENT_CREATED = "comment_created"
    SCHEDULE = "schedule"

    ALL = (TASK_CREATED, TASK_UPDATED, STATUS_CHANGED, COMMENT_CREATED, SCHEDULE)


class AutomationExecutionStatus:
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"

    ALL = (SUCCESS, FAILED, SKIPPED)


class AutomationRule(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "automation_rules"
    __table_args__ = (
        Index("ix_automation_rules_org", "organization_id"),
        Index("ix_automation_rules_project", "project_id"),
        Index("ix_automation_rules_trigger", "organization_id", "trigger_type"),
    )

    organization_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    # NULL = org-wide rule; otherwise scoped to one project.
    project_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    name: str = Field(sa_column=Column(String(128), nullable=False))
    description: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    is_active: bool = Field(
        default=True, sa_column=Column(Boolean, nullable=False, server_default="true")
    )
    trigger_type: str = Field(sa_column=Column(String(32), nullable=False))
    # e.g. {"to_status": "in_review"} or {"interval": "daily", "at": "09:00"}.
    trigger_config: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    # e.g. [{"field": "priority", "op": "equals", "value": "urgent"}]
    conditions: list | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    # e.g. [{"type": "assign", "assignee": "<uuid>"}, {"type": "comment", ...}]
    actions: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    last_run_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    run_count: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
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
    project: Optional["Project"] = Relationship()
    created_by: Optional["User"] = Relationship()


class AutomationExecution(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "automation_executions"
    __table_args__ = (
        Index("ix_automation_executions_rule", "rule_id", "created_at"),
        Index("ix_automation_executions_org", "organization_id", "created_at"),
    )

    organization_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    rule_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("automation_rules.id", ondelete="CASCADE"),
            nullable=False,
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
    trigger_event: str = Field(sa_column=Column(String(32), nullable=False))
    status: str = Field(sa_column=Column(String(16), nullable=False))
    actions_log: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    error: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    actor_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    rule: Optional["AutomationRule"] = Relationship(
        sa_relationship_kwargs={"lazy": "joined"}
    )
    task: Optional["Task"] = Relationship()
