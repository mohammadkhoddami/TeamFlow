"""Comment service: threading, @mention notifications, reactions rollups.

Threading rules:
  - a reply's parent must belong to the same task and be a top-level comment
    or a reply (deep threads flatten to one level: replies hang off the root)
  - `root_id` always points at the thread root; both FK columns SET NULL on
    delete so removing a parent never removes its replies
"""

import re
import uuid

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import NotFoundError, PermissionDeniedError, ValidationFailedError
from app.models import (
    AuditAction,
    Comment,
    Membership,
    MembershipRole,
    Organization,
    Task,
    User,
)
from app.repositories import CommentRepository, ProjectRepository, UserRepository
from app.schemas import CommentCreate, CommentRead, CommentUpdate
from app.services import activities, audit, automations, events, preferences
from app.services import reactions as reaction_service

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

MAX_REPLY_DEPTH = 2


def extract_mentions(body: str) -> list[str]:
    """Mentions are plain emails inside the body: mention john@acme.com."""
    return list(dict.fromkeys(EMAIL_RE.findall(body)))


async def _resolve_thread(
    db: AsyncSession, task: Task, parent_id: uuid.UUID | None
) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """Validates the reply target and returns (parent_id, root_id)."""
    if parent_id is None:
        return None, None
    parent = await CommentRepository(db).get_in_org(parent_id, task.organization_id)
    if parent is None or parent.task_id != task.id:
        raise ValidationFailedError("Parent comment not found on this task")
    # Keep the direct parent for context; the thread root stays stable so the
    # client can render exactly one reply level.
    if parent.root_id is not None:
        return parent.id, parent.root_id
    return parent.id, parent.id


async def create_comment(
    db: AsyncSession,
    actor: User,
    org: Organization,
    task: Task,
    data: CommentCreate,
    ip: str | None = None,
    *,
    run_automations: bool = True,
) -> Comment:
    parent_id, root_id = await _resolve_thread(db, task, data.parent_id)
    comment = await CommentRepository(db).add(
        Comment(
            organization_id=org.id,
            task_id=task.id,
            author_id=actor.id,
            body=data.body,
            parent_id=parent_id,
            root_id=root_id,
        )
    )
    await audit.log(
        db, AuditAction.COMMENT_CREATED, actor_id=actor.id,
        organization_id=org.id, target_type="comment", target_id=comment.id, ip=ip,
        meta={"task_id": str(task.id), "parent_id": str(parent_id) if parent_id else None},
    )
    await activities.record(
        db,
        organization_id=org.id,
        project_id=task.project_id,
        task_id=task.id,
        actor_id=actor.id,
        verb="comment_created",
        summary=f"commented on {task.title}",
        data={"comment_id": str(comment.id), "reply": parent_id is not None},
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
    # The author of the parent comment also hears about replies.
    if parent_id is not None:
        parent_comment = await CommentRepository(db).get_in_org(parent_id, org.id)
        if parent_comment is not None and parent_comment.author_id:
            watcher_ids.append(parent_comment.author_id)
    for uid in dict.fromkeys(watcher_ids):
        if uid != actor.id and uid not in {u.id for u in mentioned.values()}:
            await events.notify(
                db,
                user_id=uid,
                type="comment_created",
                title=f"New comment on: {task.title}",
                organization_id=org.id,
                project_id=task.project_id,
                task_id=task.id,
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
                project_id=task.project_id,
                task_id=task.id,
                data={"task_id": str(task.id), "comment_id": str(comment.id)},
            )

    await db.commit()

    payload = {
        "id": str(comment.id),
        "task_id": str(task.id),
        "author_id": str(actor.id),
        "parent_id": str(parent_id) if parent_id else None,
        "mentioned": list(mentioned.keys()),
    }
    await events.publish_project_event(task.project_id, "comment.created", payload)
    await events.dispatch_webhooks(
        db, organization_id=org.id, event="comment.created", data=payload
    )
    await events.dispatch_integrations(
        db, organization_id=org.id, event="comment.created", data=payload
    )

    # Preference-gated email copies (comments default off; mentions default on).
    project = await ProjectRepository(db).get(task.project_id)
    if project is not None:
        excerpt = " ".join(data.body.split())[:280]
        mentioned_ids = {user.id for user in mentioned.values()}
        for user in mentioned.values():
            if user.id != actor.id:
                await preferences.task_email(
                    db,
                    user_id=user.id,
                    notification_type="mention",
                    kind="mention",
                    task=task,
                    project=project,
                    org_slug=org.slug,
                    extra_context={"author_name": actor.full_name or actor.email,
                                   "comment_excerpt": excerpt},
                )
        for uid in dict.fromkeys(watcher_ids):
            if uid != actor.id and uid not in mentioned_ids:
                await preferences.task_email(
                    db,
                    user_id=uid,
                    notification_type="comment_created",
                    kind="comment_created",
                    task=task,
                    project=project,
                    org_slug=org.slug,
                    extra_context={"author_name": actor.full_name or actor.email,
                                   "comment_excerpt": excerpt},
                )
    if run_automations:
        comment_id = comment.id  # snapshot before automation commit/rollback
        try:
            await automations.execute_rules_for_event(
                db,
                event="comment_created",
                task=task,
                org=org,
                actor=actor,
                context={"comment_body": data.body, "comment_id": str(comment_id)},
            )
        except Exception:  # noqa: BLE001 - automations must not break posting
            import logging

            logging.getLogger(__name__).exception(
                "Automation execution failed for comment %s", comment_id
            )
        # Automation actions commit/rollback and expire instances; reload so
        # the route serializer never touches expired attributes.
        comment = await CommentRepository(db).get_in_org(comment_id, org.id)
    return comment


async def list_comments(
    db: AsyncSession, task_id: uuid.UUID, *, offset: int = 0, limit: int = 50
) -> tuple[list[Comment], int]:
    return await CommentRepository(db).list_for_task(task_id, offset=offset, limit=limit)


async def serialize_comments(
    db: AsyncSession, comments: list[Comment]
) -> list[CommentRead]:
    """Attach reply counts + reaction rollups in two batched queries."""
    ids = [comment.id for comment in comments]
    reply_counts = await CommentRepository(db).reply_counts(ids)
    reaction_map = await reaction_service.summaries_for_comments(db, ids)
    payloads = []
    for comment in comments:
        read = CommentRead.model_validate(comment)
        read.reply_count = reply_counts.get(comment.id, 0)
        read.reactions = reaction_map.get(comment.id, [])
        payloads.append(read)
    return payloads


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
