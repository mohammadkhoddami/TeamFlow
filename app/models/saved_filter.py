"""Saved filter model: persisted TeamQL queries.

A saved filter is organization-scoped; a NULL `project_id` means it applies to
the whole workspace, otherwise to one project. `is_shared` filters are visible
to every org member, while private ones are only listed for their owner.
"""

import uuid
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Uuid as SAUuid
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import TimeStampedMixin, UUIDMixin
from app.models.project import Project
from app.models.user import User


class SavedFilter(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "saved_filters"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "organization_id", "project_id", "name",
            name="uq_saved_filter_owner_name",
        ),
        Index("ix_saved_filters_org_project", "organization_id", "project_id"),
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
    owner_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    name: str = Field(sa_column=Column(String(128), nullable=False))
    query: str = Field(sa_column=Column(Text, nullable=False))
    is_shared: bool = Field(sa_column=Column(Boolean, nullable=False))

    owner: Optional["User"] = Relationship()
    project: Optional["Project"] = Relationship()

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("is_shared", False)
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return self.name

    def __str__(self) -> str:
        return self.__repr__()
