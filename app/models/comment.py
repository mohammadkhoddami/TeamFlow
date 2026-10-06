"""Comment model."""

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, ForeignKey, Index, Text
from sqlalchemy import Uuid as SAUuid
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import TimeStampedMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.task import Task
    from app.models.user import User


class Comment(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "comments"
    __table_args__ = (
        Index("ix_comments_task_created", "task_id", "created_at"),
        Index("ix_comments_task_root", "task_id", "root_id", "created_at"),
    )

    organization_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
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
    author_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    body: str = Field(sa_column=Column(Text, nullable=False))
    # Threading: `parent_id` is the direct reply target, `root_id` the top-level
    # comment of the thread (NULL for top-level comments). Both SET NULL so
    # deleting a parent never deletes its replies.
    parent_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("comments.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    root_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("comments.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    organization: Optional["Organization"] = Relationship()
    task: Optional["Task"] = Relationship()
    author: Optional["User"] = Relationship(sa_relationship_kwargs={"lazy": "joined"})
