"""Sprint capacity schemas."""

import uuid

from pydantic import Field
from sqlmodel import SQLModel


class CapacityMemberRead(SQLModel):
    user_id: uuid.UUID
    name: str
    capacity: float | None = None
    note: str | None = None
    assigned_points: float = 0
    assigned_tasks: int = 0
    completed_points: float = 0
    overloaded: bool = False


class CapacityEntry(SQLModel):
    user_id: uuid.UUID
    capacity: float | None = Field(default=None, ge=0, le=100_000)
    note: str | None = Field(default=None, max_length=255)


class CapacityUpdate(SQLModel):
    entries: list[CapacityEntry] = Field(max_length=200)
