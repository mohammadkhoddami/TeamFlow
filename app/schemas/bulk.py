"""Bulk task operation schemas."""

import uuid
from typing import Literal

from pydantic import Field
from sqlmodel import SQLModel

from app.schemas.task import PriorityLiteral, StatusLiteral


class BulkTaskRequest(SQLModel):
    """One request shape for every multi-select action.

    `action` decides which optional fields apply:
      - update:        status/priority/assignee_id/label_ids/sprint_id/estimate
      - move:          status (step-wise transitions enforced per task)
      - clone:         project_id/label_ids? (full copy into project_id or same)
      - move_project:  project_id (parent tasks are detached when needed)
      - archive/restore/delete: no extra fields
    """

    task_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    action: Literal[
        "update", "move", "clone", "delete", "archive", "restore", "move_project"
    ]
    status: StatusLiteral | None = None
    priority: PriorityLiteral | None = None
    assignee_id: uuid.UUID | None = None
    label_ids: list[uuid.UUID] | None = Field(default=None, max_length=20)
    sprint_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    estimate: float | None = Field(default=None, ge=0, le=100_000)


class BulkTaskFailure(SQLModel):
    task_id: uuid.UUID
    reason: str


class BulkTaskResult(SQLModel):
    requested: int
    updated: int
    skipped: int
    created_ids: list[uuid.UUID] = Field(default_factory=list)
    failures: list[BulkTaskFailure] = Field(default_factory=list)


class BulkArchiveRequest(SQLModel):
    task_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    archive: bool = True
