"""Task schemas: requests, reads, and the whitelist of sortable fields."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field
from sqlmodel import SQLModel

from app.schemas.auth import UserRead
from app.schemas.label import LabelRead

StatusLiteral = Literal["todo", "in_progress", "in_review", "done"]
PriorityLiteral = Literal["low", "medium", "high", "urgent"]

# Whitelist of sortable columns; the service layer maps these to real columns.
SortableField = Literal["created_at", "updated_at", "title", "priority", "status", "due_date"]


class TaskCreate(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20_000)
    priority: PriorityLiteral = "medium"
    due_date: datetime | None = None
    assignee_id: uuid.UUID | None = None
    label_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)


class TaskUpdate(SQLModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20_000)
    status: StatusLiteral | None = None
    priority: PriorityLiteral | None = None
    due_date: datetime | None = None
    assignee_id: uuid.UUID | None = None
    label_ids: list[uuid.UUID] | None = Field(default=None, max_length=20)


class TaskRead(SQLModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    project_id: uuid.UUID
    title: str
    description: str | None
    status: str
    priority: str
    due_date: datetime | None
    created_by_id: uuid.UUID | None
    assignee_id: uuid.UUID | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime | None
    assignee: UserRead | None = None
    creator: UserRead | None = None
    labels: list[LabelRead] = Field(default_factory=list)
    watcher_ids: list[uuid.UUID] = Field(default_factory=list)


class TaskMove(SQLModel):
    """Explicit status-transition endpoint body (more API-visible than PATCH)."""

    status: StatusLiteral
