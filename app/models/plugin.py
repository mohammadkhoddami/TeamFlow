"""Installed plugins (M4 ecosystem).

A plugin binds a catalog entry to an org with a webhook URL, the event types
it subscribes to, and the scopes it may act with. The signing `secret` is
shown once at install time.
"""

import uuid

from sqlalchemy import JSON, Boolean, Column, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy import Uuid as SAUuid
from sqlmodel import Field, SQLModel

from app.models.base import TimeStampedMixin, UUIDMixin


class Plugin(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "plugins"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_plugin_name"),
    )

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
    # Catalog metadata: catalog_id, homepage, author, permissions.
    manifest: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    webhook_url: str | None = Field(
        default=None, sa_column=Column(String(512), nullable=True)
    )
    events: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    scopes: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    secret: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    is_active: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    installed_by_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
