"""Task schemas: requests, reads, hierarchy nodes, and sortable whitelist."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field
from sqlmodel import SQLModel

from app.schemas.auth import UserRead
from app.schemas.label import LabelRead

StatusLiteral = Literal["todo", "in_progress", "in_review", "done"]
PriorityLiteral = Literal["low", "medium", "high", "urgent"]
TaskTypeLiteral = Literal["epic", "story", "task"]

# Whitelist of sortable columns; the service layer maps these to real columns.
# `type` sorts alphabetically, which happens to be epic < story < task.
SortableField = Literal[
    "created_at", "updated_at", "title", "priority", "status", "due_date", "type"
]


class TaskParentRef(SQLModel):
    """Compact parent summary embedded in task reads (breadcrumbs, links)."""

    id: uuid.UUID
    title: str
    type: str
    status: str
    priority: str


class TaskCreate(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20_000)
    priority: PriorityLiteral = "medium"
    due_date: datetime | None = None
    assignee_id: uuid.UUID | None = None
    label_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    type: TaskTypeLiteral = "task"
    parent_id: uuid.UUID | None = None


class TaskUpdate(SQLModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20_000)
    status: StatusLiteral | None = None
    priority: PriorityLiteral | None = None
    due_date: datetime | None = None
    assignee_id: uuid.UUID | None = None
    label_ids: list[uuid.UUID] | None = Field(default=None, max_length=20)
    type: TaskTypeLiteral | None = None
    parent_id: uuid.UUID | None = None


class TaskRead(SQLModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    project_id: uuid.UUID
    title: str
    description: str | None
    status: str
    priority: str
    type: str
    due_date: datetime | None
    parent_id: uuid.UUID | None = None
    created_by_id: uuid.UUID | None
    assignee_id: uuid.UUID | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime | None
    assignee: UserRead | None = None
    creator: UserRead | None = None
    parent: TaskParentRef | None = None
    labels: list[LabelRead] = Field(default_factory=list)
    watcher_ids: list[uuid.UUID] = Field(default_factory=list)
    # Direct children only (roll-ups are derived in the tree endpoint).
    child_count: int = 0
    done_child_count: int = 0


class TaskTreeNode(TaskRead):
    """TaskRead plus nested children, used by the project tree endpoint.

    Depth is bounded by the epic > story > task rules, so the recursion
    always terminates.
    """

    children: list["TaskTreeNode"] = Field(default_factory=list)


class TaskMove(SQLModel):
    """Explicit status-transition endpoint body (more API-visible than PATCH)."""

    status: StatusLiteral
