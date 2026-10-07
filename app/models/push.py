"""Web push subscriptions (M4 notifications).

One row per browser/device endpoint; `keys` holds the client's
``{"p256dh", "auth"}`` encryption keys.
"""

import uuid

from sqlalchemy import JSON, Column, ForeignKey, String
from sqlalchemy import Uuid as SAUuid
from sqlmodel import Field, SQLModel

from app.models.base import TimeStampedMixin, UUIDMixin


class PushSubscription(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "push_subscriptions"

    user_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    endpoint: str = Field(
        sa_column=Column(String(512), nullable=False, unique=True, index=True)
    )
    keys: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    user_agent: str | None = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )
