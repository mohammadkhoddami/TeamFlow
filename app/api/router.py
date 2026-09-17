"""API v1 router aggregation: single include point for the application."""

from fastapi import APIRouter

from app.api.routes import (
    attachments,
    audit,
    auth,
    comments,
    dashboard,
    health,
    invitations,
    labels,
    notifications,
    organizations,
    projects,
    tasks,
    webhooks,
)

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(organizations.router)
api_router.include_router(organizations.members_router)
api_router.include_router(invitations.router)
api_router.include_router(invitations.org_router)
api_router.include_router(projects.router)
api_router.include_router(projects.project_router)
api_router.include_router(tasks.org_task_router)
api_router.include_router(tasks.project_task_router)
api_router.include_router(tasks.task_router)
api_router.include_router(labels.router)
api_router.include_router(labels.label_router)
api_router.include_router(labels.task_label_router)
api_router.include_router(comments.router)
api_router.include_router(comments.comment_router)
api_router.include_router(attachments.router)
api_router.include_router(attachments.attachment_router)
api_router.include_router(notifications.router)
api_router.include_router(webhooks.router)
api_router.include_router(audit.audit_router)
api_router.include_router(dashboard.dashboard_router)
