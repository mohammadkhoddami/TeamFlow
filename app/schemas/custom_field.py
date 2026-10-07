"""Custom field schemas."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator
from sqlmodel import SQLModel

CustomFieldTypeLiteral = Literal[
    "text", "number", "date", "select", "multi_select", "user", "checkbox"
]


def slugify_key(value: str) -> str:
    slug = "".join(
        char.lower() if char.isalnum() else "_" for char in value.strip()
    ).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    if slug and slug[0].isdigit():
        slug = f"f_{slug}"
    return slug[:32] or "field"


class CustomFieldCreate(SQLModel):
    name: str = Field(min_length=1, max_length=64)
    key: str | None = Field(default=None, min_length=1, max_length=32)
    field_type: CustomFieldTypeLiteral
    options: list[str] = Field(default_factory=list, max_length=100)
    is_required: bool = False

    @field_validator("key")
    @classmethod
    def normalize_key(cls, value: str | None) -> str | None:
        return slugify_key(value) if value else None


class CustomFieldUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    options: list[str] | None = Field(default=None, max_length=100)
    is_required: bool | None = None
    position: int | None = Field(default=None, ge=0, le=1000)


class CustomFieldRead(SQLModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    project_id: uuid.UUID
    name: str
    key: str
    field_type: str
    options: list[str]
    is_required: bool
    position: int
    created_at: datetime


class CustomFieldValueRead(SQLModel):
    field_id: uuid.UUID
    key: str
    name: str
    field_type: str
    value: Any = None
