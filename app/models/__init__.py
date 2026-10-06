"""SQLModel persistence models.

Importing this package registers every table with SQLModel/SQLAlchemy metadata
(Alembic autogenerate and `init_db` rely on that). Conventions live in the
domain modules; this file only wires the public surface.
"""

from app.models.activity import Activity, ActivityVerb
from app.models.api_token import ApiToken, OAuthApp, OAuthToken, ServiceAccount
from app.models.attachment import Attachment, AttachmentStatus
from app.models.audit import AuditAction, AuditLog
from app.models.automation import (
    AutomationExecution,
    AutomationExecutionStatus,
    AutomationRule,
    AutomationTrigger,
)
from app.models.base import TimeStampedMixin, UUIDMixin, utcnow
from app.models.checklist import AssigneeRole, ChecklistItem, TaskAssignee
from app.models.comment import Comment
from app.models.custom_field import CustomField, CustomFieldType, CustomFieldValue
from app.models.idempotency import IdempotencyKey, IdempotencyStatus
from app.models.integration import (
    Integration,
    IntegrationEvent,
    IntegrationEventStatus,
    IntegrationProvider,
)
from app.models.label import Label
from app.models.notification import Notification, NotificationType
from app.models.notification_mute import NotificationMute
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
from app.models.reaction import CommentReaction
from app.models.release import Release, ReleaseStatus
from app.models.saved_filter import SavedFilter
from app.models.sprint import Sprint, SprintState
from app.models.sprint_capacity import SprintCapacity
from app.models.task import (
    Task,
    TaskLabelLink,
    TaskPriority,
    TaskStatus,
    TaskType,
    TaskWatcherLink,
)
from app.models.task_link import TaskLink, TaskLinkType, TaskStatusHistory
from app.models.template import ProjectTemplate, TaskTemplate
from app.models.user import User
from app.models.webhook import DeliveryStatus, Webhook, WebhookDelivery, WebhookEvent
from app.models.workflow import Board, SwimlaneBy, WorkflowStatus
from app.models.worklog import Worklog

__all__ = [
    "Activity",
    "ActivityVerb",
    "ApiToken",
    "AssigneeRole",
    "Attachment",
    "AttachmentStatus",
    "AuditAction",
    "AuditLog",
    "AutomationExecution",
    "AutomationExecutionStatus",
    "AutomationRule",
    "AutomationTrigger",
    "Board",
    "ChecklistItem",
    "Comment",
    "CommentReaction",
    "CustomField",
    "CustomFieldType",
    "CustomFieldValue",
    "DeliveryStatus",
    "DigestCadence",
    "EstimationUnit",
    "IdempotencyKey",
    "IdempotencyStatus",
    "Integration",
    "IntegrationEvent",
    "IntegrationEventStatus",
    "IntegrationProvider",
    "Invitation",
    "InvitationStatus",
    "Label",
    "Membership",
    "MembershipRole",
    "Notification",
    "NotificationMute",
    "NotificationPreference",
    "NotificationType",
    "OAuthApp",
    "OAuthToken",
    "Organization",
    "Project",
    "ProjectStatus",
    "ProjectTemplate",
    "Release",
    "ReleaseStatus",
    "SavedFilter",
    "ServiceAccount",
    "Sprint",
    "SprintCapacity",
    "SprintState",
    "SwimlaneBy",
    "Task",
    "TaskAssignee",
    "TaskLabelLink",
    "TaskLink",
    "TaskLinkType",
    "TaskPriority",
    "TaskStatus",
    "TaskStatusHistory",
    "TaskTemplate",
    "TaskType",
    "TaskWatcherLink",
    "TimeStampedMixin",
    "UUIDMixin",
    "User",
    "Webhook",
    "WebhookDelivery",
    "WebhookEvent",
    "WorkflowStatus",
    "Worklog",
    "generate_unsubscribe_token",
    "utcnow",
]
