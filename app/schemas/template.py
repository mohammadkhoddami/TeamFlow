"""Project/task template schemas."""

import uuid
from typing import Literal

from pydantic import Field
from sqlmodel import SQLModel

PriorityLiteral = Literal["low", "medium", "high", "urgent"]
TypeLiteral = Literal["epic", "story", "task"]


class ProjectTemplateRead(SQLModel):
    id: str  # "builtin:scrum" or a UUID
    name: str
    description: str | None = None
    is_builtin: bool = False
    project_id: uuid.UUID | None = None


class ProjectFromTemplate(SQLModel):
    name: str = Field(min_length=1, max_length=255)
    template_id: str = Field(min_length=1, max_length=64)
    key: str | None = Field(default=None, min_length=2, max_length=10)
    description: str | None = Field(default=None, max_length=10_000)


class SaveProjectTemplate(SQLModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=10_000)


class TaskTemplateCreate(SQLModel):
    name: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20_000)
    priority: PriorityLiteral = "medium"
    type: TypeLiteral = "task"
    estimate: float | None = Field(default=None, ge=0, le=100_000)
    label_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    checklist: list[str] = Field(default_factory=list, max_length=50)
    project_id: uuid.UUID | None = None


class TaskTemplateRead(SQLModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    project_id: uuid.UUID | None
    name: str
    title: str
    description: str | None
    priority: str
    type: str
    estimate: float | None
    label_ids: list[uuid.UUID]
    checklist: list[str]


class TaskFromTemplate(SQLModel):
    project_id: uuid.UUID
    parent_id: uuid.UUID | None = None
