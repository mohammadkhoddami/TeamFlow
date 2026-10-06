"""Sprint (iteration) model.

A sprint is a project-scoped time box with a goal and a state machine:
`planned -> active -> completed`. Only one sprint may be active per project;
that invariant is enforced in the service layer with a partial-unique row lock
(see `app.services.sprints`).

Tasks join a sprint via `Task.sprint_id`; tasks with `sprint_id = NULL` are the
project backlog.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy import Uuid as SAUuid
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import TimeStampedMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.project import Project
    from app.models.user import User


class SprintState:
    PLANNED = "planned"
    ACTIVE = "active"
    COMPLETED = "completed"

    ALL = (PLANNED, ACTIVE, COMPLETED)


class Sprint(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "sprints"
    __table_args__ = (
        Index("ix_sprints_org_project_state", "organization_id", "project_id", "state"),
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
    name: str = Field(sa_column=Column(String(255), nullable=False))
    goal: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    state: str = Field(sa_column=Column(String(16), nullable=False))
    start_date: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    end_date: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    completed_at: datetime | None = Field(
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

    organization: Optional["Organization"] = Relationship()
    project: Optional["Project"] = Relationship()
    created_by: Optional["User"] = Relationship()

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("state", SprintState.PLANNED)
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return f"{self.name} ({self.state})"

    def __str__(self) -> str:
        return self.__repr__()
