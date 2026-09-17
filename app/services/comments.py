"""Comment service with @mention notifications."""

import re
import uuid

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.models import (
    AuditAction,
    Comment,
    Membership,
    MembershipRole,
    Organization,
    Task,
    User,
)
from app.repositories import CommentRepository, UserRepository
from app.schemas import CommentCreate, CommentUpdate
from app.services import audit, events

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


def extract_mentions(body: str) -> list[str]:
    """Mentions are plain emails inside the body: mention john@acme.com."""
    return list(dict.fromkeys(EMAIL_RE.findall(body)))


async def create_comment(
    db: AsyncSession,
    actor: User,
    org: Organization,
    task: Task,
    data: CommentCreate,
    ip: str | None = None,
) -> Comment:
    comment = await CommentRepository(db).add(
        Comment(
            organization_id=org.id,
            task_id=task.id,
            author_id=actor.id,
            body=data.body,
        )
    )
    await audit.log(
        db, AuditAction.COMMENT_CREATED, actor_id=actor.id,
        organization_id=org.id, target_type="comment", target_id=comment.id, ip=ip,
        meta={"task_id": str(task.id)},
    )

    # Mentioned users (must be real users) get 'mention'; watchers + assignee
    # (minus actor and explicit mentions) get 'comment_created'.
    mentioned: dict[str, User] = {}
    for email in extract_mentions(data.body):
        user = await UserRepository(db).get_by_email(email)
        if user:
            mentioned[email] = user

    watcher_ids = [w.id for w in task.watchers]
    if task.assignee_id:
        watcher_ids.append(task.assignee_id)
    for uid in dict.fromkeys(watcher_ids):
        if uid != actor.id and uid not in {u.id for u in mentioned.values()}:
            await events.notify(
                db,
                user_id=uid,
                type="comment_created",
                title=f"New comment on: {task.title}",
                organization_id=org.id,
                data={"task_id": str(task.id), "comment_id": str(comment.id)},
            )

    for user in mentioned.values():
        if user.id != actor.id:
            await events.notify(
                db,
                user_id=user.id,
                type="mention",
                title=f"You were mentioned on: {task.title}",
                organization_id=org.id,
                data={"task_id": str(task.id), "comment_id": str(comment.id)},
            )

    await db.commit()

    payload = {
        "id": str(comment.id),
        "task_id": str(task.id),
        "author_id": str(actor.id),
        "mentioned": list(mentioned.keys()),
    }
    await events.publish_project_event(task.project_id, "comment.created", payload)
    await events.dispatch_webhooks(
        db, organization_id=org.id, event="comment.created", data=payload
    )
    return comment


async def list_comments(
    db: AsyncSession, task_id: uuid.UUID, *, offset: int = 0, limit: int = 50
) -> tuple[list[Comment], int]:
    return await CommentRepository(db).list_for_task(task_id, offset=offset, limit=limit)


async def get_comment_for_org(
    db: AsyncSession, comment_id: uuid.UUID, organization_id: uuid.UUID
) -> Comment:
    comment = await CommentRepository(db).get_in_org(comment_id, organization_id)
    if not comment:
        # 404 hides cross-org comment IDs (IDOR containment).
        raise NotFoundError("Comment not found")
    return comment


async def _can_modify(membership: Membership, comment: Comment, actor: User) -> bool:
    return comment.author_id == actor.id or membership.role != MembershipRole.MEMBER


async def update_comment(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    comment: Comment,
    data: CommentUpdate,
    ip: str | None = None,
) -> Comment:
    if not await _can_modify(membership, comment, actor):
        raise PermissionDeniedError("Only the author (or managers+) can edit a comment")
    comment.body = data.body
    comment = await CommentRepository(db).update(comment)
    await db.commit()
    return comment


async def delete_comment(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    comment: Comment,
    ip: str | None = None,
) -> None:
    if not await _can_modify(membership, comment, actor):
        raise PermissionDeniedError("Only the author (or managers+) can delete a comment")
    await audit.log(
        db, AuditAction.COMMENT_DELETED, actor_id=actor.id,
        organization_id=org.id, target_type="comment", target_id=comment.id, ip=ip,
        meta={"task_id": str(comment.task_id)},
    )
    await CommentRepository(db).delete(comment)
    await db.commit()
