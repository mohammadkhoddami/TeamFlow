"""MFA credentials (M4 enterprise security).

One TOTP credential per user: the shared secret, the current enabled flag,
and hashed/one-time recovery codes stored as a JSON list.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey
from sqlalchemy import Uuid as SAUuid
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import TimeStampedMixin, UUIDMixin
from app.models.types import EncryptedString

if TYPE_CHECKING:
    from app.models.user import User


class MfaCredential(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "mfa_credentials"

    user_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
            index=True,
        ),
    )
    secret: str = Field(sa_column=Column(EncryptedString, nullable=False))
    is_enabled: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    recovery_codes: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    confirmed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    last_used_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    user: Optional["User"] = Relationship(sa_relationship_kwargs={"lazy": "joined"})
