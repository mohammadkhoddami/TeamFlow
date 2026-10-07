"""Auth service: registration, login, rotation, revocation, password reset.

Token strategy: stateless short-lived access JWTs + stateful refresh tokens
(jti whitelisted in Redis). Rotation on every refresh; reuse of a dead jti
revokes the whole token family (stolen-token containment). Password reset
tokens are single-use, hashed at rest in Redis, 30-minute TTL.
"""

import logging
import secrets
import uuid
from datetime import timedelta

import jwt
from redis.asyncio import Redis
from sqlalchemy.exc import IntegrityError
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core import security
from app.core.config import settings
from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    UnauthorizedError,
    ValidationFailedError,
)
from app.core.rate_limit import hit_rate_limit
from app.models import AuditAction, User
from app.repositories import UserRepository
from app.schemas import (
    OtpRequest,
    OtpVerify,
    PasswordForgot,
    PasswordReset,
    RefreshedToken,
    Token,
    UserCreate,
    UserUpdate,
)
from app.services import audit, mfa, token_store
from app.services.integrations import google_oauth

logger = logging.getLogger(__name__)

ACCESS_TOKEN_EXPIRE_SECONDS = settings.access_token_expire_minutes * 60
REFRESH_TOKEN_EXPIRE_SECONDS = settings.refresh_token_expire_days * 24 * 3600
PASSWORD_RESET_TTL_SECONDS = 30 * 60


def _access_token(user: User) -> str:
    return security.create_token(
        str(user.id),
        security.TOKEN_TYPE_ACCESS,
        timedelta(seconds=ACCESS_TOKEN_EXPIRE_SECONDS),
    )


def _refresh_token(user: User) -> str:
    return security.create_token(
        str(user.id),
        security.TOKEN_TYPE_REFRESH,
        timedelta(days=settings.refresh_token_expire_days),
        extra_claims={"jti": str(uuid.uuid4())},
    )


async def _start_session(
    db: AsyncSession,
    redis: Redis,
    user: User,
    action: str,
    ip: str | None = None,
    meta: dict | None = None,
) -> Token:
    """Mints a token pair and records the login. Shared by every credential
    type (password, email OTP, Google) so token lifecycle stays identical."""
    refresh = _refresh_token(user)
    jti = jwt.decode(
        refresh, settings.secret_key, algorithms=[settings.jwt_algorithm]
    )["jti"]
    await token_store.store_refresh_token(
        redis, str(user.id), jti, REFRESH_TOKEN_EXPIRE_SECONDS
    )
    await audit.log(
        db, action, actor_id=user.id, ip=ip, meta=meta or {"email": user.email},
    )
    await db.commit()
    return Token(access_token=_access_token(user), refresh_token=refresh)


async def _unusable_password() -> str:
    """Random password hash for accounts created without one (OTP / Google).
    They can set a real password later via the reset flow; until then password
    login is impossible."""
    return await run_in_threadpool(
        security.hash_password, secrets.token_urlsafe(32)
    )


async def register_user(
    db: AsyncSession, redis: Redis, data: UserCreate, ip: str | None = None
) -> User:
    repo = UserRepository(db)
    email = data.email.lower()
    if await repo.get_by_email(email):
        raise ConflictError("A user with this email already exists")
    # The account is only created once the code emailed by /auth/otp/request
    # is redeemed. The check is single-use and wrong-attempt-capped, so a
    # registration cannot silently claim an address.
    if not await token_store.verify_otp(
        redis, email, data.code, settings.otp_max_attempts
    ):
        await audit.log(
            db, AuditAction.USER_OTP_FAILED, ip=ip,
            meta={"email": email, "context": "register"},
        )
        await db.commit()
        raise UnauthorizedError("Invalid or expired code")
    # bcrypt is CPU-bound and blocking; run it off the event loop.
    hashed = await run_in_threadpool(security.hash_password, data.password)
    user = User(
        email=email,
        full_name=data.full_name,
        hashed_password=hashed,
    )
    user = await repo.add(user)
    await audit.log(
        db, AuditAction.USER_REGISTERED, actor_id=user.id, ip=ip, meta={"email": user.email},
    )
    await db.commit()
    await db.refresh(user)
    logger.info("Registered %s after OTP verification", email)
    return user


async def login(
    db: AsyncSession, redis: Redis, email: str, password: str, ip: str | None = None
) -> dict:
    # Per-identity limit first: floods and credential stuffing burn quota
    # before any bcrypt work happens.
    await hit_rate_limit(
        redis, "auth_email", email.lower(), settings.auth_rate_limit_max, settings.auth_rate_limit_window
    )

    user = await UserRepository(db).get_by_email(email.lower())
    # bcrypt verify is blocking: offload it so one login cannot stall the worker.
    password_ok = user is not None and await run_in_threadpool(
        security.verify_password, password, user.hashed_password
    )
    if not password_ok:
        await audit.log(
            db, AuditAction.USER_LOGIN_FAILED, ip=ip, meta={"email": email},
        )
        await db.commit()
        # Deliberately vague: never reveal whether the email exists.
        raise UnauthorizedError("Incorrect email or password")
    if not user.is_active:
        raise UnauthorizedError("Account is deactivated")

    # MFA users get a one-time challenge instead of tokens; /auth/mfa/verify
    # consumes it and only then mints the session. OTP and Google logins are
    # documented as not MFA-gated (they authenticate a different factor).
    if await mfa.enabled(db, user.id):
        token = await mfa.store_login_token(redis, str(user.id))
        logger.info("MFA challenge issued for %s", user.email)
        return {"mfa_required": True, "mfa_token": token}

    session = await _start_session(db, redis, user, AuditAction.USER_LOGIN, ip=ip)
    return session.model_dump()


async def complete_mfa_login(
    db: AsyncSession, redis: Redis, mfa_token: str, code: str, ip: str | None = None
) -> Token:
    """Second step of a password login: redeems the Redis challenge token and
    a TOTP (or single-use recovery) code, then mints the usual token pair via
    the shared session helper so refresh-token lifecycle stays identical."""
    user_id = await mfa.consume_login_token(redis, mfa_token)
    if not user_id:
        raise UnauthorizedError("Invalid or expired MFA token")
    try:
        user = await UserRepository(db).get(uuid.UUID(user_id))
    except ValueError:
        raise UnauthorizedError("Invalid or expired MFA token") from None
    if not user or not user.is_active:
        raise UnauthorizedError("User no longer active")

    if not await mfa.verify_login_code(db, user, code):
        await audit.log(
            db, "user.mfa_failed", ip=ip, meta={"email": user.email},
        )
        await db.commit()
        raise UnauthorizedError("Invalid authentication code")

    return await _start_session(
        db, redis, user, AuditAction.USER_LOGIN, ip=ip,
        meta={"email": user.email, "mfa": True},
    )


async def refresh_tokens(db: AsyncSession, redis: Redis, refresh_token: str) -> RefreshedToken:
    try:
        payload = security.decode_token(refresh_token)
    except jwt.PyJWTError:
        raise UnauthorizedError("Invalid refresh token") from None

    if payload.get("type") != security.TOKEN_TYPE_REFRESH:
        raise UnauthorizedError("Wrong token type; refresh requires a refresh token")
    jti = payload.get("jti")
    user_id = payload.get("sub")
    if not jti or not user_id:
        raise UnauthorizedError("Invalid refresh token")

    user = await UserRepository(db).get(uuid.UUID(user_id))
    if not user or not user.is_active:
        raise UnauthorizedError("User no longer active")

    # Rotation: the presented token must still be whitelisted. A jti that is
    # gone means either expiry/rotation (normal) or replay of an old token
    # (attack) — we cannot tell which, so we burn the whole family.
    if not await token_store.is_refresh_token_active(redis, user_id, jti):
        await token_store.revoke_all_refresh_tokens(redis, user_id)
        logger.warning("Refresh token reuse detected; revoked session for user %s", user_id)
        raise UnauthorizedError("Refresh token expired or reused; please log in again")

    await token_store.revoke_refresh_token(redis, user_id, jti)
    new_refresh = _refresh_token(user)
    new_jti = jwt.decode(
        new_refresh, settings.secret_key, algorithms=[settings.jwt_algorithm]
    )["jti"]
    await token_store.store_refresh_token(
        redis, user_id, new_jti, REFRESH_TOKEN_EXPIRE_SECONDS
    )
    await db.commit()
    return RefreshedToken(access_token=_access_token(user), refresh_token=new_refresh)


async def logout(redis: Redis, refresh_token: str) -> None:
    """Revokes exactly the presented refresh token. An invalid token is a
    no-op: logout must succeed even if the client already rotated."""
    try:
        payload = security.decode_token(refresh_token)
    except jwt.PyJWTError:
        return
    if payload.get("type") != security.TOKEN_TYPE_REFRESH:
        return
    user_id, jti = payload.get("sub"), payload.get("jti")
    if user_id and jti:
        await token_store.revoke_refresh_token(redis, user_id, jti)


async def logout_all(redis: Redis, user: User) -> None:
    await token_store.revoke_all_refresh_tokens(redis, str(user.id))


async def request_password_reset(
    db: AsyncSession, redis: Redis, data: PasswordForgot, ip: str | None = None
) -> None:
    """Always returns success semantics: no user enumeration via this route.
    Emails are sent asynchronously by Celery; the token lives only in Redis."""
    user = await UserRepository(db).get_by_email(data.email)
    await audit.log(
        db, AuditAction.PASSWORD_RESET_REQUESTED, ip=ip,
        meta={"email": data.email, "known_account": user is not None},
    )
    await db.commit()
    if not user or not user.is_active:
        return

    token = security.token_urlsafe()
    await token_store.store_password_reset_token(
        redis, token, str(user.id), PASSWORD_RESET_TTL_SECONDS
    )
    link = f"{settings.frontend_base_url}/reset-password?token={token}"
    from app.workers.celery_app import celery_app

    await run_in_threadpool(
        celery_app.send_task,
        "teamflow.send_email",
        [data.email, "password_reset", {"reset_link": link}],
    )


async def reset_password(db: AsyncSession, redis: Redis, data: PasswordReset, ip: str | None = None) -> None:
    user_id = await token_store.consume_password_reset_token(redis, data.token)
    if not user_id:
        raise UnauthorizedError("Invalid or expired reset token")

    user = await UserRepository(db).get(uuid.UUID(user_id))
    if not user:
        raise NotFoundError("User not found")

    user.hashed_password = await run_in_threadpool(
        security.hash_password, data.new_password
    )
    await UserRepository(db).update(user)
    # Every session dies with the password: best-practice defense.
    await token_store.revoke_all_refresh_tokens(redis, user_id)
    await audit.log(
        db, AuditAction.PASSWORD_RESET, actor_id=user.id, ip=ip, meta={"email": user.email},
    )
    await db.commit()


async def update_user(db: AsyncSession, user_id: uuid.UUID, data: UserUpdate) -> User:
    repo = UserRepository(db)
    user = await repo.get(user_id)
    if not user:
        raise NotFoundError("User not found")

    if data.full_name is not None:
        user.full_name = data.full_name
    if data.email is not None and data.email.lower() != user.email:
        if await repo.get_by_email(data.email.lower()):
            raise ConflictError("A user with this email already exists")
        user.email = data.email.lower()
    if data.locale is not None:
        if data.locale not in ("en", "fa"):
            raise ValidationFailedError("Unsupported locale")
        user.locale = data.locale

    user = await repo.update(user)
    await db.commit()
    return user


# ---------------------------------------------------------------- email OTP


async def request_otp(
    db: AsyncSession, redis: Redis, data: OtpRequest, ip: str | None = None
) -> None:
    """Sends a 6-digit sign-in code. The response never reveals whether the
    email belongs to an account (verification creates one when new)."""
    email = data.email.lower()
    # Per-identity first so one mailbox cannot be flooded; the route adds the
    # per-IP cap on top.
    await hit_rate_limit(
        redis,
        "otp_email",
        email,
        settings.otp_request_rate_limit_max,
        settings.otp_request_rate_limit_window,
    )

    code = f"{secrets.randbelow(1_000_000):06d}"
    await token_store.store_otp(redis, email, code, settings.otp_ttl_seconds)

    user = await UserRepository(db).get_by_email(email)
    await audit.log(
        db, AuditAction.USER_OTP_REQUESTED, ip=ip,
        meta={"email": email, "known_account": user is not None},
    )
    await db.commit()

    from app.workers.celery_app import celery_app

    await run_in_threadpool(
        celery_app.send_task,
        "teamflow.send_email",
        [
            email,
            "otp_code",
            {"code": code, "expires_minutes": max(1, settings.otp_ttl_seconds // 60)},
        ],
    )
    logger.info(
        "Queued OTP email for %s (known_account=%s, expires in %ss)",
        email,
        user is not None,
        settings.otp_ttl_seconds,
    )


async def verify_otp(
    db: AsyncSession, redis: Redis, data: OtpVerify, ip: str | None = None
) -> Token:
    email = data.email.lower()
    if not await token_store.verify_otp(
        redis, email, data.code, settings.otp_max_attempts
    ):
        await audit.log(db, AuditAction.USER_OTP_FAILED, ip=ip, meta={"email": email})
        await db.commit()
        # Deliberately vague: the same error covers expiry, wrong code, and
        # a missing account.
        raise UnauthorizedError("Invalid or expired code")

    repo = UserRepository(db)
    user = await repo.get_by_email(email)
    if user is None:
        # First successful OTP verification creates the account.
        user = User(
            email=email, full_name="", hashed_password=await _unusable_password()
        )
        try:
            user = await repo.add(user)
        except IntegrityError:
            # A concurrent verification created the account first; log in.
            await db.rollback()
            user = await repo.get_by_email(email)
            if user is None:
                raise
        else:
            await audit.log(
                db, AuditAction.USER_REGISTERED, actor_id=user.id, ip=ip,
                meta={"email": email, "method": "otp"},
            )
    if not user.is_active:
        raise UnauthorizedError("Account is deactivated")

    return await _start_session(
        db, redis, user, AuditAction.USER_LOGIN_OTP, ip=ip,
        meta={"email": email, "method": "otp"},
    )


# ------------------------------------------------------------- Google OAuth


async def start_google_oauth(redis: Redis, redirect_uri: str) -> str:
    """Stores one-time state + PKCE verifier, returns the Google consent URL."""
    state = google_oauth.generate_state()
    verifier = google_oauth.generate_code_verifier()
    await token_store.store_oauth_state(
        redis,
        state,
        {"verifier": verifier, "redirect_uri": redirect_uri},
        settings.oauth_state_ttl_seconds,
    )
    return google_oauth.authorize_url(
        redirect_uri, state, google_oauth.code_challenge(verifier)
    )


async def google_callback(
    db: AsyncSession, redis: Redis, code: str, state: str, ip: str | None = None
) -> str:
    """Validates the Google callback and returns a one-time hand-off code for
    the frontend — tokens never travel in a redirect URL (history/referrer
    leaks, shared caches)."""
    state_data = await token_store.consume_oauth_state(redis, state)
    if not state_data:
        raise UnauthorizedError("Invalid or expired OAuth state")

    id_token = await google_oauth.exchange_code(
        code, state_data["redirect_uri"], state_data["verifier"]
    )
    identity = await run_in_threadpool(google_oauth.verify_id_token, id_token)
    if not identity.sub or not identity.email:
        raise UnauthorizedError("Google account has no email address")
    if not identity.email_verified:
        raise UnauthorizedError("Google account email is not verified")

    user = await _find_or_create_google_user(db, identity, ip=ip)
    if not user.is_active:
        raise UnauthorizedError("Account is deactivated")
    # The exchange request opens its own session, so the new/linked user and
    # the audit entry must be durable before the hand-off code is issued.
    await db.commit()

    handoff = security.token_urlsafe()
    await token_store.store_oauth_login_code(
        redis, handoff, str(user.id), settings.oauth_login_code_ttl_seconds
    )
    return handoff


async def _find_or_create_google_user(
    db: AsyncSession, identity: google_oauth.GoogleIdentity, ip: str | None = None
) -> User:
    repo = UserRepository(db)
    # The stable Google subject wins over email: an email change on either
    # side must not silently rebind the account.
    user = await repo.get_by_google_id(identity.sub)
    if user is None:
        user = await repo.get_by_email(identity.email)
    if user is None:
        user = User(
            email=identity.email,
            full_name=identity.name[:255],
            hashed_password=await _unusable_password(),
            google_id=identity.sub,
        )
        try:
            user = await repo.add(user)
        except IntegrityError:
            # Two first-time callbacks raced; the loser just logs in.
            await db.rollback()
            user = await repo.get_by_google_id(identity.sub) or await repo.get_by_email(
                identity.email
            )
            if user is None:
                raise
            return user
        await audit.log(
            db, AuditAction.USER_REGISTERED, actor_id=user.id, ip=ip,
            meta={"email": identity.email, "method": "google"},
        )
        return user

    if user.google_id is None:
        user.google_id = identity.sub
        await repo.update(user)
        await audit.log(
            db, AuditAction.USER_GOOGLE_LINKED, actor_id=user.id, ip=ip,
            meta={"email": user.email, "google_id": identity.sub},
        )
    return user


async def exchange_oauth_login_code(
    db: AsyncSession, redis: Redis, code: str, ip: str | None = None
) -> Token:
    """Turns the one-time OAuth hand-off code into a real token pair."""
    user_id = await token_store.consume_oauth_login_code(redis, code)
    if not user_id:
        raise UnauthorizedError("Invalid or expired login code")
    user = await UserRepository(db).get(uuid.UUID(user_id))
    if not user or not user.is_active:
        raise UnauthorizedError("User no longer active")
    return await _start_session(
        db, redis, user, AuditAction.USER_LOGIN_GOOGLE, ip=ip,
        meta={"email": user.email, "method": "google"},
    )
