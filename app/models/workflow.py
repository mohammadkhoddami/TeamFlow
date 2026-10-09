"""Per-project workflow statuses and boards.

The default workflow is the classic four-column flow
(`todo -> in_progress -> in_review -> done`); projects that never customize it
have no `WorkflowStatus` rows and the service synthesizes the defaults. Once a
project saves a workflow, task status validation and transitions follow those
rows.

`Board` adds multiple saved views per project: a name, an optional TeamQL
filter, the visible workflow columns, and the swimlane grouping.
"""

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Uuid as SAUuid
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import TimeStampedMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.project import Project


class SwimlaneBy:
    NONE = "none"
    ASSIGNEE = "assignee"
    PRIORITY = "priority"
    LABEL = "label"

    ALL = (NONE, ASSIGNEE, PRIORITY, LABEL)


class WorkflowStatus(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "workflow_statuses"
    __table_args__ = (
        UniqueConstraint("project_id", "key", name="uq_workflow_status_project_key"),
        Index("ix_workflow_statuses_project_position", "project_id", "position"),
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
    key: str = Field(sa_column=Column(String(32), nullable=False))
    name: str = Field(sa_column=Column(String(64), nullable=False))
    # Category drives completed_at, reports and dashboard buckets. Must be one
    # of the four canonical categories so aggregates stay comparable.
    category: str = Field(sa_column=Column(String(16), nullable=False))
    position: int = Field(sa_column=Column(Integer, nullable=False, server_default="0"))
    # None = no limit. Enforced only when the project sets wip_enforced.
    wip_limit: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    # Allowed next status keys; empty list = terminal.
    transitions: list[str] = Field(sa_column=Column(JSON, nullable=False))

    organization: Optional["Organization"] = Relationship()
    project: Optional["Project"] = Relationship()

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("position", 0)
        kwargs.setdefault("transitions", [])
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return f"{self.key} ({self.category})"


class Board(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "boards"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_boards_project_name"),
        Index("ix_boards_project", "project_id"),
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
        ),
    )
    name: str = Field(sa_column=Column(String(128), nullable=False))
    is_default: bool = Field(sa_column=Column(Boolean, nullable=False))
    swimlane_by: str = Field(
        sa_column=Column(String(16), nullable=False, server_default="none")
    )
    filter_query: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    # Subset/order of workflow status keys; NULL = all statuses.
    columns: list[str] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    # Issue types shown on the board (epic/story/task); NULL = all types.
    issue_types: list[str] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
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

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("is_default", False)
        kwargs.setdefault("swimlane_by", SwimlaneBy.NONE)
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return self.name
