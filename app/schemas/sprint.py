"""Sprint schemas: request bodies and aggregate-carrying reads."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field
from sqlmodel import SQLModel

SprintStateLiteral = Literal["planned", "active", "completed"]


class SprintCreate(SQLModel):
    name: str = Field(min_length=1, max_length=255)
    goal: str | None = Field(default=None, max_length=10_000)
    start_date: datetime | None = None
    end_date: datetime | None = None


class SprintUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    goal: str | None = Field(default=None, max_length=10_000)
    start_date: datetime | None = None
    end_date: datetime | None = None


class SprintComplete(SQLModel):
    """Completing a sprint moves unfinished tasks to a target sprint.

    `carry_over_sprint_id` must be a planned sprint in the same project;
    omitting it returns unfinished tasks to the backlog.
    """

    carry_over_sprint_id: uuid.UUID | None = None


class SprintRead(SQLModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    project_id: uuid.UUID
    name: str
    goal: str | None
    state: str
    start_date: datetime | None
    end_date: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime | None
    task_count: int = 0
    done_task_count: int = 0
    total_estimate: float | None = None
    done_estimate: float | None = None
    carried_over_count: int = 0
