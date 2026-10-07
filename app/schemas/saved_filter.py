"""Saved filter schemas (TeamQL queries persisted per org/project)."""

import uuid
from datetime import datetime

from pydantic import Field
from sqlmodel import SQLModel


class SavedFilterCreate(SQLModel):
    name: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=2_000)
    project_id: uuid.UUID | None = None
    is_shared: bool = False


class SavedFilterUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    query: str | None = Field(default=None, min_length=1, max_length=2_000)
    is_shared: bool | None = None


class SavedFilterRead(SQLModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    project_id: uuid.UUID | None
    owner_id: uuid.UUID
    name: str
    query: str
    is_shared: bool
    created_at: datetime
    updated_at: datetime | None
