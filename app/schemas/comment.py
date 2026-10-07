"""Comment schemas."""

import uuid
from datetime import datetime

from pydantic import Field
from sqlmodel import SQLModel

from app.schemas.auth import UserRead


class CommentCreate(SQLModel):
    body: str = Field(min_length=1, max_length=20_000)
    # Threading: reply to a comment by ID (its thread root is derived server-side).
    parent_id: uuid.UUID | None = None


class CommentUpdate(SQLModel):
    body: str = Field(min_length=1, max_length=20_000)


class ReactionSummary(SQLModel):
    emoji: str
    count: int
    user_ids: list[uuid.UUID] = Field(default_factory=list)


class ReactionCreate(SQLModel):
    emoji: str = Field(min_length=1, max_length=32)


class CommentRead(SQLModel):
    id: uuid.UUID
    task_id: uuid.UUID
    organization_id: uuid.UUID
    body: str
    parent_id: uuid.UUID | None = None
    root_id: uuid.UUID | None = None
    author: UserRead | None = None
    created_at: datetime
    updated_at: datetime | None
    reply_count: int = 0
    reactions: list[ReactionSummary] = Field(default_factory=list)
