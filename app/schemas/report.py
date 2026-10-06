"""Agile report schemas."""

import uuid
from datetime import date, datetime

from sqlmodel import SQLModel


class BurndownPoint(SQLModel):
    day: date
    remaining_points: float
    remaining_tasks: int
    ideal_points: float | None = None


class BurndownReport(SQLModel):
    sprint_id: uuid.UUID
    sprint_name: str
    start_date: datetime | None
    end_date: datetime | None
    total_points: float
    total_tasks: int
    points: list[BurndownPoint]


class VelocityPoint(SQLModel):
    sprint_id: uuid.UUID
    sprint_name: str
    start_date: datetime | None
    end_date: datetime | None
    committed_points: float
    completed_points: float
    committed_tasks: int
    completed_tasks: int


class VelocityReport(SQLModel):
    project_id: uuid.UUID
    average_completed_points: float
    sprints: list[VelocityPoint]


class CfdPoint(SQLModel):
    day: date
    todo: int
    in_progress: int
    in_review: int
    done: int


class CfdReport(SQLModel):
    project_id: uuid.UUID
    days: int
    points: list[CfdPoint]


class CycleTimeItem(SQLModel):
    task_id: uuid.UUID
    key: str | None
    title: str
    lead_time_days: float
    cycle_time_days: float | None
    completed_at: datetime | None


class CycleTimeReport(SQLModel):
    project_id: uuid.UUID
    days: int
    count: int
    avg_lead_time_days: float | None
    p50_lead_time_days: float | None
    p85_lead_time_days: float | None
    avg_cycle_time_days: float | None
    p50_cycle_time_days: float | None
    p85_cycle_time_days: float | None
    items: list[CycleTimeItem]


class SprintMemberBreakdown(SQLModel):
    user_id: uuid.UUID | None
    name: str
    assigned_tasks: int
    completed_tasks: int
    completed_points: float


class SprintReport(SQLModel):
    sprint_id: uuid.UUID
    sprint_name: str
    state: str
    start_date: datetime | None
    end_date: datetime | None
    committed_tasks: int
    committed_points: float
    completed_tasks: int
    completed_points: float
    added_during_sprint: int
    carried_over: int
    scope_change_pct: float
    members: list[SprintMemberBreakdown]
