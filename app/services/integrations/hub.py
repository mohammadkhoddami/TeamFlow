"""Third-party integrations (M3 #23).

Inbound VCS webhooks (GitHub/GitLab/Bitbucket) are verified with the
integration secret, matched to tasks by issue key, then linked as task
comments with optional workflow auto-transition. Outbound chat notifications
(Slack/Teams) reuse the durable-row-then-enqueue pattern from webhooks.
Google Calendar subscribes to a tokenized ICS feed.

The webhook receivers are intentionally unauthenticated (third parties cannot
hold JWTs); possession and signature of the integration secret is the auth.
"""

import hashlib
import hmac
import json
import logging
import re
import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import (
    AppError,
    ConflictError,
    NotFoundError,
    UnauthorizedError,
    ValidationFailedError,
)
from app.core.outbound import validate_outbound_url
from app.models import (
    AuditAction,
    Integration,
    IntegrationEvent,
    IntegrationProvider,
    Organization,
    Task,
    User,
)
from app.repositories import IntegrationRepository
from app.schemas import IntegrationCreate, IntegrationUpdate
from app.services import audit, events

logger = logging.getLogger(__name__)

VCS_PROVIDERS = IntegrationProvider.VCS
CHAT_PROVIDERS = IntegrationProvider.CHAT
# Providers whose inbound endpoints are protected by a generated secret.
SECRET_PROVIDERS = VCS_PROVIDERS + (IntegrationProvider.GOOGLE_CALENDAR,)

ISSUE_KEY_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9]{1,9}-\d+)\b")

MAX_MATCHED_TASKS_PER_EVENT = 25


async def create_integration(
    db: AsyncSession,
    actor: User,
    org: Organization,
    data: IntegrationCreate,
    *,
    ip: str | None = None,
) -> tuple[Integration, str | None]:
    if data.provider not in IntegrationProvider.ALL:
        raise ValidationFailedError("Unknown provider")
    _validate_config(data.provider, data.config)
    existing = await IntegrationRepository(db).list_for_org(org.id, provider=data.provider)
    if any(entry.name == data.name for entry in existing):
        raise ConflictError("An integration with this name already exists for the provider")

    secret = secrets.token_urlsafe(24) if data.provider in SECRET_PROVIDERS else None
    integration = await IntegrationRepository(db).add(
        Integration(
            organization_id=org.id,
            provider=data.provider,
            name=data.name,
            config=data.config,
            secret=secret,
            events=list(dict.fromkeys(data.events)),
            created_by_id=actor.id,
        )
    )
    await audit.log(
        db, AuditAction.INTEGRATION_CREATED, actor_id=actor.id,
        organization_id=org.id, target_type="integration", target_id=integration.id, ip=ip,
        meta={"provider": integration.provider, "name": integration.name},
    )
    await db.commit()
    return integration, secret


def _validate_config(provider: str, config: dict) -> None:
    if provider in CHAT_PROVIDERS:
        url = str((config or {}).get("webhook_url", ""))
        if not url:
            raise ValidationFailedError(
                f"{provider} integrations require config.webhook_url (http/https)"
            )
        validate_outbound_url(url)
    if provider in VCS_PROVIDERS:
        auto = (config or {}).get("auto_transition") or {}
        if not isinstance(auto, dict):
            raise ValidationFailedError("config.auto_transition must be an object")
        for key in ("opened", "merged", "push", "closed"):
            if key in auto and not isinstance(auto[key], str):
                raise ValidationFailedError("auto_transition values must be status keys")
    if provider == IntegrationProvider.GOOGLE_CALENDAR:
        pass  # feed token only


async def list_integrations(
    db: AsyncSession, org: Organization, *, provider: str | None = None
) -> list[Integration]:
    return await IntegrationRepository(db).list_for_org(org.id, provider=provider)


async def get_integration_for_org(
    db: AsyncSession, integration_id: uuid.UUID, organization_id: uuid.UUID
) -> Integration:
    integration = await IntegrationRepository(db).get_in_org(integration_id, organization_id)
    if integration is None:
        raise NotFoundError("Integration not found")
    return integration


async def update_integration(
    db: AsyncSession,
    actor: User,
    org: Organization,
    integration: Integration,
    data: IntegrationUpdate,
    *,
    ip: str | None = None,
) -> tuple[Integration, str | None]:
    changed = data.model_fields_set
    rotated_secret: str | None = None
    if "name" in changed and data.name is not None:
        integration.name = data.name
    if "config" in changed and data.config is not None:
        _validate_config(integration.provider, data.config)
        integration.config = data.config
    if "events" in changed and data.events is not None:
        integration.events = list(dict.fromkeys(data.events))
    if "is_active" in changed and data.is_active is not None:
        integration.is_active = data.is_active
    if data.rotate_secret and integration.provider in SECRET_PROVIDERS:
        rotated_secret = secrets.token_urlsafe(24)
        integration.secret = rotated_secret
    integration = await IntegrationRepository(db).update(integration)
    await audit.log(
        db, AuditAction.INTEGRATION_UPDATED, actor_id=actor.id,
        organization_id=org.id, target_type="integration", target_id=integration.id, ip=ip,
        meta={"fields": sorted(changed), "rotated_secret": bool(rotated_secret)},
    )
    await db.commit()
    return integration, rotated_secret


async def delete_integration(
    db: AsyncSession,
    actor: User,
    org: Organization,
    integration: Integration,
    *,
    ip: str | None = None,
) -> None:
    await audit.log(
        db, AuditAction.INTEGRATION_DELETED, actor_id=actor.id,
        organization_id=org.id, target_type="integration", target_id=integration.id, ip=ip,
        meta={"provider": integration.provider, "name": integration.name},
    )
    await IntegrationRepository(db).delete(integration)
    await db.commit()


async def list_events(
    db: AsyncSession,
    org: Organization,
    *,
    integration_id: uuid.UUID | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[IntegrationEvent], int]:
    return await IntegrationRepository(db).list_events(
        org.id, integration_id=integration_id, offset=offset, limit=limit
    )


def webhook_path(integration: Integration) -> str | None:
    if integration.provider in VCS_PROVIDERS:
        return f"/api/v1/integrations/{integration.provider}/{integration.id}"
    return None


def feed_path(integration: Integration) -> str | None:
    if integration.provider == IntegrationProvider.GOOGLE_CALENDAR:
        return f"/api/v1/integrations/google-calendar/{integration.id}/feed.ics"
    return None


# Config values that act as credentials (chat webhook URLs are bearer
# secrets) must never round-trip through read endpoints.
_SECRET_CONFIG_KEYS = ("webhook_url",)


def to_read(integration: Integration) -> dict:
    config = dict(integration.config or {})
    for key in _SECRET_CONFIG_KEYS:
        config.pop(key, None)
    return {
        "id": integration.id,
        "organization_id": integration.organization_id,
        "provider": integration.provider,
        "name": integration.name,
        "config": config,
        "has_webhook_url": bool((integration.config or {}).get("webhook_url")),
        "events": integration.events or [],
        "is_active": integration.is_active,
        "last_event_at": integration.last_event_at,
        "webhook_path": webhook_path(integration),
        "feed_path": feed_path(integration),
        "has_secret": integration.secret is not None,
        "created_at": integration.created_at,
    }


# --- signature verification ------------------------------------------------


def verify_webhook_signature(
    provider: str, secret: str, body: bytes, headers: dict[str, str]
) -> None:
    """Raises UnauthorizedError when the provider signature does not match."""
    normalized = {key.lower(): value for key, value in headers.items()}
    if provider == IntegrationProvider.GITHUB:
        signature = normalized.get("x-hub-signature-256", "")
        expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise UnauthorizedError("Invalid webhook signature")
    elif provider == IntegrationProvider.GITLAB:
        if not hmac.compare_digest(normalized.get("x-gitlab-token", ""), secret):
            raise UnauthorizedError("Invalid webhook token")
    elif provider == IntegrationProvider.BITBUCKET:
        signature = normalized.get("x-hub-signature-256") or normalized.get(
            "x-hub-signature", ""
        )
        if "=" in signature:
            signature = signature.split("=", 1)[1]
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise UnauthorizedError("Invalid webhook signature")
    else:
        raise ValidationFailedError("Provider does not accept inbound webhooks")


# --- inbound event processing ----------------------------------------------


def _extract_issue_keys(*values: Any) -> list[str]:
    keys: list[str] = []
    for value in values:
        if not value:
            continue
        for match in ISSUE_KEY_RE.findall(str(value)):
            key = match.upper()
            if key not in keys:
                keys.append(key)
    return keys[:MAX_MATCHED_TASKS_PER_EVENT]


def _normalize_event(provider: str, event_type: str, payload: dict) -> dict:
    """Provider payload -> {kind, action, ref, title, url, keys}."""
    if provider == IntegrationProvider.GITHUB:
        if event_type == "pull_request":
            pr = payload.get("pull_request") or {}
            action = payload.get("action", "")
            merged = bool(pr.get("merged"))
            normalized = "merged" if action == "closed" and merged else (
                "closed" if action == "closed" else "opened"
            )
            return {
                "kind": "pull_request",
                "action": normalized,
                "ref": str(pr.get("number", "")),
                "title": pr.get("title") or f"PR #{pr.get('number')}",
                "url": pr.get("html_url"),
                "keys": _extract_issue_keys(pr.get("title"), pr.get("body"), pr.get("head", {}).get("ref")),
            }
        if event_type == "push":
            commits = payload.get("commits") or []
            return {
                "kind": "commit",
                "action": "push",
                "ref": str(payload.get("after", ""))[:12],
                "title": commits[-1].get("message", "") if commits else "push",
                "url": payload.get("compare") or commits[-1].get("url") if commits else None,
                "keys": _extract_issue_keys(
                    *[commit.get("message") for commit in commits],
                    payload.get("ref"),
                ),
            }
    if provider == IntegrationProvider.GITLAB:
        if event_type in ("merge_request", "Merge Request Hook"):
            attrs = payload.get("object_attributes") or {}
            action = "merged" if attrs.get("state") == "merged" else (
                "closed" if attrs.get("state") == "closed" else "opened"
            )
            return {
                "kind": "merge_request",
                "action": action,
                "ref": str(attrs.get("iid", "")),
                "title": attrs.get("title") or f"MR !{attrs.get('iid')}",
                "url": attrs.get("url"),
                "keys": _extract_issue_keys(
                    attrs.get("title"), attrs.get("description"), attrs.get("source_branch")
                ),
            }
        if event_type in ("push", "Push Hook"):
            commits = payload.get("commits") or []
            return {
                "kind": "commit",
                "action": "push",
                "ref": str(payload.get("after", ""))[:12],
                "title": commits[-1].get("message", "") if commits else "push",
                "url": commits[-1].get("url") if commits else None,
                "keys": _extract_issue_keys(
                    *[commit.get("message") for commit in commits], payload.get("ref")
                ),
            }
    if provider == IntegrationProvider.BITBUCKET:
        if event_type.startswith("pullrequest:"):
            pr = payload.get("pullrequest") or {}
            merged = event_type == "pullrequest:fulfilled"
            action = "merged" if merged else (
                "closed" if event_type == "pullrequest:rejected" else "opened"
            )
            return {
                "kind": "pull_request",
                "action": action,
                "ref": str(pr.get("id", "")),
                "title": pr.get("title") or f"PR #{pr.get('id')}",
                "url": (pr.get("links") or {}).get("html", {}).get("href"),
                "keys": _extract_issue_keys(
                    pr.get("title"), pr.get("description"),
                    (pr.get("source") or {}).get("branch", {}).get("name"),
                ),
            }
        if event_type == "repo:push":
            changes = ((payload.get("push") or {}).get("changes")) or []
            messages = []
            for change in changes:
                for commit in (change.get("commits") or []):
                    messages.append(commit.get("message"))
            return {
                "kind": "commit",
                "action": "push",
                "ref": "",
                "title": next((m for m in messages if m), "push"),
                "url": None,
                "keys": _extract_issue_keys(*messages),
            }
    return {"kind": event_type, "action": "unknown", "ref": "", "title": "", "url": None, "keys": []}


async def handle_vcs_webhook(
    db: AsyncSession,
    integration: Integration,
    *,
    event_type: str,
    payload: dict,
    body: bytes,
) -> dict:
    """Match issue keys in the payload, link results, maybe auto-transition."""
    normalized = _normalize_event(integration.provider, event_type, payload)
    keys = normalized["keys"]
    if not keys:
        event = await IntegrationRepository(db).add_event(
            IntegrationEvent(
                organization_id=integration.organization_id,
                integration_id=integration.id,
                direction="inbound",
                event_type=event_type,
                status="ignored",
                detail="No issue keys found in payload",
            )
        )
        integration.last_event_at = datetime.now(UTC)
        await db.commit()
        return {"matched": 0, "event_id": str(event.id)}

    tasks = list(
        (
            await db.execute(
                select(Task).where(
                    Task.organization_id == integration.organization_id,
                    Task.key.in_(keys),
                    Task.archived_at.is_(None),
                )
            )
        ).scalars().all()
    )

    actor = None
    if integration.created_by_id is not None:
        actor = await db.get(User, integration.created_by_id)

    linked: list[str] = []
    transitions: list[str] = []
    failures: list[str] = []
    if tasks and actor is not None:
        from app.schemas import CommentCreate, TaskUpdate
        from app.services import comments as comment_service
        from app.services import tasks as task_service

        target_status = (integration.config or {}).get("auto_transition", {}).get(
            normalized["action"]
        )
        for task in tasks:
            link_label = normalized["kind"].replace("_", " ")
            ref = f" #{normalized['ref']}" if normalized["ref"] else ""
            url = normalized["url"]
            title = normalized["title"] or normalized["ref"] or "link"
            body = (
                f"Linked {link_label}{ref}: "
                + (f"[{title}]({url})" if url else title)
                + f" via {integration.provider} integration."
            )
            try:
                await comment_service.create_comment(
                    db, actor, integration.organization, task,
                    CommentCreate(body=body),
                    run_automations=False,
                )
                linked.append(task.key or str(task.id))
            except Exception as exc:  # noqa: BLE001 - log and continue
                logger.exception("Failed to link %s to %s", task.key, normalized)
                failures.append(f"{task.key}: link failed ({exc})")
                continue
            if target_status and target_status != task.status:
                try:
                    await task_service.move_task(
                        db, actor, integration.organization, task,
                        target_status, run_automations=False,
                    )
                    transitions.append(f"{task.key}->{target_status}")
                except AppError as exc:
                    failures.append(f"{task.key}: transition failed ({exc.detail})")
                except Exception:  # noqa: BLE001
                    logger.exception("Auto-transition failed for %s", task.key)
                    failures.append(f"{task.key}: transition failed")

    event = await IntegrationRepository(db).add_event(
        IntegrationEvent(
            organization_id=integration.organization_id,
            integration_id=integration.id,
            direction="inbound",
            event_type=event_type,
            status="delivered" if linked else "ignored",
            detail="; ".join([*linked, *transitions, *failures])[:2000] or "No tasks matched",
            data={
                "keys": keys,
                "action": normalized["action"],
                "kind": normalized["kind"],
            },
        )
    )
    integration.last_event_at = datetime.now(UTC)
    await db.commit()
    return {
        "matched": len(tasks),
        "linked": linked,
        "transitions": transitions,
        "failures": failures,
        "event_id": str(event.id),
    }


# --- Google Calendar ICS feed ----------------------------------------------

ICS_HEADER = (
    "BEGIN:VCALENDAR\r\n"
    "VERSION:2.0\r\n"
    "PRODID:-//TeamFlow//Calendar//EN\r\n"
    "CALSCALE:GREGORIAN\r\n"
    "METHOD:PUBLISH\r\n"
    "X-WR-CALNAME:{name}\r\n"
)


def format_chat_message(event_type: str, payload: dict) -> str:
    """Human-readable Slack/Teams message for a TeamFlow event."""
    from app.core.config import settings

    key = payload.get("key") or ""
    title = payload.get("title") or "a task"
    status = payload.get("status") or ""
    priority = payload.get("priority") or ""
    project_id = payload.get("project_id")
    link = (
        f"{settings.frontend_base_url.rstrip('/')}/org/-/projects/{project_id}"
        if project_id
        else settings.frontend_base_url
    )
    prefix = f"[{key}] " if key else ""
    if event_type == "task.created":
        return f"🆕 {prefix}{title} created ({priority} priority) — {link}"
    if event_type == "task.completed":
        return f"✅ {prefix}{title} completed — {link}"
    if event_type == "task.updated":
        return f"🔄 {prefix}{title} updated (status: {status}) — {link}"
    if event_type == "comment.created":
        return f"💬 New comment on {prefix}{title} — {link}"
    if event_type == "member.joined":
        return f"👋 {payload.get('email', 'A new member')} joined the workspace"
    return f"TeamFlow event {event_type}: {prefix}{title}"


def _ics_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


async def load_feed_tasks(
    db: AsyncSession, integration: Integration
) -> tuple[list[Task], dict[uuid.UUID, str]]:
    """Tasks with due dates for the ICS feed (bounded, next/previous 12 months)."""
    from app.models import Project

    conds = [
        Task.organization_id == integration.organization_id,
        Task.due_date.is_not(None),
        Task.archived_at.is_(None),
    ]
    rows = (
        await db.execute(
            select(Task, Project.name)
            .join(Project, Project.id == Task.project_id)
            .where(*conds)
            .order_by(Task.due_date.asc())
            .limit(2000)
        )
    ).all()
    tasks = [row[0] for row in rows]
    names = {row[0].project_id: row[1] for row in rows}
    return tasks, names


def build_ics(integration: Integration, tasks: list[Task], project_names: dict[uuid.UUID, str]) -> str:
    """All-day VEVENTs for tasks with due dates (subscribable by Google Calendar)."""
    org_name = integration.organization.name if integration.organization else "TeamFlow"
    lines = [ICS_HEADER.format(name=_ics_escape(f"{org_name} — TeamFlow"))]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    for task in tasks:
        if task.due_date is None:
            continue
        day = task.due_date.strftime("%Y%m%d")
        end_day = task.due_date.strftime("%Y%m%d")
        project_name = project_names.get(task.project_id, "")
        summary = f"{task.key or 'Task'}: {task.title}"
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{task.id}@teamflow",
                f"DTSTAMP:{stamp}",
                f"DTSTART;VALUE=DATE:{day}",
                f"DTEND;VALUE=DATE:{end_day}",
                f"SUMMARY:{_ics_escape(summary)}",
                f"DESCRIPTION:{_ics_escape(f'{project_name}\\nStatus: {task.status}\\nPriority: {task.priority}')}",
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
