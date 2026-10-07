"""SSO (OIDC) configuration and SCIM token schemas (M4 enterprise)."""

import uuid
from datetime import datetime
from typing import Literal

from sqlmodel import Field, SQLModel

RoleLiteral = Literal["owner", "admin", "manager", "member"]


class SsoConfigUpdate(SQLModel):
    issuer: str = Field(min_length=1, max_length=512)
    client_id: str = Field(min_length=1, max_length=255)
    # Empty on update keeps the stored secret; required on first create.
    client_secret: str = Field(default="", max_length=512)
    scopes: list[str] = Field(default_factory=lambda: ["openid", "email", "profile"])
    is_enabled: bool = True
    auto_provision: bool = True
    default_role: RoleLiteral = "member"


class SsoConfigRead(SQLModel):
    provider: str
    issuer: str
    client_id: str
    scopes: list[str]
    is_enabled: bool
    auto_provision: bool
    default_role: str
    has_secret: bool


class SsoPublicConfig(SQLModel):
    enabled: bool
    provider: str
    login_url: str


class ScimTokenCreate(SQLModel):
    name: str = Field(min_length=1, max_length=128)


class ScimTokenRead(SQLModel):
    id: uuid.UUID
    name: str
    is_active: bool
    last_used_at: datetime | None = None
    created_at: datetime


class ScimTokenCreated(ScimTokenRead):
    # Plain token is returned exactly once, at creation time.
    token: str
