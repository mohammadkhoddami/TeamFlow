"""Comment schemas."""

import uuid
from datetime import datetime

from pydantic import Field
from sqlmodel import SQLModel

from app.schemas.auth import UserRead


class CommentCreate(SQLModel):
    body: str = Field(min_length=1, max_length=20_000)


class CommentUpdate(SQLModel):
    body: str = Field(min_length=1, max_length=20_000)


class CommentRead(SQLModel):
    id: uuid.UUID
    task_id: uuid.UUID
    organization_id: uuid.UUID
    body: str
    author: UserRead | None = None
    created_at: datetime
    updated_at: datetime | None
