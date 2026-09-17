"""Project model."""

import uuid

from sqlalchemy import Column, ForeignKey, Index, String, Text
from sqlalchemy import Uuid as SAUuid
from sqlmodel import Field, SQLModel

from app.models.base import TimeStampedMixin, UUIDMixin


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

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("status", ProjectStatus.ACTIVE)
        super().__init__(**kwargs)
