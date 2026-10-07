"""Goal/OKR schemas (M4).

A goal is an org-level objective linked to tasks; reads embeds the linked
tasks with their rolled-up progress plus the goal's aggregate progress.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field
from sqlmodel import SQLModel

from app.schemas.auth import UserRead

GoalStatusLiteral = Literal["active", "achieved", "cancelled"]


class GoalCreate(SQLModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=20_000)
    status: GoalStatusLiteral = "active"
    due_date: datetime | None = None
    owner_id: uuid.UUID | None = None


class GoalUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=20_000)
    status: GoalStatusLiteral | None = None
    due_date: datetime | None = None
    owner_id: uuid.UUID | None = None


class GoalTaskRef(SQLModel):
    """Linked task summary with derived progress (0-100)."""

    id: uuid.UUID
    key: str | None = None
    title: str
    type: str
    status: str
    status_category: str
    progress_pct: int = 0


class GoalTaskLinkRequest(SQLModel):
    task_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)


class GoalRead(SQLModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    description: str | None
    status: str
    due_date: datetime | None
    owner_id: uuid.UUID | None
    owner: UserRead | None = None
    created_by_id: uuid.UUID | None
    progress_pct: int = 0
    tasks: list[GoalTaskRef] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime | None = None
