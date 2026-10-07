"""Custom org roles and per-project membership (M4 permissions).

`CustomRole` is an org-defined bundle of permissions; `ProjectMember` grants
a user an explicit role on one project (viewer/member/manager), independent
of their organization membership role.
"""

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import JSON, Column, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy import Uuid as SAUuid
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import TimeStampedMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.user import User


class CustomRole(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "custom_roles"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_custom_role_name"),
    )

    organization_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    name: str = Field(sa_column=Column(String(64), nullable=False))
    description: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    permissions: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    created_by_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


class ProjectMember(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_member"),
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
    user_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    role: str = Field(
        default="member",
        sa_column=Column(String(16), nullable=False, server_default="member"),
    )

    project: Optional["Project"] = Relationship(
        sa_relationship_kwargs={"lazy": "joined"}
    )
    user: Optional["User"] = Relationship(sa_relationship_kwargs={"lazy": "joined"})
