"""Workflow status + board schemas."""

import uuid
from typing import Literal

from pydantic import Field, field_validator
from sqlmodel import SQLModel

CategoryLiteral = Literal["todo", "in_progress", "in_review", "done"]
SwimlaneLiteral = Literal["none", "assignee", "priority", "label"]


class WorkflowStatusCreate(SQLModel):
    key: str = Field(min_length=1, max_length=32, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1, max_length=64)
    category: CategoryLiteral
    wip_limit: int | None = Field(default=None, ge=0, le=1000)
    transitions: list[str] = Field(default_factory=list, max_length=20)


class WorkflowStatusRead(WorkflowStatusCreate):
    id: uuid.UUID | None = None
    position: int = 0


class WorkflowUpdate(SQLModel):
    """Replaces the whole workflow (rows are matched by key)."""

    statuses: list[WorkflowStatusCreate] = Field(min_length=1, max_length=20)
    wip_enforced: bool | None = None

    @field_validator("statuses")
    @classmethod
    def unique_keys(cls, value: list[WorkflowStatusCreate]) -> list[WorkflowStatusCreate]:
        keys = [entry.key for entry in value]
        if len(keys) != len(set(keys)):
            raise ValueError("Workflow status keys must be unique")
        return value


class BoardCreate(SQLModel):
    name: str = Field(min_length=1, max_length=128)
    swimlane_by: SwimlaneLiteral = "none"
    filter_query: str | None = Field(default=None, max_length=2000)
    columns: list[str] | None = Field(default=None, max_length=20)
    is_default: bool = False


class BoardUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    swimlane_by: SwimlaneLiteral | None = None
    filter_query: str | None = Field(default=None, max_length=2000)
    columns: list[str] | None = Field(default=None, max_length=20)
    is_default: bool | None = None


class BoardRead(SQLModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    project_id: uuid.UUID
    name: str
    is_default: bool
    swimlane_by: str
    filter_query: str | None
    columns: list[str] | None
    created_at: object | None = None
    updated_at: object | None = None
