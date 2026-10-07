"""Dependency-injection layer: request-scoped cross-cutting concerns.

This is the FastAPI pattern that replaces Django middleware/decorators:
declare what a route needs as an annotated parameter, FastAPI resolves it.

Dependencies here:
  DB             - per-request SQLModel/SQLAlchemy async session
  CurrentUser    - JWT-authenticated, active user (binds the logging context)
  OrgMembership  - (org, membership) for org-scoped routes; the tenant boundary
  ProjectAccess  - (project, org, membership) for id-addressed projects
  TaskAccess     - (task, org, membership) for id-addressed tasks
  RedisDep       - shared async Redis client
  Storage        - S3/MinIO client

Role enforcement stays in services so programmatic callers get identical
rules; dependencies resolve *context*, not permissions.
"""

import uuid
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from jwt import PyJWTError
from redis.asyncio import Redis
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import security
from app.core.db import get_db
from app.core.exceptions import NotFoundError, UnauthorizedError
from app.core.logging import org_id_ctx, user_id_ctx
from app.core.redis import get_redis_client
from app.models import (
    Attachment,
    Comment,
    Label,
    Membership,
    MembershipRole,
    Organization,
    Project,
    ProjectMember,
    Sprint,
    Task,
    User,
)
from app.repositories import (
    MembershipRepository,
    OrganizationRepository,
)
from app.services.integrations.storage import StorageClient

DB = Annotated[AsyncSession, Depends(get_db)]

# tokenUrl points at the login endpoint so Swagger's "Authorize" button works.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

Token = Annotated[str, Depends(oauth2_scheme)]

RedisDep = Annotated[Redis, Depends(get_redis_client)]


def get_storage() -> StorageClient:
    return StorageClient.from_settings()


Storage = Annotated[StorageClient, Depends(get_storage)]


async def get_current_user(request: Request, token: Token, db: DB) -> User:
    """JWT or M3 API token.

    Personal/service-account tokens (`tf_...`) and OAuth2 access tokens
    (`tfo_...`) resolve to the owning User; scope + rate-limit checks happen
    inside the token service so every route gets them for free.
    """
    from app.services import api_tokens

    # Check the OAuth prefix first: "tfo_..." also starts with "tf_".
    if token.startswith(api_tokens.OAUTH_TOKEN_PREFIX):
        user = await api_tokens.authenticate_oauth_token(
            db, token, method=request.method, path=request.url.path
        )
        user_id_ctx.set(str(user.id))
        return user
    if token.startswith(api_tokens.TOKEN_PREFIX):
        api_token = await api_tokens.authenticate_token(
            db, token, method=request.method, path=request.url.path
        )
        user = await db.get(User, api_token.user_id)
        if not user or not user.is_active:
            raise UnauthorizedError("Token owner not found or deactivated")
        user_id_ctx.set(str(user.id))
        return user

    try:
        payload = security.decode_token(token)
        user_id = uuid.UUID(payload["sub"])
    except (PyJWTError, KeyError, ValueError):
        raise UnauthorizedError("Invalid or expired token") from None

    user = await db.get(User, user_id)
    if not user or not user.is_active:
        raise UnauthorizedError("User not found or deactivated")
    user_id_ctx.set(str(user.id))
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_org_membership(
    slug: str, current_user: CurrentUser, db: DB
) -> tuple[Organization, Membership]:
    """Resolves a slug to (organization, membership) and enforces that the
    current user is an active member. Every org-scoped route declares this
    dependency, which is where tenant isolation is enforced in one place."""
    org = await OrganizationRepository(db).get_by_slug(slug)
    if not org:
        raise NotFoundError("Organization not found")
    membership = await MembershipRepository(db).get_for_user(current_user.id, org.id)
    if not membership or not membership.is_active:
        # 404 (not 403) so non-members cannot even confirm the org exists.
        raise NotFoundError("Organization not found")
    org_id_ctx.set(str(org.id))
    return org, membership


OrgMembership = Annotated[tuple[Organization, Membership], Depends(get_org_membership)]


async def _assert_project_visible(
    db: DB, project: Project, membership: Membership
) -> None:
    """Private projects are concealed (404) from non-admin members without an
    explicit `project_members` row."""
    if project.visibility != "private":
        return
    if membership.role in (MembershipRole.ADMIN, MembershipRole.OWNER):
        return
    statement = select(ProjectMember.id).where(
        ProjectMember.project_id == project.id,
        ProjectMember.user_id == membership.user_id,
    )
    if (await db.execute(statement)).scalars().first() is None:
        raise NotFoundError("Project not found")


async def get_project_access(
    project_id: uuid.UUID, current_user: CurrentUser, db: DB
) -> tuple[Project, Organization, Membership]:
    """Tenant boundary for id-addressed projects: project -> its org -> the
    caller's membership. Non-members and unknown IDs both get 404 so project
    IDs cannot be probed across tenants."""
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if not project:
        raise NotFoundError("Project not found")
    membership = await MembershipRepository(db).get_for_user(
        current_user.id, project.organization_id
    )
    if not membership or not membership.is_active:
        raise NotFoundError("Project not found")
    await _assert_project_visible(db, project, membership)
    org = await OrganizationRepository(db).get(project.organization_id)
    if not org:
        raise NotFoundError("Project not found")
    org_id_ctx.set(str(org.id))
    return project, org, membership


ProjectAccess = Annotated[
    tuple[Project, Organization, Membership], Depends(get_project_access)
]


async def get_task_access(
    task_id: uuid.UUID, current_user: CurrentUser, db: DB
) -> tuple[Task, Organization, Membership]:
    """Tenant boundary for id-addressed tasks (IDOR containment). Uses a
    select() query (not db.get) so eager strategies load relationships
    safely inside the async session."""
    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    if not task:
        raise NotFoundError("Task not found")
    membership = await MembershipRepository(db).get_for_user(
        current_user.id, task.organization_id
    )
    if not membership or not membership.is_active:
        raise NotFoundError("Task not found")
    project = (
        await db.execute(select(Project).where(Project.id == task.project_id))
    ).scalar_one_or_none()
    if not project:
        raise NotFoundError("Task not found")
    await _assert_project_visible(db, project, membership)
    org = await OrganizationRepository(db).get(task.organization_id)
    if not org:
        raise NotFoundError("Task not found")
    org_id_ctx.set(str(org.id))
    return task, org, membership


TaskAccess = Annotated[tuple[Task, Organization, Membership], Depends(get_task_access)]


async def get_sprint_access(
    sprint_id: uuid.UUID, current_user: CurrentUser, db: DB
) -> tuple[Sprint, Organization, Membership]:
    """Tenant boundary for id-addressed sprints (IDOR containment)."""
    sprint = (
        await db.execute(select(Sprint).where(Sprint.id == sprint_id))
    ).scalar_one_or_none()
    if not sprint:
        raise NotFoundError("Sprint not found")
    membership = await MembershipRepository(db).get_for_user(
        current_user.id, sprint.organization_id
    )
    if not membership or not membership.is_active:
        raise NotFoundError("Sprint not found")
    org = await OrganizationRepository(db).get(sprint.organization_id)
    if not org:
        raise NotFoundError("Sprint not found")
    org_id_ctx.set(str(org.id))
    return sprint, org, membership


SprintAccess = Annotated[tuple[Sprint, Organization, Membership], Depends(get_sprint_access)]


async def get_attachment_access(
    attachment_id: uuid.UUID, current_user: CurrentUser, db: DB
) -> tuple[Attachment, Organization, Membership]:
    """Tenant boundary for id-addressed attachments (IDOR containment)."""
    attachment = (
        await db.execute(select(Attachment).where(Attachment.id == attachment_id))
    ).scalar_one_or_none()
    if not attachment:
        raise NotFoundError("Attachment not found")
    membership = await MembershipRepository(db).get_for_user(
        current_user.id, attachment.organization_id
    )
    if not membership or not membership.is_active:
        raise NotFoundError("Attachment not found")
    org = await OrganizationRepository(db).get(attachment.organization_id)
    if not org:
        raise NotFoundError("Attachment not found")
    return attachment, org, membership


AttachmentAccess = Annotated[
    tuple[Attachment, Organization, Membership], Depends(get_attachment_access)
]


async def get_comment_access(
    comment_id: uuid.UUID, current_user: CurrentUser, db: DB
) -> tuple[Comment, Organization, Membership]:
    """Tenant boundary for id-addressed comments (IDOR containment)."""
    comment = (
        await db.execute(select(Comment).where(Comment.id == comment_id))
    ).scalar_one_or_none()
    if not comment:
        raise NotFoundError("Comment not found")
    membership = await MembershipRepository(db).get_for_user(
        current_user.id, comment.organization_id
    )
    if not membership or not membership.is_active:
        raise NotFoundError("Comment not found")
    org = await OrganizationRepository(db).get(comment.organization_id)
    if not org:
        raise NotFoundError("Comment not found")
    return comment, org, membership


CommentAccess = Annotated[
    tuple[Comment, Organization, Membership], Depends(get_comment_access)
]


async def get_label_access(
    label_id: uuid.UUID, current_user: CurrentUser, db: DB
) -> tuple[Label, Organization, Membership]:
    """Tenant boundary for id-addressed labels (IDOR containment)."""
    label = (
        await db.execute(select(Label).where(Label.id == label_id))
    ).scalar_one_or_none()
    if not label:
        raise NotFoundError("Label not found")
    membership = await MembershipRepository(db).get_for_user(
        current_user.id, label.organization_id
    )
    if not membership or not membership.is_active:
        raise NotFoundError("Label not found")
    org = await OrganizationRepository(db).get(label.organization_id)
    if not org:
        raise NotFoundError("Label not found")
    return label, org, membership


LabelAccess = Annotated[tuple[Label, Organization, Membership], Depends(get_label_access)]
