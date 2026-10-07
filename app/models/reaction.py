"""Emoji reactions on comments (M3 #21)."""

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy import Uuid as SAUuid
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import TimeStampedMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.comment import Comment
    from app.models.user import User


class CommentReaction(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "comment_reactions"
    __table_args__ = (
        UniqueConstraint("comment_id", "user_id", "emoji", name="uq_comment_reaction"),
        Index("ix_comment_reactions_comment", "comment_id"),
    )

    organization_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    comment_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("comments.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    user_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    emoji: str = Field(sa_column=Column(String(32), nullable=False))

    comment: Optional["Comment"] = Relationship()
    user: Optional["User"] = Relationship(sa_relationship_kwargs={"lazy": "joined"})
