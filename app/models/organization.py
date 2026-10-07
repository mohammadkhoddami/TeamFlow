"""Organization, Membership, and Invitation models.

`Organization` is the tenant root. Every tenant-owned row carries
`organization_id` (FK ON DELETE CASCADE) so tenant isolation is one indexed
filter and org deletion is a single statement handled by the database.

Membership is the join table between users and organizations and holds the
per-org role. A user's global attributes are deliberately *not* authoritative
inside an organization.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy import Uuid as SAUuid
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import TimeStampedMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.user import User


class MembershipRole:
    """String constants instead of an Enum for simpler DB serialization."""

    OWNER = "owner"
    ADMIN = "admin"
    MANAGER = "manager"
    MEMBER = "member"

    ALL = (OWNER, ADMIN, MANAGER, MEMBER)
    # Roles that automated provisioning (SSO/SCIM) may assign. Ownership must
    # be a deliberate, human action, never a side effect of a directory sync.
    ASSIGNABLE = (ADMIN, MANAGER, MEMBER)


class Organization(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "organizations"

    name: str = Field(sa_column=Column(String(255), nullable=False))
    slug: str = Field(
        sa_column=Column(String(255), unique=True, index=True, nullable=False)
    )
    is_active: bool = Field(sa_column=Column(Boolean, nullable=False))
    accent_color: str | None = Field(
        default=None, sa_column=Column(String(16), nullable=True)
    )
    audit_retention_days: int | None = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    created_by_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    created_by: Optional["User"] = Relationship()

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("is_active", True)
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return f"{self.name} ({self.slug})"

    def __str__(self) -> str:
        return self.__repr__()


class Membership(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "organization_id", name="uq_membership_user_org"),
    )

    user_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    organization_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    role: str = Field(sa_column=Column(String(32), nullable=False))
    is_active: bool = Field(sa_column=Column(Boolean, nullable=False))
    custom_role_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("custom_roles.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    user: "User" = Relationship(sa_relationship_kwargs={"lazy": "joined"})
    organization: Optional["Organization"] = Relationship()

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("role", MembershipRole.MEMBER)
        kwargs.setdefault("is_active", True)
        super().__init__(**kwargs)


class InvitationStatus:
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    REVOKED = "revoked"
    EXPIRED = "expired"

    ALL = (PENDING, ACCEPTED, DECLINED, REVOKED, EXPIRED)


class Invitation(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "invitations"
    __table_args__ = (Index("ix_invitations_org_email", "organization_id", "email"),)

    email: str = Field(
        sa_column=Column(String(255), index=True, nullable=False)
    )
    organization_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    role: str = Field(sa_column=Column(String(32), nullable=False))
    status: str = Field(sa_column=Column(String(32), nullable=False))
    expires_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    invited_by_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    organization: Optional["Organization"] = Relationship()
    invited_by: Optional["User"] = Relationship()

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("role", MembershipRole.MEMBER)
        kwargs.setdefault("status", InvitationStatus.PENDING)
        super().__init__(**kwargs)
