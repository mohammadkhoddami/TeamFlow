"""Project schemas."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator
from sqlmodel import SQLModel

PROJECT_KEY_RE = r"^[A-Za-z][A-Za-z0-9]{1,9}$"


def _normalize_key(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip().upper()


class ProjectCreate(SQLModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10_000)
    key: str | None = Field(default=None, min_length=2, max_length=10, pattern=PROJECT_KEY_RE)
    estimation_unit: Literal["none", "points", "hours"] | None = None

    @field_validator("key")
    @classmethod
    def normalize_key(cls, value: str | None) -> str | None:
        return _normalize_key(value)


class ProjectUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10_000)
    status: Literal["active", "archived"] | None = None
    key: str | None = Field(default=None, min_length=2, max_length=10, pattern=PROJECT_KEY_RE)
    estimation_unit: Literal["none", "points", "hours"] | None = None
    visibility: Literal["workspace", "private"] | None = None

    @field_validator("key")
    @classmethod
    def normalize_key(cls, value: str | None) -> str | None:
        return _normalize_key(value)


class ProjectRead(SQLModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    description: str | None
    status: str
    key: str | None = None
    estimation_unit: str = "points"
    wip_enforced: bool = False
    visibility: str = "workspace"
    owner_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime | None
