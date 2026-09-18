"""Session authentication for the admin panel.

The admin panel deliberately does not reuse API JWTs: browsers cannot set an
`Authorization` header on navigation, so admins log in with email + password
and get a signed session cookie (Starlette `SessionMiddleware`, `httponly` +
`SameSite=Lax` + `Secure` in production).

Only active superusers may pass. Every login attempt is audited, rate limited
per (ip, email), and password verification burns the same bcrypt time whether
or not the account exists (no user enumeration through timing).
"""

import hashlib
import logging
import uuid

from sqladmin.authentication import AuthenticationBackend
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import Response

from app.core import security
from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.core.exceptions import RateLimitError
from app.core.rate_limit import client_ip, hit_rate_limit
from app.core.redis import get_redis_client
from app.models import AuditAction, User
from app.repositories import UserRepository
from app.services import audit

logger = logging.getLogger(__name__)

SESSION_USER_KEY = "admin_user_id"

_dummy_hash: str | None = None


def _session_secret() -> str:
    """Derive an admin-only cookie-signing key from the app secret.

    Key separation: a leak or misuse of the session secret cannot be replayed
    as a JWT signing key (or vice versa).
    """
    digest = hashlib.sha256(
        b"teamflow-admin-session:" + settings.secret_key.encode("utf-8")
    )
    return digest.hexdigest()


def _dummy_password_hash() -> str:
    """Lazily built bcrypt hash used to equalize failed-login timing."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = security.hash_password("teamflow-admin-dummy-password")
    return _dummy_hash


class AdminAuth(AuthenticationBackend):
    def __init__(self) -> None:
        super().__init__(
            secret_key=_session_secret(),
            same_site="lax",
            https_only=settings.is_production,
            max_age=settings.admin_session_max_age_seconds,
        )

    async def _login_rate_limited(self, request: Request, email: str) -> bool:
        if not settings.rate_limit_enabled:
            return False
        try:
            await hit_rate_limit(
                get_redis_client(),
                "admin_login",
                f"{client_ip(request)}:{email}",
                settings.auth_rate_limit_max,
                settings.auth_rate_limit_window,
            )
        except RateLimitError:
            logger.warning("Admin login rate limited ip=%s", client_ip(request))
            return True
        return False

    async def login(self, request: Request) -> Response | bool:
        form = await request.form()
        email = str(form.get("username", "")).strip().lower()
        password = str(form.get("password", ""))
        ip = client_ip(request)
        if not email or not password:
            return False
        if await self._login_rate_limited(request, email):
            return False

        async with AsyncSessionLocal() as db:
            user = await UserRepository(db).get_by_email(email)
            if user is None:
                # Same bcrypt cost as a real account, so response timing does
                # not reveal whether the email exists.
                await run_in_threadpool(
                    security.verify_password, password, _dummy_password_hash()
                )
                await audit.log(
                    db, AuditAction.ADMIN_LOGIN_FAILED, ip=ip, meta={"email": email}
                )
                await db.commit()
                return False

            valid = await run_in_threadpool(
                security.verify_password, password, user.hashed_password
            )
            if not valid or not user.is_active or not user.is_superuser:
                logger.warning("Admin login rejected email=%s ip=%s", email, ip)
                await audit.log(
                    db, AuditAction.ADMIN_LOGIN_FAILED, ip=ip, meta={"email": email}
                )
                await db.commit()
                return False

            await audit.log(
                db,
                AuditAction.ADMIN_LOGIN,
                actor_id=user.id,
                ip=ip,
                meta={"email": user.email},
            )
            await db.commit()

        request.session[SESSION_USER_KEY] = str(user.id)
        return True

    async def authenticate(self, request: Request) -> Response | bool:
        raw = request.session.get(SESSION_USER_KEY)
        if not raw:
            return False
        try:
            user_id = uuid.UUID(str(raw))
        except (TypeError, ValueError):
            request.session.clear()
            return False

        async with AsyncSessionLocal() as db:
            user = await db.get(User, user_id)
        if user is None or not user.is_active or not user.is_superuser:
            request.session.clear()
            return False
        return True

    async def logout(self, request: Request) -> Response | bool:
        raw = request.session.get(SESSION_USER_KEY)
        if raw:
            try:
                user_id = uuid.UUID(str(raw))
            except (TypeError, ValueError):
                user_id = None
            if user_id is not None:
                async with AsyncSessionLocal() as db:
                    await audit.log(
                        db,
                        AuditAction.ADMIN_LOGOUT,
                        actor_id=user_id,
                        ip=client_ip(request),
                    )
                    await db.commit()
        request.session.clear()
        # Falsy return makes sqladmin redirect the browser to the login page.
        return False
