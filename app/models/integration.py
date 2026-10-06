"""Third-party integrations (M3 #23).

`Integration` holds a provider connection:
  - github / gitlab / bitbucket: inbound webhooks (branch/commit/PR -> task
    links + auto-transition) verified with `secret`
  - slack / teams: outbound notifications to an incoming webhook URL
  - google_calendar: ICS feed token so Google Calendar can subscribe

`IntegrationEvent` is the per-integration delivery/receipt log.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy import Uuid as SAUuid
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import TimeStampedMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.user import User


class IntegrationProvider:
    GITHUB = "github"
    GITLAB = "gitlab"
    BITBUCKET = "bitbucket"
    SLACK = "slack"
    TEAMS = "teams"
    GOOGLE_CALENDAR = "google_calendar"

    ALL = (GITHUB, GITLAB, BITBUCKET, SLACK, TEAMS, GOOGLE_CALENDAR)
    VCS = (GITHUB, GITLAB, BITBUCKET)
    CHAT = (SLACK, TEAMS)


class IntegrationEventStatus:
    RECEIVED = "received"
    DELIVERED = "delivered"
    FAILED = "failed"
    IGNORED = "ignored"

    ALL = (RECEIVED, DELIVERED, FAILED, IGNORED)


class Integration(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "integrations"
    __table_args__ = (
        UniqueConstraint("organization_id", "provider", "name", name="uq_integration_name"),
        Index("ix_integrations_org_provider", "organization_id", "provider"),
    )

    organization_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    provider: str = Field(sa_column=Column(String(32), nullable=False))
    name: str = Field(sa_column=Column(String(128), nullable=False))
    # Non-secret provider settings (chat webhook URL, repo slug, ...).
    config: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    # Inbound webhook secret / ICS feed token (shown once at creation).
    secret: str | None = Field(default=None, sa_column=Column(String(128), nullable=True))
    # Outbound event filter for chat providers (task.created, comment.created, ...).
    events: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    is_active: bool = Field(
        default=True, sa_column=Column(Boolean, nullable=False, server_default="true")
    )
    last_event_at: datetime | None = Field(
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

    organization: Optional["Organization"] = Relationship(
        sa_relationship_kwargs={"lazy": "joined"}
    )
    created_by: Optional["User"] = Relationship()


class IntegrationEvent(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "integration_events"
    __table_args__ = (
        Index("ix_integration_events_integration", "integration_id", "created_at"),
        Index("ix_integration_events_org", "organization_id", "created_at"),
    )

    organization_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    integration_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("integrations.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    direction: str = Field(
        default="inbound",
        sa_column=Column(String(8), nullable=False, server_default="inbound"),
    )
    event_type: str = Field(sa_column=Column(String(64), nullable=False))
    status: str = Field(
        default=IntegrationEventStatus.RECEIVED,
        sa_column=Column(String(16), nullable=False, server_default="received"),
    )
    detail: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    data: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))

    integration: Optional["Integration"] = Relationship(
        sa_relationship_kwargs={"lazy": "joined"}
    )
