"""Comment reactions with emoji whitelist (M3 #21)."""

import uuid

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import (
    NotFoundError,
    PermissionDeniedError,
    ValidationFailedError,
)
from app.models import AuditAction, Comment, CommentReaction, Organization, User
from app.repositories import ReactionRepository
from app.services import audit

# Curated set: the picker shows these; arbitrary strings are rejected.
ALLOWED_EMOJIS = (
    "👍", "👎", "❤️", "🎉", "😄", "😅", "🙏", "👀", "🚀", "✅", "❌", "🔥",
    "😢", "🤔", "💡", "⚠️",
)

MAX_REACTION_LENGTH = 8


def _validate_emoji(emoji: str) -> str:
    emoji = emoji.strip()
    if len(emoji) > MAX_REACTION_LENGTH:
        raise ValidationFailedError("Reaction is too long")
    if emoji not in ALLOWED_EMOJIS:
        raise ValidationFailedError("Unsupported emoji reaction")
    return emoji


async def add_reaction(
    db: AsyncSession,
    actor: User,
    org: Organization,
    comment: Comment,
    emoji: str,
    *,
    ip: str | None = None,
) -> CommentReaction:
    emoji = _validate_emoji(emoji)
    repo = ReactionRepository(db)
    existing = await repo.get(comment.id, actor.id, emoji)
    if existing is not None:
        return existing
    reaction = await repo.add(
        CommentReaction(
            organization_id=org.id,
            comment_id=comment.id,
            user_id=actor.id,
            emoji=emoji,
        )
    )
    await audit.log(
        db, AuditAction.REACTION_ADDED, actor_id=actor.id,
        organization_id=org.id, target_type="comment", target_id=comment.id, ip=ip,
        meta={"emoji": emoji},
    )
    await db.commit()
    return reaction


async def remove_reaction(
    db: AsyncSession,
    actor: User,
    org: Organization,
    comment: Comment,
    emoji: str,
    *,
    ip: str | None = None,
) -> None:
    emoji = _validate_emoji(emoji)
    repo = ReactionRepository(db)
    reaction = await repo.get(comment.id, actor.id, emoji)
    if reaction is None:
        raise NotFoundError("Reaction not found")
    await repo.delete(reaction)
    await audit.log(
        db, AuditAction.REACTION_REMOVED, actor_id=actor.id,
        organization_id=org.id, target_type="comment", target_id=comment.id, ip=ip,
        meta={"emoji": emoji},
    )
    await db.commit()


async def summaries_for_comments(
    db: AsyncSession, comment_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[dict]]:
    """Batched reaction rollups: comment_id -> [{emoji, count, user_ids}]."""
    reactions = await ReactionRepository(db).list_for_comments(comment_ids)
    grouped: dict[uuid.UUID, dict[str, list[uuid.UUID]]] = {}
    for reaction in reactions:
        grouped.setdefault(reaction.comment_id, {}).setdefault(reaction.emoji, []).append(
            reaction.user_id
        )
    return {
        comment_id: [
            {"emoji": emoji, "count": len(user_ids), "user_ids": list(user_ids)}
            for emoji, user_ids in by_emoji.items()
        ]
        for comment_id, by_emoji in grouped.items()
    }
