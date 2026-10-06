"""Release/version model (M3 #16).

A release is a dated scope bucket inside a project. Tasks link to releases via
`Task.release_id`; the roadmap view groups work by epic and overlays releases.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy import Uuid as SAUuid
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import TimeStampedMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.project import Project
    from app.models.user import User


class ReleaseStatus:
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    RELEASED = "released"
    CANCELLED = "cancelled"

    ALL = (PLANNED, IN_PROGRESS, RELEASED, CANCELLED)


class Release(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "releases"
    __table_args__ = (
        Index("ix_releases_org_project", "organization_id", "project_id"),
        Index("ix_releases_project_date", "project_id", "release_date"),
        UniqueConstraint("project_id", "name", name="uq_releases_project_name"),
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
    name: str = Field(sa_column=Column(String(128), nullable=False))
    description: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    version: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    status: str = Field(
        default=ReleaseStatus.PLANNED,
        sa_column=Column(String(16), nullable=False, server_default="planned"),
    )
    start_date: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    release_date: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    released_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
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
