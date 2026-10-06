"""Calendar view schemas (M3 #17)."""

import uuid
from datetime import datetime

from pydantic import Field
from sqlmodel import SQLModel

from app.schemas.auth import UserRead


class CalendarTaskRead(SQLModel):
    id: uuid.UUID
    key: str | None
    title: str
    due_date: datetime
    status: str
    status_category: str
    priority: str
    type: str
    project_id: uuid.UUID
    project_name: str
    estimate: float | None = None
    assignee: UserRead | None = None


class CalendarResponse(SQLModel):
    start: datetime
    end: datetime
    tasks: list[CalendarTaskRead] = Field(default_factory=list)
