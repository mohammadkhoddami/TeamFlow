"""SSO (OIDC) configuration and SCIM provisioning tokens (M4 enterprise).

`SsoConfig` is one config per organization; `ScimToken` are the bearer
credentials SCIM clients use to sync users/groups, stored hashed.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, String
from sqlalchemy import Uuid as SAUuid
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import TimeStampedMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.organization import Organization


class SsoConfig(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "sso_configs"

    organization_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
            index=True,
        ),
    )
    provider: str = Field(
        default="oidc",
        sa_column=Column(String(16), nullable=False, server_default="oidc"),
    )
    issuer: str = Field(sa_column=Column(String(512), nullable=False))
    client_id: str = Field(sa_column=Column(String(255), nullable=False))
    client_secret: str = Field(sa_column=Column(String(512), nullable=False))
    scopes: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    is_enabled: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    auto_provision: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    default_role: str = Field(
        default="member",
        sa_column=Column(String(16), nullable=False, server_default="member"),
    )
    created_by_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    organization: Optional["Organization"] = Relationship(
        sa_relationship_kwargs={"lazy": "joined"}
    )


class ScimToken(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "scim_tokens"
    __table_args__ = (Index("ix_scim_tokens_org", "organization_id"),)

    organization_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    name: str = Field(sa_column=Column(String(128), nullable=False))
    token_hash: str = Field(
        sa_column=Column(String(64), nullable=False, unique=True, index=True)
    )
    is_active: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    last_used_at: datetime | None = Field(
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
