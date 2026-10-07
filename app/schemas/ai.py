"""AI breakdown schemas (M4, heuristic only — no external API)."""

import uuid
from typing import Literal

from pydantic import Field
from sqlmodel import SQLModel

AiItemTypeLiteral = Literal["epic", "story", "task"]
AiPriorityLiteral = Literal["low", "medium", "high", "urgent"]


class AiBreakdownRequest(SQLModel):
    description: str = Field(min_length=0, max_length=20_000)
    project_id: uuid.UUID | None = None


class AiBreakdownItem(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    type: AiItemTypeLiteral = "task"
    priority: AiPriorityLiteral = "medium"
    children: list["AiBreakdownItem"] = Field(default_factory=list, max_length=100)


AiBreakdownItem.model_rebuild()


class AiBreakdownProposal(SQLModel):
    provided: bool
    items: list[AiBreakdownItem] = Field(default_factory=list)
    suggested_priority: AiPriorityLiteral = "medium"


class AiApplyRequest(SQLModel):
    project_id: uuid.UUID
    parent_id: uuid.UUID | None = None
    items: list[AiBreakdownItem] = Field(min_length=1, max_length=100)


class AiApplyFailure(SQLModel):
    title: str
    error: str


class AiApplyResult(SQLModel):
    created: int
    task_ids: list[uuid.UUID] = Field(default_factory=list)
    failures: list[AiApplyFailure] = Field(default_factory=list)
