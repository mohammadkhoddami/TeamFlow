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
    full_name: str = Field(sa_column=Column(String(255), nullable=False))
    is_active: bool = Field(sa_column=Column(Boolean, nullable=False))
    is_superuser: bool = Field(sa_column=Column(Boolean, nullable=False))

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("full_name", "")
        kwargs.setdefault("is_active", True)
        kwargs.setdefault("is_superuser", False)
        super().__init__(**kwargs)
