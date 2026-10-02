"""Auth/user request-response schemas.

Routers accept and return *these* classes, never table models, so DB internals
(hashed_password etc.) can never leak into responses.
"""

import uuid
from datetime import datetime

from pydantic import EmailStr, Field
from sqlmodel import SQLModel


class UserCreate(SQLModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    full_name: str = Field(default="", max_length=255)
    # One-time code emailed by POST /auth/otp/request. Registration refuses to
    # create the account without it, so an address cannot be claimed silently.
    code: str = Field(min_length=4, max_length=10)


class UserUpdate(SQLModel):
    email: EmailStr | None = None
    full_name: str | None = Field(default=None, max_length=255)


class UserRead(SQLModel):
    id: uuid.UUID
    email: str
    full_name: str
    is_active: bool
    created_at: datetime


class Token(SQLModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenRefresh(SQLModel):
    refresh_token: str


class RefreshedToken(SQLModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class PasswordForgot(SQLModel):
    email: EmailStr


class PasswordReset(SQLModel):
    token: str = Field(min_length=8)
    new_password: str = Field(min_length=10, max_length=128)


class OtpRequest(SQLModel):
    email: EmailStr


class OtpVerify(SQLModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=10)


class OAuthExchange(SQLModel):
    code: str = Field(min_length=8, max_length=256)
