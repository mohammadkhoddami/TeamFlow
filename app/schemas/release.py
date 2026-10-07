"""Release + roadmap schemas (M3 #16)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field
from sqlmodel import SQLModel

from app.schemas.auth import UserRead

ReleaseStatusLiteral = Literal["planned", "in_progress", "released", "cancelled"]


class ReleaseCreate(SQLModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=20_000)
    version: str | None = Field(default=None, max_length=64)
    status: ReleaseStatusLiteral = "planned"
    start_date: datetime | None = None
    release_date: datetime | None = None


class ReleaseUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=20_000)
    version: str | None = Field(default=None, max_length=64)
    status: ReleaseStatusLiteral | None = None
    start_date: datetime | None = None
    release_date: datetime | None = None


class ReleaseRead(SQLModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: str | None
    version: str | None
    status: str
    start_date: datetime | None
    release_date: datetime | None
    released_at: datetime | None
    created_at: datetime
    task_count: int = 0
    done_task_count: int = 0


class RoadmapTaskRef(SQLModel):
    id: uuid.UUID
    key: str | None
    title: str
    type: str
    status: str
    status_category: str
    priority: str
    due_date: datetime | None
    estimate: float | None
    assignee: UserRead | None = None


class RoadmapEpic(SQLModel):
    id: uuid.UUID
    key: str | None
    title: str
    status: str
    status_category: str
    priority: str
    start_date: datetime | None
    due_date: datetime | None
    task_count: int
    done_task_count: int
    children: list[RoadmapTaskRef] = Field(default_factory=list)


class RoadmapResponse(SQLModel):
    project_id: uuid.UUID
    releases: list[ReleaseRead] = Field(default_factory=list)
    epics: list[RoadmapEpic] = Field(default_factory=list)
    unassigned: list[RoadmapTaskRef] = Field(default_factory=list)
