"""Repository layer: the only place raw queries live.

Repositories know about SQLModel tables and sessions but never commit —
services own transaction boundaries so multi-step operations stay atomic.
All methods return raw models/rows; serialization is the schema layer's job.
"""

from app.repositories.attachment import AttachmentRepository
from app.repositories.audit import AuditLogRepository
from app.repositories.comment import CommentRepository
from app.repositories.idempotency import IdempotencyRepository
from app.repositories.invitation import InvitationRepository
from app.repositories.label import LabelRepository
from app.repositories.notification import NotificationRepository
from app.repositories.organization import MembershipRepository, OrganizationRepository
from app.repositories.project import ProjectRepository
from app.repositories.task import TaskFilters, TaskRepository
from app.repositories.user import UserRepository
from app.repositories.webhook import WebhookDeliveryRepository, WebhookRepository

__all__ = [
    "AttachmentRepository",
    "AuditLogRepository",
    "CommentRepository",
    "IdempotencyRepository",
    "InvitationRepository",
    "LabelRepository",
    "MembershipRepository",
    "NotificationRepository",
    "OrganizationRepository",
    "ProjectRepository",
    "TaskFilters",
    "TaskRepository",
    "UserRepository",
    "WebhookDeliveryRepository",
    "WebhookRepository",
]
