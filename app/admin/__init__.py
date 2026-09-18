"""Admin panel bootstrap.

Mounts a server-rendered admin UI (sqladmin) at `settings.admin_base_url`.
Access requires an active superuser session (`app.admin.auth`); every write is
appended to `audit_logs` (`app.admin.audit`). Disable entirely with
`ADMIN_ENABLED=false`.
"""

from pathlib import Path

from fastapi import FastAPI

from app.admin.audit import AdminAuditBackend
from app.admin.auth import AdminAuth
from app.admin.panel import TeamFlowAdmin
from app.admin.views import ADMIN_VIEWS
from app.core.config import settings
from app.core.db import AsyncSessionLocal, engine

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def setup_admin(app: FastAPI) -> None:
    if not settings.admin_enabled:
        return

    admin = TeamFlowAdmin(
        app=app,
        engine=engine,
        base_url=settings.admin_base_url,
        title=settings.admin_title,
        templates_dir=str(_TEMPLATES_DIR),
        authentication_backend=AdminAuth(),
        audit_backend=AdminAuditBackend(AsyncSessionLocal),
    )
    for view in ADMIN_VIEWS:
        admin.add_view(view)
