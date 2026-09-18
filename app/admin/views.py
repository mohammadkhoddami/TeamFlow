"""sqladmin ModelViews for every TeamFlow table.

Conventions:
- `TeamFlowModelView` holds shared defaults (CSV export, page sizes, hidden
  timestamps); `ReadOnlyModelView` removes create/edit for append-only or
  derived data (audit logs, deliveries, idempotency keys).
- Foreign keys are edited through relationships with AJAX lookups
  (`form_ajax_refs`) instead of loading every row of the target table.
- Writes funnel through `on_model_change`/`on_model_delete` for business
  invariants (password hashing, secret generation, self-lockout guards) and
  are persisted to `audit_logs` by `AdminAuditBackend`.
"""

from sqladmin import ModelView
from sqladmin.fields import SelectField
from sqladmin.filters import (
    AllUniqueStringValuesFilter,
    BooleanFilter,
    StaticValuesFilter,
)
from sqlalchemy import func
from sqlmodel import select
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from app.admin.auth import SESSION_USER_KEY
from app.admin.forms import UserAdminForm
from app.core import security
from app.core.db import AsyncSessionLocal
from app.models import (
    Attachment,
    AttachmentStatus,
    AuditLog,
    Comment,
    DeliveryStatus,
    IdempotencyKey,
    IdempotencyStatus,
    Invitation,
    InvitationStatus,
    Label,
    Membership,
    MembershipRole,
    Notification,
    NotificationType,
    Organization,
    Project,
    ProjectStatus,
    Task,
    TaskPriority,
    TaskStatus,
    User,
    Webhook,
    WebhookDelivery,
)

USER_REF = {"fields": ["email", "full_name"], "order_by": ["email"]}
ORGANIZATION_REF = {"fields": ["name", "slug"], "order_by": ["name"]}
PROJECT_REF = {"fields": ["name"], "order_by": ["name"]}
TASK_REF = {"fields": ["title"], "order_by": ["title"]}
LABEL_REF = {"fields": ["name"], "order_by": ["name"]}

_ROLE_CHOICES = [(role, role.title()) for role in MembershipRole.ALL]
_STATUS_CHOICES = [
    (status, status.replace("_", " ").title()) for status in InvitationStatus.ALL
]
_TASK_STATUS_CHOICES = [
    (status, status.replace("_", " ").title()) for status in TaskStatus.ALL
]
_TASK_PRIORITY_CHOICES = [
    (priority, priority.title()) for priority in TaskPriority.ALL
]
_PROJECT_STATUS_CHOICES = [
    (status, status.title()) for status in ProjectStatus.ALL
]
_ATTACHMENT_STATUS_CHOICES = [
    (status, status.title()) for status in AttachmentStatus.ALL
]
_NOTIFICATION_TYPE_CHOICES = [
    (ntype, ntype.replace("_", " ").title()) for ntype in NotificationType.ALL
]
_DELIVERY_STATUS_CHOICES = [
    (status, status.title()) for status in DeliveryStatus.ALL
]
_IDEMPOTENCY_STATUS_CHOICES = [
    (status, status.replace("_", " ").title())
    for status in (
        IdempotencyStatus.IN_PROGRESS,
        IdempotencyStatus.COMPLETED,
        IdempotencyStatus.FAILED,
    )
]


def _format_size(model: Attachment, attr: str) -> str:
    size = getattr(model, attr) or 0
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _format_body(model: Comment, attr: str) -> str:
    body = getattr(model, attr) or ""
    return body if len(body) <= 80 else f"{body[:80]}..."


class TeamFlowModelView(ModelView):
    """Shared defaults for every TeamFlow view."""

    can_export = True
    page_size = 25
    page_size_options = [25, 50, 100, 200]
    save_as = False
    form_excluded_columns = ["created_at", "updated_at"]


class ReadOnlyModelView(TeamFlowModelView):
    can_create = False
    can_edit = False


class UserAdmin(TeamFlowModelView, model=User):
    name = "User"
    name_plural = "Users"
    icon = "fa-solid fa-users"
    category = "Access"
    form = UserAdminForm
    column_list = [User.email, User.full_name, User.is_active, User.is_superuser, User.created_at]
    column_searchable_list = [User.email, User.full_name]
    column_sortable_list = [User.email, User.full_name, User.is_active, User.created_at]
    column_filters = [BooleanFilter(User.is_active), BooleanFilter(User.is_superuser)]
    column_details_exclude_list = [User.hashed_password]
    column_default_sort = [("created_at", True)]

    async def on_model_change(
        self, data: dict, model: User, is_created: bool, request: Request
    ) -> None:
        password = data.pop("password", None)
        if is_created and not password:
            raise ValueError("A password is required when creating a user.")
        if password:
            # bcrypt is CPU-bound and blocking; keep it off the event loop.
            model.hashed_password = await run_in_threadpool(
                security.hash_password, password
            )
        if "email" in data:
            data["email"] = str(data["email"]).strip().lower()

        admin_id = request.session.get(SESSION_USER_KEY)
        if (
            admin_id
            and str(model.id) == admin_id
            and (
                not data.get("is_active", True)
                or not data.get("is_superuser", False)
            )
        ):
            raise ValueError("You cannot deactivate or demote your own account.")

    async def on_model_delete(self, model: User, request: Request) -> None:
        admin_id = request.session.get(SESSION_USER_KEY)
        if admin_id and str(model.id) == admin_id:
            raise ValueError("You cannot delete your own account.")
        if model.is_superuser:
            async with AsyncSessionLocal() as db:
                remaining = (
                    await db.execute(
                        select(func.count())
                        .select_from(User)
                        .where(User.is_superuser.is_(True), User.id != model.id)
                    )
                ).scalar_one()
            if int(remaining) == 0:
                raise ValueError("The last superuser cannot be deleted.")


class OrganizationAdmin(TeamFlowModelView, model=Organization):
    name = "Organization"
    name_plural = "Organizations"
    icon = "fa-solid fa-building"
    category = "Access"
    column_list = [
        Organization.name,
        Organization.slug,
        Organization.is_active,
        Organization.created_by,
        Organization.created_at,
    ]
    column_searchable_list = [Organization.name, Organization.slug]
    column_sortable_list = ["name", "slug", "is_active", "created_at"]
    column_filters = [BooleanFilter(Organization.is_active)]
    column_default_sort = [("created_at", True)]
    form_ajax_refs = {"created_by": USER_REF}


class MembershipAdmin(TeamFlowModelView, model=Membership):
    name = "Membership"
    name_plural = "Memberships"
    icon = "fa-solid fa-user-tag"
    category = "Access"
    column_list = [
        Membership.user,
        Membership.organization,
        Membership.role,
        Membership.is_active,
        Membership.created_at,
    ]
    column_searchable_list = [
        "user.email",
        "user.full_name",
        "organization.name",
        "organization.slug",
    ]
    column_sortable_list = ["role", "is_active", "created_at"]
    column_filters = [
        StaticValuesFilter(Membership.role, _ROLE_CHOICES, title="Role"),
        BooleanFilter(Membership.is_active),
    ]
    form_ajax_refs = {"user": USER_REF, "organization": ORGANIZATION_REF}


class InvitationAdmin(TeamFlowModelView, model=Invitation):
    name = "Invitation"
    name_plural = "Invitations"
    icon = "fa-solid fa-envelope-open-text"
    category = "Access"
    column_list = [
        Invitation.email,
        Invitation.organization,
        Invitation.role,
        Invitation.status,
        Invitation.created_at,
    ]
    column_searchable_list = [Invitation.email, "organization.name"]
    column_sortable_list = ["email", "role", "status", "created_at"]
    column_filters = [
        StaticValuesFilter(Invitation.status, _STATUS_CHOICES, title="Status"),
        StaticValuesFilter(Invitation.role, _ROLE_CHOICES, title="Role"),
    ]
    form_ajax_refs = {"organization": ORGANIZATION_REF, "invited_by": USER_REF}


class ProjectAdmin(TeamFlowModelView, model=Project):
    name = "Project"
    name_plural = "Projects"
    icon = "fa-solid fa-diagram-project"
    category = "Work"
    column_list = [
        Project.name,
        Project.organization,
        Project.status,
        Project.owner,
        Project.created_at,
    ]
    column_searchable_list = [Project.name, "organization.name"]
    column_sortable_list = ["name", "status", "created_at"]
    column_filters = [
        StaticValuesFilter(Project.status, _PROJECT_STATUS_CHOICES, title="Status")
    ]
    form_ajax_refs = {"organization": ORGANIZATION_REF, "owner": USER_REF}


class TaskAdmin(TeamFlowModelView, model=Task):
    name = "Task"
    name_plural = "Tasks"
    icon = "fa-solid fa-list-check"
    category = "Work"
    form_overrides = {"status": SelectField, "priority": SelectField}
    form_args = {
        "status": {"choices": _TASK_STATUS_CHOICES},
        "priority": {"choices": _TASK_PRIORITY_CHOICES},
    }
    column_list = [
        Task.title,
        Task.project,
        Task.organization,
        Task.status,
        Task.priority,
        Task.assignee,
        Task.due_date,
        Task.created_at,
    ]
    column_searchable_list = [Task.title, Task.description]
    column_sortable_list = ["title", "status", "priority", "due_date", "created_at"]
    column_filters = [
        StaticValuesFilter(Task.status, _TASK_STATUS_CHOICES, title="Status"),
        StaticValuesFilter(Task.priority, _TASK_PRIORITY_CHOICES, title="Priority"),
    ]
    column_default_sort = [("created_at", True)]
    form_ajax_refs = {
        "organization": ORGANIZATION_REF,
        "project": PROJECT_REF,
        "creator": USER_REF,
        "assignee": USER_REF,
        "labels": LABEL_REF,
        "watchers": USER_REF,
    }


class LabelAdmin(TeamFlowModelView, model=Label):
    name = "Label"
    name_plural = "Labels"
    icon = "fa-solid fa-tags"
    category = "Work"
    column_list = [Label.name, Label.organization, Label.color, Label.created_at]
    column_searchable_list = [Label.name, "organization.name"]
    column_sortable_list = ["name", "created_at"]
    form_ajax_refs = {"organization": ORGANIZATION_REF}


class CommentAdmin(TeamFlowModelView, model=Comment):
    name = "Comment"
    name_plural = "Comments"
    icon = "fa-solid fa-comments"
    category = "Work"
    column_list = [
        Comment.task,
        Comment.author,
        Comment.body,
        Comment.created_at,
    ]
    column_searchable_list = [Comment.body, "author.email", "task.title"]
    column_sortable_list = ["created_at"]
    column_formatters = {Comment.body: _format_body}
    column_default_sort = [("created_at", True)]
    form_ajax_refs = {
        "organization": ORGANIZATION_REF,
        "task": TASK_REF,
        "author": USER_REF,
    }


class AttachmentAdmin(TeamFlowModelView, model=Attachment):
    name = "Attachment"
    name_plural = "Attachments"
    icon = "fa-solid fa-paperclip"
    category = "Work"
    column_list = [
        Attachment.filename,
        Attachment.task,
        Attachment.size,
        Attachment.content_type,
        Attachment.status,
        Attachment.created_at,
    ]
    column_searchable_list = [Attachment.filename, Attachment.content_type]
    column_sortable_list = ["filename", "size", "status", "created_at"]
    column_filters = [
        StaticValuesFilter(
            Attachment.status, _ATTACHMENT_STATUS_CHOICES, title="Status"
        )
    ]
    column_formatters = {Attachment.size: _format_size}
    column_default_sort = [("created_at", True)]
    form_ajax_refs = {
        "organization": ORGANIZATION_REF,
        "task": TASK_REF,
        "uploader": USER_REF,
    }


class NotificationAdmin(TeamFlowModelView, model=Notification):
    name = "Notification"
    name_plural = "Notifications"
    icon = "fa-solid fa-bell"
    category = "Automation"
    column_list = [
        Notification.user,
        Notification.type,
        Notification.title,
        Notification.read_at,
        Notification.created_at,
    ]
    column_searchable_list = [Notification.title, "user.email"]
    column_sortable_list = ["type", "created_at", "read_at"]
    column_filters = [
        StaticValuesFilter(
            Notification.type, _NOTIFICATION_TYPE_CHOICES, title="Type"
        )
    ]
    column_default_sort = [("created_at", True)]
    form_ajax_refs = {"user": USER_REF, "organization": ORGANIZATION_REF}


class WebhookAdmin(TeamFlowModelView, model=Webhook):
    name = "Webhook"
    name_plural = "Webhooks"
    icon = "fa-solid fa-satellite-dish"
    category = "Automation"
    form_excluded_columns = ["created_at", "updated_at", Webhook.secret]
    column_list = [
        Webhook.url,
        Webhook.organization,
        Webhook.events,
        Webhook.is_active,
        Webhook.created_at,
    ]
    column_searchable_list = [Webhook.url, Webhook.description]
    column_sortable_list = ["url", "is_active", "created_at"]
    column_filters = [BooleanFilter(Webhook.is_active)]
    column_details_exclude_list = [Webhook.secret]
    column_default_sort = [("created_at", True)]
    form_ajax_refs = {"organization": ORGANIZATION_REF, "created_by": USER_REF}

    async def on_model_change(
        self, data: dict, model: Webhook, is_created: bool, request: Request
    ) -> None:
        # The signing secret never travels through the form; generate it once.
        if not getattr(model, "secret", None):
            model.secret = security.token_urlsafe()


class WebhookDeliveryAdmin(ReadOnlyModelView, model=WebhookDelivery):
    name = "Webhook delivery"
    name_plural = "Webhook deliveries"
    icon = "fa-solid fa-truck-fast"
    category = "Automation"
    can_delete = True
    form_ajax_refs = {"webhook": {"fields": ["url"]}}
    column_list = [
        WebhookDelivery.webhook,
        WebhookDelivery.event,
        WebhookDelivery.status,
        WebhookDelivery.attempts,
        WebhookDelivery.response_status,
        WebhookDelivery.created_at,
        WebhookDelivery.delivered_at,
    ]
    column_searchable_list = ["event", "webhook.url"]
    column_sortable_list = ["event", "status", "attempts", "created_at"]
    column_filters = [
        StaticValuesFilter(
            WebhookDelivery.status, _DELIVERY_STATUS_CHOICES, title="Status"
        )
    ]
    column_default_sort = [("created_at", True)]


class AuditLogAdmin(ReadOnlyModelView, model=AuditLog):
    name = "Audit log"
    name_plural = "Audit logs"
    icon = "fa-solid fa-clipboard-list"
    category = "Logs"
    can_delete = False
    # `meta` collides with WTForms' Form.meta attribute; forms are never
    # rendered for this read-only view, but exclude it so scaffolding is safe.
    form_excluded_columns = ["created_at", "updated_at", "meta"]
    column_list = [
        AuditLog.created_at,
        AuditLog.action,
        AuditLog.actor,
        AuditLog.organization,
        AuditLog.target_type,
        AuditLog.target_id,
        AuditLog.ip,
    ]
    column_searchable_list = [AuditLog.action, AuditLog.target_id]
    column_sortable_list = ["created_at", "action"]
    column_filters = [AllUniqueStringValuesFilter(AuditLog.action)]
    column_default_sort = [("created_at", True)]
    form_ajax_refs = {"actor": USER_REF, "organization": ORGANIZATION_REF}


class IdempotencyKeyAdmin(ReadOnlyModelView, model=IdempotencyKey):
    name = "Idempotency key"
    name_plural = "Idempotency keys"
    icon = "fa-solid fa-repeat"
    category = "Logs"
    can_delete = True
    column_list = [
        IdempotencyKey.key,
        IdempotencyKey.method,
        IdempotencyKey.path,
        IdempotencyKey.status,
        IdempotencyKey.user,
        IdempotencyKey.created_at,
    ]
    column_searchable_list = [IdempotencyKey.key, IdempotencyKey.path]
    column_sortable_list = ["method", "status", "created_at"]
    column_filters = [
        StaticValuesFilter(
            IdempotencyKey.status, _IDEMPOTENCY_STATUS_CHOICES, title="Status"
        )
    ]
    column_default_sort = [("created_at", True)]
    form_ajax_refs = {"user": USER_REF}


ADMIN_VIEWS = (
    UserAdmin,
    OrganizationAdmin,
    MembershipAdmin,
    InvitationAdmin,
    ProjectAdmin,
    TaskAdmin,
    LabelAdmin,
    CommentAdmin,
    AttachmentAdmin,
    NotificationAdmin,
    WebhookAdmin,
    WebhookDeliveryAdmin,
    AuditLogAdmin,
    IdempotencyKeyAdmin,
)
