"""Webhook schemas. The signing secret is returned exactly once at creation."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import AnyHttpUrl, Field
from sqlmodel import SQLModel

WebhookEventLiteral = Literal[
    "task.created", "task.updated", "task.completed", "comment.created", "member.joined"
]


class WebhookCreate(SQLModel):
    url: AnyHttpUrl
    events: list[WebhookEventLiteral] = Field(min_length=1, max_length=10)
    description: str | None = Field(default=None, max_length=255)


class WebhookUpdate(SQLModel):
    url: AnyHttpUrl | None = None
    events: list[WebhookEventLiteral] | None = Field(default=None, min_length=1, max_length=10)
    is_active: bool | None = None
    description: str | None = Field(default=None, max_length=255)


class WebhookRead(SQLModel):
    id: uuid.UUID
    url: str
    events: list[str]
    is_active: bool
    description: str | None
    created_at: datetime


class WebhookCreated(SQLModel):
    """First response includes the plaintext secret; it is not retrievable later."""

    id: uuid.UUID
    url: str
    events: list[str]
    is_active: bool
    description: str | None
    secret: str
    created_at: datetime


class WebhookDeliveryRead(SQLModel):
    id: uuid.UUID
    webhook_id: uuid.UUID
    event: str
    status: str
    attempts: int
    response_status: int | None
    last_error: str | None
    delivered_at: datetime | None
    created_at: datetime
