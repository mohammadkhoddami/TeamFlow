"""Saved dashboards (M4).

A dashboard stores an ordered list of widgets; each widget is a dict shaped
``{"id", "type", "title", "config"}``. Organization-scoped, optionally
pinned to one project.
"""

import uuid

from sqlalchemy import JSON, Boolean, Column, ForeignKey, String, UniqueConstraint
from sqlalchemy import Uuid as SAUuid
from sqlmodel import Field, SQLModel

from app.models.base import TimeStampedMixin, UUIDMixin


class Dashboard(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "dashboards"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_dashboard_name"),
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
    widgets: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    is_default: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    created_by_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
