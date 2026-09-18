"""Project model."""

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, ForeignKey, Index, String, Text
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


class Project(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "projects"
    __table_args__ = (Index("ix_projects_org_status", "organization_id", "status"),)

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
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return self.name

    def __str__(self) -> str:
        return self.__repr__()
