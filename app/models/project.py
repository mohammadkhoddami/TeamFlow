"""Project model."""

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
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
    from app.models.user import User


class ProjectStatus:
    ACTIVE = "active"
    ARCHIVED = "archived"

    ALL = (ACTIVE, ARCHIVED)


class EstimationUnit:
    """Configurable estimation field for the project.

    `points` (default) and `hours` are numeric per-task estimates; `none`
    hides estimation UI/aggregation but keeps stored values.
    """

    NONE = "none"
    POINTS = "points"
    HOURS = "hours"

    ALL = (NONE, POINTS, HOURS)


class Project(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "projects"
    __table_args__ = (
        Index("ix_projects_org_status", "organization_id", "status"),
        UniqueConstraint("organization_id", "key", name="uq_projects_org_key"),
    )

    organization_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    name: str = Field(sa_column=Column(String(255), nullable=False))
    description: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    status: str = Field(sa_column=Column(String(16), nullable=False))
    # Human-readable issue key prefix, e.g. "TEAM" -> TEAM-123. Assigned on
    # create from the name and editable by managers.
    key: str | None = Field(
        default=None, sa_column=Column(String(16), nullable=True)
    )
    # Atomic per-project counter backing issue keys (UPDATE ... +1 RETURNING).
    issue_counter: int = Field(sa_column=Column(Integer, nullable=False, server_default="0"))
    estimation_unit: str = Field(
        sa_column=Column(String(16), nullable=False, server_default="points")
    )
    # When true, moving tasks into a workflow status at its WIP limit is rejected.
    wip_enforced: bool = Field(
        sa_column=Column(Boolean, nullable=False, server_default="false")
    )
    visibility: str = Field(
        default="workspace",
        sa_column=Column(String(16), nullable=False, server_default="workspace"),
    )
    owner_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    organization: Optional["Organization"] = Relationship()
    owner: Optional["User"] = Relationship()

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("status", ProjectStatus.ACTIVE)
        kwargs.setdefault("issue_counter", 0)
        kwargs.setdefault("estimation_unit", EstimationUnit.POINTS)
        kwargs.setdefault("wip_enforced", False)
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return self.name

    def __str__(self) -> str:
        return self.__repr__()
