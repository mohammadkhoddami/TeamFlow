"""Audit log model: immutable record of important business actions."""

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import JSON, Column, ForeignKey, Index, String
from sqlalchemy import Uuid as SAUuid
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import TimeStampedMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.user import User


class AuditAction:
    # auth
    USER_REGISTERED = "user.registered"
    USER_LOGIN = "user.login"
    USER_LOGIN_FAILED = "user.login_failed"
    PASSWORD_RESET_REQUESTED = "user.password_reset_requested"
    PASSWORD_RESET = "user.password_reset"
    # organizations
    ORG_CREATED = "organization.created"
    ORG_UPDATED = "organization.updated"
    ORG_DELETED = "organization.deleted"
    INVITATION_CREATED = "invitation.created"
    INVITATION_ACCEPTED = "invitation.accepted"
    INVITATION_DECLINED = "invitation.declined"
    MEMBER_REMOVED = "member.removed"
    MEMBER_ROLE_CHANGED = "member.role_changed"
    # projects
    PROJECT_CREATED = "project.created"
    PROJECT_UPDATED = "project.updated"
    PROJECT_DELETED = "project.deleted"
    # tasks
    TASK_CREATED = "task.created"
    TASK_UPDATED = "task.updated"
    TASK_DELETED = "task.deleted"
    TASK_ASSIGNED = "task.assigned"
    TASK_COMPLETED = "task.completed"
    # comments / attachments / webhooks
    COMMENT_CREATED = "comment.created"
    COMMENT_DELETED = "comment.deleted"
    ATTACHMENT_UPLOADED = "attachment.uploaded"
    ATTACHMENT_REQUESTED = "attachment.requested"
    ATTACHMENT_DELETED = "attachment.deleted"
    WEBHOOK_CREATED = "webhook.created"
    WEBHOOK_DELETED = "webhook.deleted"
    # admin panel (session-authenticated superusers)
    ADMIN_LOGIN = "admin.login"
    ADMIN_LOGIN_FAILED = "admin.login_failed"
    ADMIN_LOGOUT = "admin.logout"
    ADMIN_CREATE = "admin.create"
    ADMIN_UPDATE = "admin.update"
    ADMIN_DELETE = "admin.delete"


class AuditLog(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_org_created", "organization_id", "created_at"),
        Index("ix_audit_actor", "actor_id"),
    )

    actor_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    organization_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    action: str = Field(sa_column=Column(String(64), nullable=False))
    target_type: str | None = Field(
        default=None, sa_column=Column(String(64), nullable=True)
    )
    target_id: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    ip: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    meta: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))

    actor: Optional["User"] = Relationship()
    organization: Optional["Organization"] = Relationship()

    def __repr__(self) -> str:
        return f"{self.action} ({self.target_type or '-'}:{self.target_id or '-'})"
