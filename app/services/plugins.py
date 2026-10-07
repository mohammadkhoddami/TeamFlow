"""Plugin service (M4 ecosystem).

A plugin binds a *directory* entry (or an ad-hoc manifest) to an org with a
webhook URL and the events it subscribes to. `install` returns the signing
secret exactly once; `dispatch_plugins` mirrors `events.dispatch_integrations`
(enqueue-per-plugin, log-and-continue) but stays intentionally simple: plugins
have no delivery ledger, so a broker outage only logs.
"""

import logging
import secrets
import uuid
from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.exceptions import ConflictError, NotFoundError, ValidationFailedError
from app.core.outbound import validate_outbound_url
from app.models import Organization, Plugin, User
from app.services import audit
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

# Built-in catalog of first-party/known plugins. `events` is the default
# subscription set; `scopes` documents what the plugin may act with.
DIRECTORY: list[dict[str, Any]] = [
    {
        "id": "github-issues",
        "name": "GitHub Issues Sync",
        "description": "Two-way sync between TeamFlow tasks and GitHub issues.",
        "author": "TeamFlow",
        "homepage": "https://github.com/teamflow/plugins/tree/main/github-issues",
        "events": ["task.created", "task.updated", "task.completed"],
        "scopes": ["tasks.read", "tasks.write"],
    },
    {
        "id": "slack-relay",
        "name": "Slack Relay",
        "description": "Relay task, comment and membership events into Slack channels.",
        "author": "TeamFlow",
        "homepage": "https://github.com/teamflow/plugins/tree/main/slack-relay",
        "events": ["task.created", "task.updated", "comment.created", "member.joined"],
        "scopes": ["events.read"],
    },
    {
        "id": "standup-digest",
        "name": "Standup Digest",
        "description": "Daily digest of board movement posted to your team chat.",
        "author": "TeamFlow Labs",
        "homepage": "https://github.com/teamflow/plugins/tree/main/standup-digest",
        "events": ["task.created", "task.updated", "task.completed"],
        "scopes": ["tasks.read", "reports.read"],
    },
    {
        "id": "calendar-sync",
        "name": "Calendar Sync",
        "description": "Mirror tasks with due dates into Google Calendar / iCal feeds.",
        "author": "TeamFlow",
        "homepage": "https://github.com/teamflow/plugins/tree/main/calendar-sync",
        "events": ["task.created", "task.updated", "task.deleted"],
        "scopes": ["tasks.read", "calendar.read"],
    },
    {
        "id": "webhook-relay",
        "name": "Generic Webhook Relay",
        "description": "Forward every subscribed event to a custom HTTPS endpoint with HMAC signatures.",
        "author": "TeamFlow",
        "homepage": "https://github.com/teamflow/plugins/tree/main/webhook-relay",
        "events": [
            "task.created",
            "task.updated",
            "task.completed",
            "task.deleted",
            "comment.created",
            "member.joined",
        ],
        "scopes": ["events.read"],
    },
]


def get_directory_entry(catalog_id: str) -> dict[str, Any] | None:
    return next((entry for entry in DIRECTORY if entry["id"] == catalog_id), None)


async def installed_catalog_ids(
    db: AsyncSession, organization_id: uuid.UUID
) -> set[str]:
    plugins = await list_plugins(db, organization_id)
    return {
        (plugin.manifest or {}).get("catalog_id")
        for plugin in plugins
        if (plugin.manifest or {}).get("catalog_id")
    }


async def list_plugins(db: AsyncSession, organization_id: uuid.UUID) -> list[Plugin]:
    statement = (
        select(Plugin)
        .where(Plugin.organization_id == organization_id)
        .order_by(Plugin.created_at.desc())
    )
    return list((await db.execute(statement)).scalars().all())


async def get_plugin_for_org(
    db: AsyncSession, plugin_id: uuid.UUID, organization_id: uuid.UUID
) -> Plugin:
    statement = select(Plugin).where(
        Plugin.id == plugin_id, Plugin.organization_id == organization_id
    )
    plugin = (await db.execute(statement)).scalar_one_or_none()
    if plugin is None:
        raise NotFoundError("Plugin not found")
    return plugin


def _validate_webhook_url(url: str | None) -> str:
    if not url:
        raise ValidationFailedError("A plugin webhook_url (http/https) is required")
    return validate_outbound_url(url)


async def install(
    db: AsyncSession,
    actor: User,
    org: Organization,
    *,
    catalog_id: str | None = None,
    manifest: dict | None = None,
    webhook_url: str | None = None,
    events: list[str] | None = None,
    name: str | None = None,
    description: str | None = None,
    ip: str | None = None,
) -> tuple[Plugin, str]:
    """Installs a plugin and returns (plugin, secret). The secret is shown once."""
    entry: dict[str, Any] | None = None
    if catalog_id:
        entry = get_directory_entry(catalog_id)
        if entry is None:
            raise NotFoundError(f"Unknown plugin: {catalog_id}")

    merged_manifest: dict[str, Any] = {}
    if entry is not None:
        merged_manifest = {
            "catalog_id": entry["id"],
            "author": entry["author"],
            "homepage": entry["homepage"],
        }
    if manifest:
        if not isinstance(manifest, dict):
            raise ValidationFailedError("manifest must be an object")
        merged_manifest.update(manifest)

    plugin_name = name or (entry["name"] if entry else None)
    if not plugin_name:
        raise ValidationFailedError("A plugin name (or catalog_id) is required")
    plugin_description = description or (entry["description"] if entry else None)
    plugin_events = list(
        dict.fromkeys(events if events is not None else (entry["events"] if entry else []))
    )
    scopes = list(merged_manifest.get("scopes") or (entry["scopes"] if entry else []))

    existing = await list_plugins(db, org.id)
    if any(existing_plugin.name == plugin_name for existing_plugin in existing):
        raise ConflictError("A plugin with this name is already installed")

    secret = secrets.token_urlsafe(24)
    plugin = Plugin(
        organization_id=org.id,
        name=plugin_name,
        description=plugin_description,
        manifest=merged_manifest,
        webhook_url=_validate_webhook_url(webhook_url),
        events=plugin_events,
        scopes=scopes,
        secret=secret,
        is_active=True,
        installed_by_id=actor.id,
    )
    db.add(plugin)
    await db.flush()
    await audit.log(
        db, "plugin.installed", actor_id=actor.id,
        organization_id=org.id, target_type="plugin", target_id=plugin.id, ip=ip,
        meta={"name": plugin.name, "catalog_id": merged_manifest.get("catalog_id")},
    )
    await db.commit()
    await db.refresh(plugin)
    return plugin, secret


async def update_plugin(
    db: AsyncSession,
    actor: User,
    org: Organization,
    plugin: Plugin,
    *,
    name: str | None = None,
    description: str | None = None,
    webhook_url: str | None = None,
    events: list[str] | None = None,
    is_active: bool | None = None,
    ip: str | None = None,
) -> Plugin:
    changed: list[str] = []
    if name is not None and name != plugin.name:
        existing = await list_plugins(db, org.id)
        if any(other.name == name and other.id != plugin.id for other in existing):
            raise ConflictError("A plugin with this name is already installed")
        plugin.name = name
        changed.append("name")
    if description is not None:
        plugin.description = description
        changed.append("description")
    if webhook_url is not None:
        plugin.webhook_url = _validate_webhook_url(webhook_url)
        changed.append("webhook_url")
    if events is not None:
        plugin.events = list(dict.fromkeys(events))
        changed.append("events")
    if is_active is not None:
        plugin.is_active = is_active
        changed.append("is_active")
    db.add(plugin)
    await db.flush()
    await audit.log(
        db, "plugin.updated", actor_id=actor.id,
        organization_id=org.id, target_type="plugin", target_id=plugin.id, ip=ip,
        meta={"fields": changed},
    )
    await db.commit()
    await db.refresh(plugin)
    return plugin


async def uninstall(
    db: AsyncSession,
    actor: User,
    org: Organization,
    plugin: Plugin,
    *,
    ip: str | None = None,
) -> None:
    await audit.log(
        db, "plugin.uninstalled", actor_id=actor.id,
        organization_id=org.id, target_type="plugin", target_id=plugin.id, ip=ip,
        meta={"name": plugin.name},
    )
    await db.delete(plugin)
    await db.commit()


async def dispatch_plugins(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    event: str,
    data: dict[str, Any],
) -> None:
    """Enqueue one delivery task per active plugin subscribed to `event`.

    Deliberately simpler than webhook delivery: no durable ledger, failures are
    logged (a broker outage loses plugin events rather than stranding rows).
    """
    plugins = await list_plugins(db, organization_id)
    matching = [
        plugin
        for plugin in plugins
        if plugin.is_active
        and plugin.webhook_url
        and event in (plugin.events or [])
    ]
    for plugin in matching:
        try:
            await run_in_threadpool(
                celery_app.send_task,
                "teamflow.deliver_plugin",
                [str(plugin.id), event, data],
            )
        except Exception:
            logger.exception("Failed to enqueue plugin delivery for %s", plugin.id)
