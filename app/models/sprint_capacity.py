"""Per-sprint member capacity for capacity planning."""

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, Float, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy import Uuid as SAUuid
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import TimeStampedMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.sprint import Sprint
    from app.models.user import User


class SprintCapacity(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "sprint_capacities"
    __table_args__ = (
        UniqueConstraint("sprint_id", "user_id", name="uq_sprint_capacity_member"),
        Index("ix_sprint_capacities_sprint", "sprint_id"),
    )

    organization_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    sprint_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("sprints.id", ondelete="CASCADE"),
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
    capacity: float = Field(sa_column=Column(Float, nullable=False))
    note: str | None = Field(default=None, sa_column=Column(String(255), nullable=True))

    organization: Optional["Organization"] = Relationship()
    sprint: Optional["Sprint"] = Relationship()
    user: Optional["User"] = Relationship(sa_relationship_kwargs={"lazy": "joined"})

    def __repr__(self) -> str:
        return f"{self.user_id}: {self.capacity}"
