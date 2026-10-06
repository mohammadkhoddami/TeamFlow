"""User model."""


from sqlalchemy import Boolean, Column, String, Text
from sqlmodel import Field, SQLModel

from app.models.base import TimeStampedMixin, UUIDMixin


class User(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "users"

    email: str = Field(
        sa_column=Column(String(255), unique=True, index=True, nullable=False)
    )
    hashed_password: str = Field(sa_column=Column(Text, nullable=False))
    # Google account subject ("sub") when the user signed in with Gmail.
    google_id: str | None = Field(
        default=None,
        sa_column=Column(String(255), unique=True, index=True, nullable=True),
    )
    full_name: str = Field(sa_column=Column(String(255), nullable=False))
    is_active: bool = Field(sa_column=Column(Boolean, nullable=False))
    is_superuser: bool = Field(sa_column=Column(Boolean, nullable=False))
    # True for the shadow user backing a service account (M3 #24): such users
    # cannot log in interactively and are hidden from member listings/pickers.
    is_service_account: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("full_name", "")
        kwargs.setdefault("is_active", True)
        kwargs.setdefault("is_superuser", False)
        kwargs.setdefault("is_service_account", False)
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return f"{self.full_name} <{self.email}>"

    def __str__(self) -> str:
        return self.__repr__()
