"""Task link / dependency schemas."""

import uuid
from datetime import datetime
from typing import Literal

from sqlmodel import SQLModel

TaskLinkTypeLiteral = Literal["blocks", "relates_to", "duplicates", "clones"]


class TaskLinkCreate(SQLModel):
    to_task_id: uuid.UUID
    link_type: TaskLinkTypeLiteral = "relates_to"


class LinkedTaskRef(SQLModel):
    id: uuid.UUID
    key: str | None
    title: str
    status: str
    status_category: str
    project_id: uuid.UUID


class TaskLinkRead(SQLModel):
    id: uuid.UUID
    link_type: str
    # Direction relative to the requested task: "out" = this task is `from`.
    direction: str
    task: LinkedTaskRef
    created_at: datetime


class TaskLinkSummary(SQLModel):
    blocks: list[TaskLinkRead]
    blocked_by: list[TaskLinkRead]
    relates_to: list[TaskLinkRead]
    duplicates: list[TaskLinkRead]
    clones: list[TaskLinkRead]
