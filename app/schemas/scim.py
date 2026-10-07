"""SCIM 2.0 request schemas (M4 enterprise user provisioning)."""

from typing import Any

from sqlmodel import Field, SQLModel


class ScimName(SQLModel):
    formatted: str | None = Field(default=None, max_length=255)


class ScimUserCreate(SQLModel):
    userName: str = Field(min_length=1, max_length=255)
    name: ScimName | None = None
    active: bool = True


class ScimOperation(SQLModel):
    op: str
    path: str | None = None
    value: Any = None


class ScimPatchRequest(SQLModel):
    schemas: list[str] = Field(default_factory=list)
    Operations: list[ScimOperation] = Field(default_factory=list)
