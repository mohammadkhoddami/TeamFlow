"""Organization, membership, and invitation schemas."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import EmailStr, Field
from sqlmodel import SQLModel

from app.models.organization import MembershipRole

RoleLiteral = Literal["owner", "admin", "manager", "member"]


class OrganizationCreate(SQLModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(
        pattern=r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$",
        min_length=2,
        max_length=63,
    )


class OrganizationUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None


class OrganizationRead(SQLModel):
    id: uuid.UUID
    name: str
    slug: str
    is_active: bool
    created_at: datetime
    my_role: str | None = None  # role of the requesting user, if any


class MembershipCreate(SQLModel):
    user_email: EmailStr
    role: RoleLiteral = MembershipRole.MEMBER


class MembershipUpdate(SQLModel):
    role: RoleLiteral


class MembershipRead(SQLModel):
    id: uuid.UUID
    role: str
    user_id: uuid.UUID
    organization_id: uuid.UUID
    created_at: datetime
    user: "UserBrief | None" = None


class UserBrief(SQLModel):
    id: uuid.UUID
    email: str
    full_name: str


MembershipRead.model_rebuild()


class OrganizationMemberRead(SQLModel):
    """Used on list pages: org summary + viewer's role."""

    organization: OrganizationRead
    role: str


class InvitationCreate(SQLModel):
    email: EmailStr
    role: RoleLiteral = MembershipRole.MEMBER


class InvitationRead(SQLModel):
    id: uuid.UUID
    email: str
    role: str
    status: str
    organization_id: uuid.UUID
    organization_name: str | None = None
    invited_by_id: uuid.UUID | None = None
    created_at: datetime
