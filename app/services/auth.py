"""Auth service: registration, login, rotation, revocation, password reset.

Token strategy: stateless short-lived access JWTs + stateful refresh tokens
(jti whitelisted in Redis). Rotation on every refresh; reuse of a dead jti
revokes the whole token family (stolen-token containment). Password reset
tokens are single-use, hashed at rest in Redis, 30-minute TTL.
"""

import logging
import uuid
from datetime import timedelta

import jwt
from redis.asyncio import Redis
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core import security
from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError, UnauthorizedError
from app.core.rate_limit import hit_rate_limit
from app.models import AuditAction, User
from app.repositories import UserRepository
from app.schemas import (
    PasswordForgot,
    PasswordReset,
    RefreshedToken,
    Token,
    UserCreate,
    UserUpdate,
)
from app.services import audit, token_store

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


async def register_user(db: AsyncSession, data: UserCreate, ip: str | None = None) -> User:
    repo = UserRepository(db)
    if await repo.get_by_email(data.email):
        raise ConflictError("A user with this email already exists")
    user = User(
        email=data.email,
        full_name=data.full_name,
        hashed_password=security.hash_password(data.password),
    )
    user = await repo.add(user)
    await audit.log(
        db, AuditAction.USER_REGISTERED, actor_id=user.id, ip=ip, meta={"email": user.email},
    )
    await db.commit()
    await db.refresh(user)
    return user


async def login(
    db: AsyncSession, redis: Redis, email: str, password: str, ip: str | None = None
) -> Token:
    # Per-identity limit first: floods and credential stuffing burn quota
    # before any bcrypt work happens.
    await hit_rate_limit(
        redis, "auth_email", email.lower(), settings.auth_rate_limit_max, settings.auth_rate_limit_window
    )

    user = await UserRepository(db).get_by_email(email)
    if not user or not security.verify_password(password, user.hashed_password):
        await audit.log(
            db, AuditAction.USER_LOGIN_FAILED, ip=ip, meta={"email": email},
        )
        await db.commit()
        # Deliberately vague: never reveal whether the email exists.
        raise UnauthorizedError("Incorrect email or password")
    if not user.is_active:
        raise UnauthorizedError("Account is deactivated")

    refresh = _refresh_token(user)
    jti = jwt.decode(
        refresh, settings.secret_key, algorithms=[settings.jwt_algorithm]
    )["jti"]
    await token_store.store_refresh_token(
        redis, str(user.id), jti, REFRESH_TOKEN_EXPIRE_SECONDS
    )
    await audit.log(
        db, AuditAction.USER_LOGIN, actor_id=user.id, ip=ip, meta={"email": email},
    )
    await db.commit()
    return Token(access_token=_access_token(user), refresh_token=refresh)


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

    user.hashed_password = security.hash_password(data.new_password)
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
    if data.email is not None and data.email != user.email:
        if await repo.get_by_email(data.email):
            raise ConflictError("A user with this email already exists")
        user.email = data.email

    user = await repo.update(user)
    await db.commit()
    return user
