"""Audit log + dashboard schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel
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
