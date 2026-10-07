"""Per-user email notification preferences.

One row per user (created lazily with defaults). The matrix mirrors the
notification types that can be delivered by email:
`assigned`, `mentioned`, `comments`, `due`. `digest` controls cadence:
`immediate` (send per event), `daily`, `weekly`, or `off`.

`unsubscribe_token` is a stable random token embedded in every email footer so
recipients can unsubscribe (or manage prefs) without logging in.
"""

import secrets
import uuid

from sqlalchemy import Boolean, Column, ForeignKey, String
from sqlalchemy import Uuid as SAUuid
from sqlmodel import Field, SQLModel

from app.models.base import TimeStampedMixin, UUIDMixin


class DigestCadence:
    IMMEDIATE = "immediate"
    DAILY = "daily"
    WEEKLY = "weekly"
    OFF = "off"

    ALL = (IMMEDIATE, DAILY, WEEKLY, OFF)


def generate_unsubscribe_token() -> str:
    return secrets.token_urlsafe(32)


class NotificationPreference(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "notification_preferences"

    user_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
            index=True,
        ),
    )
    email_enabled: bool = Field(sa_column=Column(Boolean, nullable=False))
    assigned: bool = Field(sa_column=Column(Boolean, nullable=False))
    mentioned: bool = Field(sa_column=Column(Boolean, nullable=False))
    comments: bool = Field(sa_column=Column(Boolean, nullable=False))
    due: bool = Field(sa_column=Column(Boolean, nullable=False))
    digest: str = Field(sa_column=Column(String(16), nullable=False))
    unsubscribe_token: str = Field(
        default_factory=generate_unsubscribe_token,
        sa_column=Column(String(64), nullable=False, unique=True, index=True),
    )

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("email_enabled", True)
        kwargs.setdefault("assigned", True)
        kwargs.setdefault("mentioned", True)
        kwargs.setdefault("comments", False)
        kwargs.setdefault("due", True)
        kwargs.setdefault("digest", DigestCadence.IMMEDIATE)
        super().__init__(**kwargs)

    def allows(self, notification_type: str) -> bool:
        if not self.email_enabled or self.digest == DigestCadence.OFF:
            return False
        if self.digest != DigestCadence.IMMEDIATE:
            # Digest cadences are sent by the scheduled digest job, not inline.
            return False
        mapping = {
            "task_assigned": self.assigned,
            "mention": self.mentioned,
            "comment_created": self.comments,
            "task_completed": self.comments,
            "task_due_soon": self.due,
        }
        return mapping.get(notification_type, False)
