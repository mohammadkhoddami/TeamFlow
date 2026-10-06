"""API tokens, service accounts and OAuth app registrations (M3 #24).

Three related principals:
  - ApiToken        personal access token; acts as its owning user
  - ServiceAccount  non-human identity for automations/CI; backed by a shadow
                    User row + membership so the existing authorization stack
                    (org/project access checks) works unchanged
  - OAuthApp        registered client for machine-to-machine OAuth2
                    (client_credentials grant); tokens persisted hashed

Secrets are never stored in plaintext: tokens and client secrets are hashed
with SHA-256 (they are high-entropy random values, so a fast hash is
appropriate; bcrypt is reserved for low-entropy human passwords).
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy import Uuid as SAUuid
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import TimeStampedMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.user import User


class ServiceAccount(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "service_accounts"
    __table_args__ = (
        Index("ix_service_accounts_org", "organization_id"),
    )

    organization_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    # Shadow user backing this principal (same authorization stack, no login).
    user_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
    )
    name: str = Field(sa_column=Column(String(128), nullable=False))
    description: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    scopes: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    is_active: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
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
    user: Optional["User"] = Relationship(
        sa_relationship_kwargs={"lazy": "joined", "foreign_keys": "ServiceAccount.user_id"}
    )


class ApiToken(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "api_tokens"
    __table_args__ = (
        Index("ix_api_tokens_org", "organization_id"),
        Index("ix_api_tokens_user", "user_id"),
    )

    organization_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    # Owning user; service-account tokens point at the account's shadow user.
    user_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    service_account_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("service_accounts.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    name: str = Field(sa_column=Column(String(128), nullable=False))
    # Display-only prefix (e.g. "tf_ab12cd34"); the full secret is shown once.
    token_prefix: str = Field(sa_column=Column(String(24), nullable=False))
    token_hash: str = Field(
        sa_column=Column(String(64), nullable=False, unique=True, index=True)
    )
    scopes: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    # Requests-per-minute budget for this token (NULL = no token-specific cap).
    rate_limit_per_minute: int | None = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    expires_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    last_used_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    usage_count: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
    is_active: bool = Field(
        default=True, sa_column=Column(Boolean, nullable=False, server_default="true")
    )
    revoked_at: datetime | None = Field(
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
    user: Optional["User"] = Relationship(
        sa_relationship_kwargs={"lazy": "joined", "foreign_keys": "ApiToken.user_id"}
    )
    service_account: Optional["ServiceAccount"] = Relationship(
        sa_relationship_kwargs={"lazy": "joined"}
    )


class OAuthApp(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "oauth_apps"
    __table_args__ = (Index("ix_oauth_apps_org", "organization_id"),)

    organization_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    name: str = Field(sa_column=Column(String(128), nullable=False))
    description: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    client_id: str = Field(
        sa_column=Column(String(64), nullable=False, unique=True, index=True)
    )
    client_secret_hash: str = Field(sa_column=Column(String(64), nullable=False))
    redirect_uris: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    scopes: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    is_active: bool = Field(
        default=True, sa_column=Column(Boolean, nullable=False, server_default="true")
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

    organization: Optional["Organization"] = Relationship()


class OAuthToken(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "oauth_tokens"
    __table_args__ = (Index("ix_oauth_tokens_app", "app_id"),)

    organization_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    app_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("oauth_apps.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    token_hash: str = Field(
        sa_column=Column(String(64), nullable=False, unique=True, index=True)
    )
    scopes: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    is_active: bool = Field(
        default=True, sa_column=Column(Boolean, nullable=False, server_default="true")
    )

    app: Optional["OAuthApp"] = Relationship(
        sa_relationship_kwargs={"lazy": "joined"}
    )
