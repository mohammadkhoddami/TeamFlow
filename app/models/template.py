"""Project and task templates.

Built-in templates (Scrum, Kanban, Bug triage) live in code
(`app.services.templates`); `ProjectTemplate` stores user-saved snapshots of a
project's workflow, labels, boards, custom fields and sample hierarchy.
"""

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import JSON, Column, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy import Uuid as SAUuid
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import TimeStampedMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.project import Project


class ProjectTemplate(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "project_templates"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_project_template_name"),
    )

    organization_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    name: str = Field(sa_column=Column(String(128), nullable=False))
    description: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    config: dict = Field(sa_column=Column(JSON, nullable=False))
    created_by_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    organization: Optional["Organization"] = Relationship()

    def __repr__(self) -> str:
        return self.name


class TaskTemplate(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "task_templates"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_task_template_name"),
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
    name: str = Field(sa_column=Column(String(128), nullable=False))
    title: str = Field(sa_column=Column(String(255), nullable=False))
    description: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    priority: str = Field(sa_column=Column(String(16), nullable=False))
    type: str = Field(sa_column=Column(String(16), nullable=False))
    estimate: float | None = Field(default=None, sa_column=Column(Float, nullable=True))
    label_ids: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    checklist: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )

    organization: Optional["Organization"] = Relationship()
    project: Optional["Project"] = Relationship()

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("priority", "medium")
        kwargs.setdefault("type", "task")
        kwargs.setdefault("label_ids", [])
        kwargs.setdefault("checklist", [])
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return self.name
