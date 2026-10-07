"""Custom-role and per-project membership schemas (M4 permissions)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import EmailStr, Field
from sqlmodel import SQLModel

ProjectMemberRoleLiteral = Literal["viewer", "member", "manager"]


class CustomRoleCreate(SQLModel):
    name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=1000)
    permissions: list[str] = Field(default_factory=list, max_length=64)


class CustomRoleUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=1000)
    permissions: list[str] | None = Field(default=None, max_length=64)


class CustomRoleRead(SQLModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    description: str | None
    permissions: list[str]
    created_by_id: uuid.UUID | None = None
    created_at: datetime


class ProjectMemberUser(SQLModel):
    id: uuid.UUID
    email: str
    full_name: str


class ProjectMemberCreate(SQLModel):
    user_email: EmailStr
    role: ProjectMemberRoleLiteral = "member"


class ProjectMemberUpdate(SQLModel):
    role: ProjectMemberRoleLiteral


class ProjectMemberRead(SQLModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    project_id: uuid.UUID
    user_id: uuid.UUID
    role: str
    created_at: datetime
    user: ProjectMemberUser | None = None
