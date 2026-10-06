"""Global search schemas."""

import uuid
from datetime import datetime

from sqlmodel import SQLModel


class TaskSearchHit(SQLModel):
    id: uuid.UUID
    key: str | None
    title: str
    status: str
    priority: str
    type: str
    project_id: uuid.UUID
    project_name: str | None = None
    snippet: str | None = None


class CommentSearchHit(SQLModel):
    id: uuid.UUID
    task_id: uuid.UUID
    task_title: str | None = None
    task_key: str | None = None
    project_id: uuid.UUID | None = None
    body: str
    snippet: str | None = None
    created_at: datetime


class ProjectSearchHit(SQLModel):
    id: uuid.UUID
    name: str
    key: str | None
    status: str
    snippet: str | None = None


class SearchResponse(SQLModel):
    query: str
    tasks: list[TaskSearchHit]
    comments: list[CommentSearchHit]
    projects: list[ProjectSearchHit]
