"""Notification preference schemas."""

from typing import Literal

from sqlmodel import SQLModel

DigestLiteral = Literal["immediate", "daily", "weekly", "off"]


class NotificationPreferenceBase(SQLModel):
    email_enabled: bool = True
    assigned: bool = True
    mentioned: bool = True
    comments: bool = False
    due: bool = True
    digest: DigestLiteral = "immediate"


class NotificationPreferenceUpdate(SQLModel):
    email_enabled: bool | None = None
    assigned: bool | None = None
    mentioned: bool | None = None
    comments: bool | None = None
    due: bool | None = None
    digest: DigestLiteral | None = None


class NotificationPreferenceRead(NotificationPreferenceBase):
    unsubscribe_url: str | None = None
