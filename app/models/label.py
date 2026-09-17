"""Label model: org-scoped tags attachable to tasks (M2M via TaskLabelLink)."""

import uuid

from sqlalchemy import Column, ForeignKey, String, UniqueConstraint
from sqlalchemy import Uuid as SAUuid
from sqlmodel import Field, SQLModel

from app.models.base import TimeStampedMixin, UUIDMixin


class Label(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "labels"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_label_org_name"),
    )

    organization_id: uuid.UUID = Field(
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    name: str = Field(sa_column=Column(String(64), nullable=False))
    color: str | None = Field(default=None, sa_column=Column(String(9), nullable=True))
