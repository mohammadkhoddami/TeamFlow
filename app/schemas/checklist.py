"""Checklist + multi-assignee schemas."""

import uuid
from typing import Literal

from pydantic import Field
from sqlmodel import SQLModel

AssigneeRoleLiteral = Literal["assignee", "approver"]


class ChecklistItemCreate(SQLModel):
    text: str = Field(min_length=1, max_length=500)


class ChecklistItemUpdate(SQLModel):
    text: str | None = Field(default=None, min_length=1, max_length=500)
    is_done: bool | None = None
    position: int | None = Field(default=None, ge=0, le=1000)


class ChecklistItemRead(SQLModel):
    id: uuid.UUID
    task_id: uuid.UUID
    text: str
    is_done: bool
    position: int


class TaskAssigneeEntry(SQLModel):
    user_id: uuid.UUID
    role: AssigneeRoleLiteral = "assignee"


class TaskAssigneesUpdate(SQLModel):
    assignees: list[TaskAssigneeEntry] = Field(max_length=20)


class TaskAssigneeRead(SQLModel):
    user_id: uuid.UUID
    name: str
    email: str
    role: str
