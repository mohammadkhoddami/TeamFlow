"""Worklog + timesheet schemas."""

import uuid
from datetime import date, datetime

from pydantic import Field
from sqlmodel import SQLModel


class WorklogCreate(SQLModel):
    minutes: int = Field(ge=1, le=24 * 60)
    started_at: datetime
    description: str | None = Field(default=None, max_length=2000)


class WorklogUpdate(SQLModel):
    minutes: int | None = Field(default=None, ge=1, le=24 * 60)
    started_at: datetime | None = None
    description: str | None = Field(default=None, max_length=2000)


class WorklogRead(SQLModel):
    id: uuid.UUID
    task_id: uuid.UUID
    user_id: uuid.UUID | None
    user_name: str | None = None
    minutes: int
    started_at: datetime
    description: str | None
    created_at: datetime


class TimesheetRow(SQLModel):
    day: date
    user_id: uuid.UUID | None
    user_name: str
    task_id: uuid.UUID
    task_key: str | None
    task_title: str
    minutes: int


class TimesheetTotals(SQLModel):
    user_id: uuid.UUID | None
    user_name: str
    minutes: int


class TimesheetReport(SQLModel):
    date_from: date
    date_to: date
    total_minutes: int
    rows: list[TimesheetRow]
    totals_by_user: list[TimesheetTotals]
