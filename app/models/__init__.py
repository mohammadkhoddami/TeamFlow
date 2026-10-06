"""SQLModel persistence models.

Importing this package registers every table with SQLModel/SQLAlchemy metadata
(Alembic autogenerate and `init_db` rely on that). Conventions live in the
domain modules; this file only wires the public surface.
"""

from app.models.attachment import Attachment, AttachmentStatus
from app.models.audit import AuditAction, AuditLog
from app.models.base import TimeStampedMixin, UUIDMixin, utcnow
from app.models.comment import Comment
from app.models.idempotency import IdempotencyKey, IdempotencyStatus
from app.models.label import Label
from app.models.notification import Notification, NotificationType
from app.models.notification_preference import (
    DigestCadence,
    NotificationPreference,
    generate_unsubscribe_token,
)
from app.models.organization import (
    Invitation,
    InvitationStatus,
    Membership,
    MembershipRole,
    Organization,
)
from app.models.project import EstimationUnit, Project, ProjectStatus
from app.models.saved_filter import SavedFilter
from app.models.sprint import Sprint, SprintState
from app.models.task import (
    Task,
    TaskLabelLink,
    TaskPriority,
    TaskStatus,
    TaskType,
    TaskWatcherLink,
)
from app.models.user import User
from app.models.webhook import DeliveryStatus, Webhook, WebhookDelivery, WebhookEvent

__all__ = [
    "AuditAction",
    "AuditLog",
    "Attachment",
    "AttachmentStatus",
    "Comment",
    "DeliveryStatus",
    "DigestCadence",
    "EstimationUnit",
    "IdempotencyKey",
    "IdempotencyStatus",
    "Invitation",
    "InvitationStatus",
    "Label",
    "Membership",
    "MembershipRole",
    "Notification",
    "NotificationPreference",
    "NotificationType",
    "Organization",
    "Project",
    "ProjectStatus",
    "SavedFilter",
    "Sprint",
    "SprintState",
    "Task",
    "TaskLabelLink",
    "TaskPriority",
    "TaskStatus",
    "TaskType",
    "TaskWatcherLink",
    "TimeStampedMixin",
    "UUIDMixin",
    "User",
    "Webhook",
    "WebhookDelivery",
    "WebhookEvent",
    "generate_unsubscribe_token",
    "utcnow",
]
