"""Service layer: business rules. No HTTP, no SQL — just orchestration.

One module per domain; routers import through this package
(`from app.services import tasks`) so the call sites stay stable if a module
is ever refactored internally.
"""

from app.services import (
    attachments,
    audit,
    auth,
    bulk,
    cache,
    comments,
    dashboard,
    events,
    invitations,
    labels,
    notifications,
    organizations,
    preferences,
    projects,
    saved_filters,
    search,
    sprints,
    tasks,
    teamql,
    token_store,
    webhooks,
)
from app.services.invitations import accept_invitation, create_invitation
from app.services.organizations import (
    add_member_direct,
    create_organization,
    delete_organization,
    get_organization_for_user,
    list_organizations,
    role_rank,
    update_member_role,
)

__all__ = [
    "accept_invitation",
    "add_member_direct",
    "attachments",
    "audit",
    "auth",
    "bulk",
    "cache",
    "comments",
    "create_invitation",
    "create_organization",
    "dashboard",
    "delete_organization",
    "events",
    "get_organization_for_user",
    "invitations",
    "labels",
    "list_organizations",
    "notifications",
    "organizations",
    "preferences",
    "projects",
    "role_rank",
    "saved_filters",
    "search",
    "sprints",
    "tasks",
    "teamql",
    "token_store",
    "update_member_role",
    "webhooks",
]
