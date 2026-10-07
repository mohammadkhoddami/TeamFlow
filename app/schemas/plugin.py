"""Plugin directory / installation schemas (M4 ecosystem)."""

import uuid
from datetime import datetime

from pydantic import Field
from sqlmodel import SQLModel


class PluginDirectoryEntry(SQLModel):
    id: str
    name: str
    description: str
    author: str
    homepage: str
    events: list[str]
    scopes: list[str]
    installed: bool = False


class PluginInstall(SQLModel):
    catalog_id: str | None = Field(default=None, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    homepage: str | None = Field(default=None, max_length=512)
    author: str | None = Field(default=None, max_length=128)
    webhook_url: str = Field(min_length=8, max_length=512)
    # None (not []) so catalog defaults apply when the client omits events.
    events: list[str] | None = Field(default=None, max_length=64)
    scopes: list[str] | None = Field(default=None, max_length=64)
    manifest: dict | None = None


class PluginUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    webhook_url: str | None = Field(default=None, min_length=8, max_length=512)
    events: list[str] | None = Field(default=None, max_length=64)
    is_active: bool | None = None


class PluginRead(SQLModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    description: str | None
    manifest: dict
    webhook_url: str | None
    events: list[str]
    scopes: list[str]
    is_active: bool
    installed_by_id: uuid.UUID | None = None
    created_at: datetime


class PluginCreated(PluginRead):
    # Returned exactly once; the stored value is the signing secret.
    secret: str | None = None
