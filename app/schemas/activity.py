"""Activity feed schemas (M3 #21)."""

import uuid
from datetime import datetime

from sqlmodel import SQLModel

from app.schemas.auth import UserRead


class ActivityRead(SQLModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    project_id: uuid.UUID | None
    task_id: uuid.UUID | None
    actor_id: uuid.UUID | None
    actor: UserRead | None = None
    verb: str
    summary: str
    data: dict | None
    created_at: datetime
