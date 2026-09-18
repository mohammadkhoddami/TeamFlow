"""Audit backend: persists every admin create/update/delete to `audit_logs`.

sqladmin calls this on the same request thread that performed the change, so
the admin panel's activity lands in the same immutable trail the API writes.
Sensitive values (password hashes, webhook secrets, tokens) are redacted
before they reach the JSON `meta` column.
"""

import uuid
from typing import Any

from sqladmin.audit import AuditEntry, DBAuditBackend
from starlette.requests import Request

from app.admin.auth import SESSION_USER_KEY
from app.models import AuditAction, AuditLog

_REDACTED = "***"
_SENSITIVE_KEY_PARTS = ("password", "secret", "token", "hashed")

_ACTION_MAP = {
    "create": AuditAction.ADMIN_CREATE,
    "update": AuditAction.ADMIN_UPDATE,
    "delete": AuditAction.ADMIN_DELETE,
}


def _sanitize(value: Any, key: str = "") -> Any:
    if key and any(part in key.lower() for part in _SENSITIVE_KEY_PARTS):
        return _REDACTED
    if isinstance(value, dict):
        return {k: _sanitize(v, k) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class AdminAuditBackend(DBAuditBackend):
    """Maps sqladmin's fixed :class:`AuditEntry` onto the TeamFlow schema."""

    async def get_actor(self, request: Request) -> uuid.UUID | None:
        raw = request.session.get(SESSION_USER_KEY)
        try:
            return uuid.UUID(str(raw))
        except (TypeError, ValueError):
            return None

    def build_row(self, entry: AuditEntry, actor: Any, request: Request) -> AuditLog:
        return AuditLog(
            actor_id=actor,
            action=_ACTION_MAP.get(entry.action, f"admin.{entry.action}"),
            target_type=entry.identity,
            target_id=entry.pk,
            ip=request.client.host if request.client else None,
            meta={"changes": _sanitize(entry.changes or {})},
            created_at=entry.timestamp,
        )
