"""Label schemas."""

import uuid
from datetime import datetime

from pydantic import Field, field_validator
from sqlmodel import SQLModel


class LabelCreate(SQLModel):
    name: str = Field(min_length=1, max_length=64)
    color: str | None = Field(default=None, max_length=9)

    @field_validator("color")
    @classmethod
    def color_hex(cls, v: str | None) -> str | None:
        if v is not None and not (v.startswith("#") and len(v) == 7):
            raise ValueError("color must be #RRGGBB")
        return v


class LabelUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    color: str | None = None


class LabelRead(SQLModel):
    id: uuid.UUID
    name: str
    color: str | None
    organization_id: uuid.UUID
    created_at: datetime
