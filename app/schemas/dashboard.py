"""Audit log + dashboard schemas (M1 stats and M4 saved dashboards)."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import SQLModel


class AuditLogRead(SQLModel):
    id: uuid.UUID
    actor_id: uuid.UUID | None
    organization_id: uuid.UUID | None
    action: str
    target_type: str | None
    target_id: str | None
    ip: str | None
    meta: dict | None
    created_at: datetime


class TasksByStatus(BaseModel):
    todo: int = 0
    in_progress: int = 0
    in_review: int = 0
    done: int = 0


class TasksPerMember(BaseModel):
    user_id: uuid.UUID
    full_name: str
    open_tasks: int


class DashboardStats(BaseModel):
    projects: int
    active_projects: int
    total_tasks: int
    completed_tasks: int
    overdue_tasks: int
    unassigned_tasks: int
    tasks_by_status: TasksByStatus
    tasks_per_member: list[TasksPerMember]
    active_members: int


# --- M4: saved dashboards / widget builder ---

WidgetTypeLiteral = Literal["stats", "status", "members", "overdue", "activity"]


class DashboardWidget(BaseModel):
    """One card on a saved dashboard; `config` is widget-specific extras."""

    id: str | None = None
    type: WidgetTypeLiteral
    title: str = Field(min_length=1, max_length=128)
    config: dict = Field(default_factory=dict)


class DashboardCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    widgets: list[DashboardWidget] = Field(default_factory=list, max_length=50)
    project_id: uuid.UUID | None = None
    is_default: bool = False


class DashboardUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    widgets: list[DashboardWidget] | None = Field(default=None, max_length=50)
    project_id: uuid.UUID | None = None
    is_default: bool | None = None


class DashboardRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    project_id: uuid.UUID | None
    name: str
    widgets: list[DashboardWidget]
    is_default: bool
    created_by_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime | None = None


class WidgetData(BaseModel):
    id: str
    type: str
    title: str
    data: Any


class DashboardData(BaseModel):
    widgets: list[WidgetData]
