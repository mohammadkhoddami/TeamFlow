"""Public intake forms and their submissions (M4).

`Form` is a project-scoped, slug-addressed form definition; each field is a
dict shaped ``{"key", "label", "type", "required", "options"}`` with type one
of text/textarea/select/user/priority/date. `FormSubmission` stores the
answers and the task it created, if any.
"""

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import JSON, Boolean, Column, ForeignKey, Index, Integer, String, Text
from sqlalchemy import Uuid as SAUuid
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import TimeStampedMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.project import Project


class Form(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "forms"

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
            index=True,
        ),
    )
    name: str = Field(sa_column=Column(String(128), nullable=False))
    description: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    slug: str = Field(
        sa_column=Column(String(64), nullable=False, unique=True, index=True)
    )
    fields: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    is_public: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    submit_count: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default="0"),
    )
    created_by_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    project: Optional["Project"] = Relationship(
        sa_relationship_kwargs={"lazy": "joined"}
    )


class FormSubmission(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "form_submissions"
    __table_args__ = (
        Index("ix_form_submissions_form_created", "form_id", "created_at"),
    )

    organization_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    form_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("forms.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    task_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    data: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
