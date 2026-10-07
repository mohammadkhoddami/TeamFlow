"""Repository layer: the only place raw queries live.

Repositories know about SQLModel tables and sessions but never commit —
services own transaction boundaries so multi-step operations stay atomic.
All methods return raw models/rows; serialization is the schema layer's job.
"""

from app.repositories.activity import ActivityRepository
from app.repositories.api_token import (
    ApiTokenRepository,
    OAuthAppRepository,
    OAuthTokenRepository,
    ServiceAccountRepository,
)
from app.repositories.attachment import AttachmentRepository
from app.repositories.audit import AuditLogRepository
from app.repositories.automation import AutomationRepository
from app.repositories.capacity import CapacityRepository
from app.repositories.checklist import ChecklistRepository, TaskAssigneeRepository
from app.repositories.comment import CommentRepository
from app.repositories.custom_field import (
    CustomFieldRepository,
    CustomFieldValueRepository,
)
from app.repositories.idempotency import IdempotencyRepository
from app.repositories.integration import IntegrationRepository
from app.repositories.invitation import InvitationRepository
from app.repositories.label import LabelRepository
from app.repositories.notification import NotificationRepository
from app.repositories.organization import MembershipRepository, OrganizationRepository
from app.repositories.preference import PreferenceRepository
from app.repositories.project import ProjectRepository
from app.repositories.reaction import MuteRepository, ReactionRepository
from app.repositories.release import ReleaseRepository
from app.repositories.saved_filter import SavedFilterRepository
from app.repositories.sprint import SprintRepository
from app.repositories.task import TaskFilters, TaskRepository, fts_condition
from app.repositories.task_link import TaskLinkRepository, TaskStatusHistoryRepository
from app.repositories.template import (
    ProjectTemplateRepository,
    TaskTemplateRepository,
)
from app.repositories.user import UserRepository
from app.repositories.webhook import WebhookDeliveryRepository, WebhookRepository
from app.repositories.workflow import BoardRepository, WorkflowStatusRepository
from app.repositories.worklog import WorklogRepository

__all__ = [
    "ActivityRepository",
    "ApiTokenRepository",
    "AttachmentRepository",
    "AuditLogRepository",
    "AutomationRepository",
    "BoardRepository",
    "CapacityRepository",
    "ChecklistRepository",
    "CommentRepository",
    "CustomFieldRepository",
    "CustomFieldValueRepository",
    "IdempotencyRepository",
    "IntegrationRepository",
    "InvitationRepository",
    "LabelRepository",
    "MembershipRepository",
    "MuteRepository",
    "NotificationRepository",
    "OAuthAppRepository",
    "OAuthTokenRepository",
    "OrganizationRepository",
    "PreferenceRepository",
    "ProjectRepository",
    "ProjectTemplateRepository",
    "ReactionRepository",
    "ReleaseRepository",
    "SavedFilterRepository",
    "ServiceAccountRepository",
    "SprintRepository",
    "TaskAssigneeRepository",
    "TaskFilters",
    "TaskLinkRepository",
    "TaskRepository",
    "TaskStatusHistoryRepository",
    "TaskTemplateRepository",
    "UserRepository",
    "WebhookDeliveryRepository",
    "WebhookRepository",
    "WorkflowStatusRepository",
    "WorklogRepository",
    "fts_condition",
]
