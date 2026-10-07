"""Custom fields: typed per-project attributes without schema migrations.

A `CustomField` defines the attribute (text/number/date/select/multi_select/
user/checkbox); `CustomFieldValue` stores one value per task and field as JSON,
so new field types never require DDL.
"""

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy import Uuid as SAUuid
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import TimeStampedMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.project import Project
    from app.models.task import Task


class CustomFieldType:
    TEXT = "text"
    NUMBER = "number"
    DATE = "date"
    SELECT = "select"
    MULTI_SELECT = "multi_select"
    USER = "user"
    CHECKBOX = "checkbox"

    ALL = (TEXT, NUMBER, DATE, SELECT, MULTI_SELECT, USER, CHECKBOX)


class CustomField(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "custom_fields"
    __table_args__ = (
        UniqueConstraint("project_id", "key", name="uq_custom_field_project_key"),
        Index("ix_custom_fields_project_position", "project_id", "position"),
    )

    organization_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    project_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    name: str = Field(sa_column=Column(String(64), nullable=False))
    # Stable slug used by TeamQL (`cf_<key>`) and imports.
    key: str = Field(sa_column=Column(String(32), nullable=False))
    field_type: str = Field(sa_column=Column(String(16), nullable=False))
    options: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    is_required: bool = Field(sa_column=Column(Boolean, nullable=False))
    position: int = Field(sa_column=Column(Integer, nullable=False, server_default="0"))

    organization: Optional["Organization"] = Relationship()
    project: Optional["Project"] = Relationship()

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("options", [])
        kwargs.setdefault("is_required", False)
        kwargs.setdefault("position", 0)
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return self.name


class CustomFieldValue(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "custom_field_values"
    __table_args__ = (
        UniqueConstraint("task_id", "field_id", name="uq_custom_value_task_field"),
        Index("ix_custom_values_org_field", "organization_id", "field_id"),
    )

    organization_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    task_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    field_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("custom_fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    value: object = Field(sa_column=Column(JSON, nullable=True))

    task: Optional["Task"] = Relationship()
    field: Optional["CustomField"] = Relationship()
