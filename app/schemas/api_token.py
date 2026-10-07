"""API token / service account / OAuth app schemas (M3 #24)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field
from sqlmodel import SQLModel

ScopeLiteral = Literal["read", "write", "admin"]

DEFAULT_SCOPES = ["read", "write"]


class ApiTokenCreate(SQLModel):
    name: str = Field(min_length=1, max_length=128)
    scopes: list[str] = Field(default_factory=lambda: ["read", "write"], max_length=10)
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=100_000)
    # When set, the token belongs to a service account instead of the caller.
    service_account_id: uuid.UUID | None = None


class ApiTokenUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    scopes: list[str] | None = Field(default=None, max_length=10)
    is_active: bool | None = None
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=100_000)


class ApiTokenRead(SQLModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    user_id: uuid.UUID
    service_account_id: uuid.UUID | None
    name: str
    token_prefix: str
    scopes: list[str]
    rate_limit_per_minute: int | None
    expires_at: datetime | None
    last_used_at: datetime | None
    usage_count: int
    is_active: bool
    revoked_at: datetime | None
    created_at: datetime


class ApiTokenCreated(ApiTokenRead):
    """Returned exactly once, at creation: includes the plaintext secret."""

    token: str


class ApiTokenUsage(BaseModel):
    token_id: uuid.UUID
    name: str
    usage_count: int
    last_used_at: datetime | None
    rate_limit_per_minute: int | None
    requests_last_minute: int


class ServiceAccountCreate(SQLModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    scopes: list[str] = Field(default_factory=lambda: ["read", "write"], max_length=10)


class ServiceAccountUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    scopes: list[str] | None = Field(default=None, max_length=10)
    is_active: bool | None = None


class ServiceAccountRead(SQLModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    user_id: uuid.UUID
    name: str
    description: str | None
    scopes: list[str]
    is_active: bool
    created_at: datetime


class OAuthAppCreate(SQLModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    redirect_uris: list[str] = Field(default_factory=list, max_length=10)
    scopes: list[str] = Field(default_factory=lambda: ["read"], max_length=10)


class OAuthAppUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    redirect_uris: list[str] | None = Field(default=None, max_length=10)
    scopes: list[str] | None = Field(default=None, max_length=10)
    is_active: bool | None = None


class OAuthAppRead(SQLModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    description: str | None
    client_id: str
    redirect_uris: list[str]
    scopes: list[str]
    is_active: bool
    last_used_at: datetime | None
    created_at: datetime


class OAuthAppCreated(OAuthAppRead):
    """Returned exactly once, at creation: includes the plaintext secret."""

    client_secret: str


class OAuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    scope: str
