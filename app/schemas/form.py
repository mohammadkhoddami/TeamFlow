"""Form/request-intake schemas (M4).

A form is project-scoped and slug-addressed; the public read exposes only
what an anonymous submitter needs (fields, description, project name).
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator
from sqlmodel import SQLModel

from app.schemas.custom_field import slugify_key

FormFieldTypeLiteral = Literal["text", "textarea", "select", "user", "priority", "date"]


class FormField(SQLModel):
    key: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=256)
    type: FormFieldTypeLiteral
    required: bool = False
    options: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("key")
    @classmethod
    def normalize_key(cls, value: str) -> str:
        return slugify_key(value)


class FormCreate(SQLModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=20_000)
    fields: list[FormField] = Field(default_factory=list, max_length=100)
    is_public: bool = True


class FormUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=20_000)
    fields: list[FormField] | None = Field(default=None, max_length=100)
    is_public: bool | None = None


class FormSubmissionCreate(SQLModel):
    data: dict[str, Any] = Field(default_factory=dict)


class FormRead(SQLModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: str | None
    slug: str
    fields: list[FormField]
    is_public: bool
    submit_count: int
    created_at: datetime


class FormSubmissionRead(SQLModel):
    id: uuid.UUID
    data: dict
    task_id: uuid.UUID | None
    created_at: datetime


class PublicFormRead(SQLModel):
    name: str
    description: str | None
    fields: list[FormField]
    project_name: str
    slug: str


class FormSubmitted(SQLModel):
    task_id: uuid.UUID
    task_key: str | None = None
    detail: str
