"""MFA request/response schemas (M4 enterprise security)."""

from sqlmodel import Field, SQLModel


class MfaVerify(SQLModel):
    mfa_token: str = Field(min_length=8, max_length=256)
    code: str = Field(min_length=4, max_length=32)


class MfaEnable(SQLModel):
    code: str = Field(min_length=4, max_length=32)


class MfaStatus(SQLModel):
    enabled: bool


class MfaSetup(SQLModel):
    secret: str
    otpauth_uri: str
    recovery_codes: list[str]
