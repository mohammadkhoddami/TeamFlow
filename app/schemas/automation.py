"""Automation rule builder schemas (M3 #14).

Conditions and actions are validated structurally here (shape + known types);
semantic validation (does the status/label/user exist) happens in the service.
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlmodel import SQLModel

TriggerLiteral = Literal[
    "task_created", "task_updated", "status_changed", "comment_created", "schedule"
]
ConditionOpLiteral = Literal[
    "equals", "not_equals", "contains", "not_contains", "in", "not_in", "gt", "lt",
    "is_set", "is_empty",
]
ActionTypeLiteral = Literal[
    "assign", "transition", "comment", "notify", "webhook", "add_label", "set_priority"
]


class AutomationCondition(BaseModel):
    field: str = Field(min_length=1, max_length=64)
    op: ConditionOpLiteral = "equals"
    value: Any = None


class AutomationAction(BaseModel):
    type: ActionTypeLiteral
    # assign
    assignee_id: uuid.UUID | None = None
    # transition
    status: str | None = Field(default=None, max_length=32)
    # comment / notify (body), webhook (url)
    body: str | None = Field(default=None, max_length=20_000)
    url: str | None = Field(default=None, max_length=2048)
    # notify recipient (explicit user or role group)
    user_id: uuid.UUID | None = None
    role: str | None = Field(default=None, max_length=16)
    # add_label
    label_id: uuid.UUID | None = None
    # set_priority
    priority: Literal["low", "medium", "high", "urgent"] | None = None


class AutomationRuleCreate(SQLModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    project_id: uuid.UUID | None = None
    trigger_type: TriggerLiteral
    trigger_config: dict | None = None
    conditions: list[AutomationCondition] | None = Field(default=None, max_length=20)
    actions: list[AutomationAction] = Field(min_length=1, max_length=20)
    is_active: bool = True


class AutomationRuleUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None
    trigger_config: dict | None = None
    conditions: list[AutomationCondition] | None = Field(default=None, max_length=20)
    actions: list[AutomationAction] | None = Field(default=None, min_length=1, max_length=20)


class AutomationRuleRead(SQLModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    project_id: uuid.UUID | None
    name: str
    description: str | None
    is_active: bool
    trigger_type: str
    trigger_config: dict | None
    conditions: list[dict] | None
    actions: list[dict]
    last_run_at: datetime | None
    run_count: int
    created_at: datetime


class AutomationExecutionRead(SQLModel):
    id: uuid.UUID
    rule_id: uuid.UUID
    rule_name: str | None = None
    project_id: uuid.UUID | None
    task_id: uuid.UUID | None
    trigger_event: str
    status: str
    actions_log: list[dict]
    error: str | None
    created_at: datetime


class AutomationTemplateRead(BaseModel):
    id: str
    name: str
    description: str
    trigger_type: str
    trigger_config: dict | None = None
    conditions: list[dict] | None = None
    actions: list[dict]


class AutomationRunSummary(BaseModel):
    evaluated: int
    executed: int
    skipped: int
