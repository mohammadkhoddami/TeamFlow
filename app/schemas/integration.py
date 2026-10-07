"""Integration schemas (M3 #23)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field
from sqlmodel import SQLModel

ProviderLiteral = Literal["github", "gitlab", "bitbucket", "slack", "teams", "google_calendar"]

OUTBOUND_EVENTS = (
    "task.created",
    "task.updated",
    "task.completed",
    "comment.created",
    "member.joined",
)


class IntegrationCreate(SQLModel):
    provider: ProviderLiteral
    name: str = Field(min_length=1, max_length=128)
    # VCS: {"repository": "org/repo", "auto_transition": {"opened": "in_review"}}
    # Chat: {"webhook_url": "https://..."}
    # Google Calendar: no config required (feed token generated).
    config: dict = Field(default_factory=dict)
    events: list[str] = Field(default_factory=list, max_length=20)


class IntegrationUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    config: dict | None = None
    events: list[str] | None = Field(default=None, max_length=20)
    is_active: bool | None = None
    # VCS/gcal: generate a fresh secret/feed token.
    rotate_secret: bool = False


class IntegrationRead(SQLModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    provider: str
    name: str
    config: dict
    events: list[str]
    is_active: bool
    last_event_at: datetime | None
    # Convenience URLs/capabilities derived from the provider.
    webhook_path: str | None = None
    feed_path: str | None = None
    has_secret: bool = False
    # True when config.webhook_url is set; the value itself is never returned.
    has_webhook_url: bool = False
    created_at: datetime


class IntegrationCreated(IntegrationRead):
    # Plaintext secret/feed token, shown once at creation/rotation.
    secret: str | None = None


class IntegrationEventRead(SQLModel):
    id: uuid.UUID
    integration_id: uuid.UUID
    direction: str
    event_type: str
    status: str
    detail: str | None
    data: dict | None
    created_at: datetime
