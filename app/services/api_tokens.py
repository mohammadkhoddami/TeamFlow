"""API tokens, service accounts and OAuth apps (M3 #24).

Auth model:
  - Personal tokens (`tf_...`) inherit their owner's permissions.
  - Service-account tokens belong to a shadow User + Membership, so every
    existing org/project authorization check keeps working; the account's
    scope list further restricts what the token can do.
  - OAuth client_credentials tokens (`tfo_...`) act as the app's creator.

Scope semantics: GET/HEAD/OPTIONS require `read`, everything else `write`.
`admin` (or `*`) implies both. Tokens can carry a per-minute rate budget that
is enforced with a Redis counter (fail-open, like the rest of the limiter).
"""

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import (
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    UnauthorizedError,
    ValidationFailedError,
)
from app.core.redis import get_redis_client
from app.core.security import hash_password, token_urlsafe
from app.models import (
    ApiToken,
    AuditAction,
    Membership,
    MembershipRole,
    OAuthApp,
    OAuthToken,
    Organization,
    ServiceAccount,
    User,
)
from app.repositories import (
    ApiTokenRepository,
    MembershipRepository,
    OAuthAppRepository,
    OAuthTokenRepository,
    ServiceAccountRepository,
    UserRepository,
)
from app.schemas import (
    ApiTokenCreate,
    ApiTokenUpdate,
    OAuthAppCreate,
    OAuthAppUpdate,
    ServiceAccountCreate,
    ServiceAccountUpdate,
)
from app.services import audit, events

TOKEN_PREFIX = "tf_"
OAUTH_TOKEN_PREFIX = "tfo_"
OAUTH_ACCESS_TTL_SECONDS = 3600
READ_METHODS = {"GET", "HEAD", "OPTIONS"}

# How long a token's touch is reused before writing usage back to Postgres.
TOUCH_INTERVAL_SECONDS = 30


def hash_token(plain: str) -> str:
    return hashlib.sha256(plain.encode()).hexdigest()


def _new_secret(prefix: str) -> str:
    return f"{prefix}{secrets.token_urlsafe(32)}"


def _required_scope(method: str) -> str:
    return "read" if method.upper() in READ_METHODS else "write"


def scope_allows(scopes: list[str] | None, required: str) -> bool:
    scopes = scopes or []
    return required in scopes or "admin" in scopes or "*" in scopes


def _require_elevated(membership: Membership, what: str) -> None:
    if membership.role == MembershipRole.MEMBER:
        raise PermissionDeniedError(f"Only managers and above can manage {what}")


async def _enforce_rate_limit(token: ApiToken) -> int:
    """Redis request counter per token/minute. Returns current-minute count."""
    limit = token.rate_limit_per_minute
    minute = int(datetime.now(UTC).timestamp() // 60)
    key = f"teamflow:tok:{token.id}:{minute}"
    try:
        client = get_redis_client()
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, 120)
    except Exception:
        return 0  # fail open: Redis outage must not brick API access
    if limit is not None and int(count) > limit:
        raise RateLimitError(
            detail="Token rate limit exceeded", retry_after=60 - datetime.now(UTC).second
        )
    return int(count)


async def _touch(db: AsyncSession, token: ApiToken) -> None:
    now = datetime.now(UTC)
    last = token.last_used_at
    if last is not None and (now - last).total_seconds() < TOUCH_INTERVAL_SECONDS:
        return
    from sqlalchemy import update

    await db.execute(
        update(ApiToken)
        .where(ApiToken.id == token.id)
        .values(usage_count=ApiToken.usage_count + 1, last_used_at=now)
    )
    await db.commit()
    token.usage_count += 1
    token.last_used_at = now


async def authenticate_token(
    db: AsyncSession, plain: str, *, method: str, path: str
) -> ApiToken:
    """Resolve a personal/service-account token and enforce state + scopes."""
    token = await ApiTokenRepository(db).get_by_hash(hash_token(plain))
    if token is None:
        raise UnauthorizedError("Invalid or expired token")
    if not token.is_active or token.revoked_at is not None:
        raise UnauthorizedError("API token revoked")
    if token.expires_at is not None and token.expires_at <= datetime.now(UTC):
        raise UnauthorizedError("API token expired")
    required = _required_scope(method)
    if not scope_allows(token.scopes, required):
        raise PermissionDeniedError(f"API token lacks the '{required}' scope")
    if token.service_account is not None and not token.service_account.is_active:
        raise UnauthorizedError("Service account is disabled")
    await _enforce_rate_limit(token)
    await _touch(db, token)
    return token


async def authenticate_oauth_token(
    db: AsyncSession, plain: str, *, method: str, path: str
) -> tuple[User, uuid.UUID]:
    """Resolve an OAuth2 access token to (app creator, app organization).

    The returned organization is binding: an app registered in tenant A must
    never act in tenant B, even when its creator happens to be a member of B
    (confused-deputy prevention). Callers enforce it per request."""
    token = await OAuthTokenRepository(db).get_by_hash(hash_token(plain))
    if token is None or not token.is_active:
        raise UnauthorizedError("Invalid or expired token")
    if token.expires_at <= datetime.now(UTC):
        raise UnauthorizedError("OAuth token expired")
    app = token.app
    if app is None or not app.is_active:
        raise UnauthorizedError("OAuth app is disabled")
    required = _required_scope(method)
    if not scope_allows(token.scopes, required):
        raise PermissionDeniedError(f"OAuth token lacks the '{required}' scope")
    if app.created_by_id is None:
        raise UnauthorizedError("OAuth app owner no longer exists")
    user = await db.get(User, app.created_by_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("OAuth app owner is inactive")
    app.last_used_at = datetime.now(UTC)
    await db.commit()
    return user, token.organization_id


# --- tokens ----------------------------------------------------------------


async def create_token(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    data: ApiTokenCreate,
    *,
    ip: str | None = None,
) -> tuple[ApiToken, str]:
    owner = actor
    service_account: ServiceAccount | None = None
    if data.service_account_id is not None:
        _require_elevated(membership, "service-account tokens")
        service_account = await ServiceAccountRepository(db).get_in_org(
            data.service_account_id, org.id
        )
        if service_account is None:
            raise ValidationFailedError("Service account not found in this organization")
        if not service_account.is_active:
            raise ValidationFailedError("Service account is disabled")
        owner = await db.get(User, service_account.user_id)
        if owner is None:
            raise NotFoundError("Service account owner not found")
        invalid = [scope for scope in data.scopes if scope not in (service_account.scopes or [])]
        if invalid:
            raise ValidationFailedError(
                "Token scopes must be a subset of the service account's scopes: "
                + ", ".join(sorted(invalid))
            )

    plain = _new_secret(TOKEN_PREFIX)
    expires_at = (
        datetime.now(UTC) + timedelta(days=data.expires_in_days)
        if data.expires_in_days
        else None
    )
    token = await ApiTokenRepository(db).add(
        ApiToken(
            organization_id=org.id,
            user_id=owner.id,
            service_account_id=service_account.id if service_account else None,
            name=data.name,
            token_prefix=plain[:12],
            token_hash=hash_token(plain),
            scopes=list(dict.fromkeys(data.scopes)),
            rate_limit_per_minute=data.rate_limit_per_minute,
            expires_at=expires_at,
            created_by_id=actor.id,
        )
    )
    await audit.log(
        db, AuditAction.API_TOKEN_CREATED, actor_id=actor.id,
        organization_id=org.id, target_type="api_token", target_id=token.id, ip=ip,
        meta={"name": token.name, "service_account_id": str(service_account.id) if service_account else None},
    )
    await db.commit()
    return token, plain


async def list_tokens(
    db: AsyncSession, org: Organization, *, mine: User | None = None
) -> list[ApiToken]:
    return await ApiTokenRepository(db).list_for_org(
        org.id, user_id=mine.id if mine is not None else None
    )


async def _get_token(db: AsyncSession, org: Organization, token_id: uuid.UUID) -> ApiToken:
    token = await ApiTokenRepository(db).get_in_org(token_id, org.id)
    if token is None:
        raise NotFoundError("API token not found")
    return token


async def update_token(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    token_id: uuid.UUID,
    data: ApiTokenUpdate,
    *,
    ip: str | None = None,
) -> ApiToken:
    token = await _get_token(db, org, token_id)
    # Personal tokens are self-service; other people's tokens need elevated role.
    if token.user_id != actor.id:
        _require_elevated(membership, "other members' API tokens")
    changed = data.model_fields_set
    if "name" in changed and data.name is not None:
        token.name = data.name
    if "scopes" in changed and data.scopes is not None:
        token.scopes = list(dict.fromkeys(data.scopes))
    if "rate_limit_per_minute" in changed:
        token.rate_limit_per_minute = data.rate_limit_per_minute
    if "is_active" in changed and data.is_active is not None:
        token.is_active = data.is_active
        token.revoked_at = None if data.is_active else datetime.now(UTC)
    token = await ApiTokenRepository(db).update(token)
    await db.commit()
    return token


async def rotate_token(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    token_id: uuid.UUID,
) -> tuple[ApiToken, str]:
    token = await _get_token(db, org, token_id)
    # Personal tokens are self-service; any other token (including every
    # service-account token, whose owner is a synthetic user) needs elevated
    # role - otherwise any member could mint a fresh plaintext secret for it.
    if token.user_id != actor.id:
        _require_elevated(membership, "other members' API tokens")
    plain = _new_secret(TOKEN_PREFIX)
    token.token_prefix = plain[:12]
    token.token_hash = hash_token(plain)
    token.is_active = True
    token.revoked_at = None
    token = await ApiTokenRepository(db).update(token)
    await db.commit()
    return token, plain


async def revoke_token(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    token_id: uuid.UUID,
    *,
    ip: str | None = None,
) -> None:
    token = await _get_token(db, org, token_id)
    if token.user_id != actor.id:
        _require_elevated(membership, "other members' API tokens")
    token.is_active = False
    token.revoked_at = datetime.now(UTC)
    await ApiTokenRepository(db).update(token)
    await audit.log(
        db, AuditAction.API_TOKEN_REVOKED, actor_id=actor.id,
        organization_id=org.id, target_type="api_token", target_id=token.id, ip=ip,
        meta={"name": token.name},
    )
    await db.commit()


async def token_usage(db: AsyncSession, org: Organization, token_id: uuid.UUID) -> dict:
    token = await _get_token(db, org, token_id)
    minute = int(datetime.now(UTC).timestamp() // 60)
    count = 0
    try:
        value = await get_redis_client().get(f"teamflow:tok:{token.id}:{minute}")
        count = int(value or 0)
    except Exception:
        count = 0
    return {
        "token_id": token.id,
        "name": token.name,
        "usage_count": token.usage_count,
        "last_used_at": token.last_used_at,
        "rate_limit_per_minute": token.rate_limit_per_minute,
        "requests_last_minute": count,
    }


# --- service accounts ------------------------------------------------------


async def create_service_account(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    data: ServiceAccountCreate,
    *,
    ip: str | None = None,
) -> ServiceAccount:
    _require_elevated(membership, "service accounts")
    # Shadow user: no OTP-able inbox, random password, hidden from rosters.
    shadow = User(
        email=f"sa-{uuid.uuid4().hex}@service.teamflow.local",
        hashed_password=hash_password(_new_secret("nologin_")),
        full_name=data.name,
        is_active=True,
        is_superuser=False,
        is_service_account=True,
    )
    db.add(shadow)
    await db.flush()
    db.add(
        Membership(
            user_id=shadow.id,
            organization_id=org.id,
            role=MembershipRole.MEMBER,
            is_active=True,
        )
    )
    account = await ServiceAccountRepository(db).add(
        ServiceAccount(
            organization_id=org.id,
            user_id=shadow.id,
            name=data.name,
            description=data.description,
            scopes=list(dict.fromkeys(data.scopes)),
            created_by_id=actor.id,
        )
    )
    await audit.log(
        db, AuditAction.SERVICE_ACCOUNT_CREATED, actor_id=actor.id,
        organization_id=org.id, target_type="service_account", target_id=account.id, ip=ip,
        meta={"name": account.name},
    )
    await db.commit()
    return account


async def list_service_accounts(
    db: AsyncSession, org: Organization
) -> list[ServiceAccount]:
    return await ServiceAccountRepository(db).list_for_org(org.id)


async def _get_service_account(
    db: AsyncSession, org: Organization, account_id: uuid.UUID
) -> ServiceAccount:
    account = await ServiceAccountRepository(db).get_in_org(account_id, org.id)
    if account is None:
        raise NotFoundError("Service account not found")
    return account


async def update_service_account(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    account_id: uuid.UUID,
    data: ServiceAccountUpdate,
) -> ServiceAccount:
    _require_elevated(membership, "service accounts")
    account = await _get_service_account(db, org, account_id)
    changed = data.model_fields_set
    if "name" in changed and data.name is not None:
        account.name = data.name
        shadow = await db.get(User, account.user_id)
        if shadow is not None:
            shadow.full_name = data.name
    if "description" in changed:
        account.description = data.description
    if "scopes" in changed and data.scopes is not None:
        account.scopes = list(dict.fromkeys(data.scopes))
    if "is_active" in changed and data.is_active is not None:
        account.is_active = data.is_active
        shadow = await db.get(User, account.user_id)
        if shadow is not None:
            shadow.is_active = data.is_active
    account = await ServiceAccountRepository(db).update(account)
    await db.commit()
    return account


async def delete_service_account(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    account_id: uuid.UUID,
    *,
    ip: str | None = None,
) -> None:
    _require_elevated(membership, "service accounts")
    account = await _get_service_account(db, org, account_id)
    await audit.log(
        db, AuditAction.SERVICE_ACCOUNT_DELETED, actor_id=actor.id,
        organization_id=org.id, target_type="service_account", target_id=account.id, ip=ip,
        meta={"name": account.name},
    )
    # Deleting the shadow user cascades membership + tokens.
    shadow = await db.get(User, account.user_id)
    if shadow is not None:
        await db.delete(shadow)
    await ServiceAccountRepository(db).delete(account)
    await db.commit()


# --- OAuth apps ------------------------------------------------------------


async def create_oauth_app(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    data: OAuthAppCreate,
    *,
    ip: str | None = None,
) -> tuple[OAuthApp, str]:
    _require_elevated(membership, "OAuth apps")
    client_id = _new_secret("tfc_")
    client_secret = _new_secret("tfs_")
    app = await OAuthAppRepository(db).add(
        OAuthApp(
            organization_id=org.id,
            name=data.name,
            description=data.description,
            client_id=client_id[:64],
            client_secret_hash=hash_token(client_secret),
            redirect_uris=list(data.redirect_uris),
            scopes=list(dict.fromkeys(data.scopes)),
            created_by_id=actor.id,
        )
    )
    await audit.log(
        db, AuditAction.OAUTH_APP_CREATED, actor_id=actor.id,
        organization_id=org.id, target_type="oauth_app", target_id=app.id, ip=ip,
        meta={"name": app.name},
    )
    await db.commit()
    return app, client_secret


async def list_oauth_apps(db: AsyncSession, org: Organization) -> list[OAuthApp]:
    return await OAuthAppRepository(db).list_for_org(org.id)


async def _get_oauth_app(
    db: AsyncSession, org: Organization, app_id: uuid.UUID
) -> OAuthApp:
    app = await OAuthAppRepository(db).get_in_org(app_id, org.id)
    if app is None:
        raise NotFoundError("OAuth app not found")
    return app


async def update_oauth_app(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    app_id: uuid.UUID,
    data: OAuthAppUpdate,
) -> OAuthApp:
    _require_elevated(membership, "OAuth apps")
    app = await _get_oauth_app(db, org, app_id)
    changed = data.model_fields_set
    if "name" in changed and data.name is not None:
        app.name = data.name
    if "description" in changed:
        app.description = data.description
    if "redirect_uris" in changed and data.redirect_uris is not None:
        app.redirect_uris = list(data.redirect_uris)
    if "scopes" in changed and data.scopes is not None:
        app.scopes = list(dict.fromkeys(data.scopes))
    if "is_active" in changed and data.is_active is not None:
        app.is_active = data.is_active
    app = await OAuthAppRepository(db).update(app)
    await db.commit()
    return app


async def rotate_oauth_secret(
    db: AsyncSession, actor: User, org: Organization, membership: Membership, app_id: uuid.UUID
) -> tuple[OAuthApp, str]:
    _require_elevated(membership, "OAuth apps")
    app = await _get_oauth_app(db, org, app_id)
    secret = _new_secret("tfs_")
    app.client_secret_hash = hash_token(secret)
    app = await OAuthAppRepository(db).update(app)
    await db.commit()
    return app, secret


async def delete_oauth_app(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    app_id: uuid.UUID,
    *,
    ip: str | None = None,
) -> None:
    _require_elevated(membership, "OAuth apps")
    app = await _get_oauth_app(db, org, app_id)
    await audit.log(
        db, AuditAction.OAUTH_APP_DELETED, actor_id=actor.id,
        organization_id=org.id, target_type="oauth_app", target_id=app.id, ip=ip,
        meta={"name": app.name},
    )
    await OAuthAppRepository(db).delete(app)
    await db.commit()


async def client_credentials_grant(
    db: AsyncSession, *, client_id: str, client_secret: str, scope: str | None = None
) -> tuple[OAuthToken, OAuthApp, str]:
    """OAuth2 client_credentials: machine-to-machine access for registered apps."""
    app = await OAuthAppRepository(db).get_by_client_id(client_id)
    # Client secrets are high-entropy SHA-256 hashes (bcrypt is for passwords).
    if app is None or not hmac.compare_digest(
        hash_token(client_secret), app.client_secret_hash
    ):
        # Constant-ish response: never reveal which part failed.
        raise UnauthorizedError("Invalid client credentials")
    if not app.is_active:
        raise UnauthorizedError("OAuth app is disabled")
    requested = (
        [s for s in scope.split() if s]
        if scope
        else list(app.scopes or ["read"])
    )
    invalid = [s for s in requested if s not in (app.scopes or [])]
    if invalid:
        raise ValidationFailedError(
            "Requested scope exceeds the app's registered scopes: " + ", ".join(invalid)
        )
    plain = _new_secret(OAUTH_TOKEN_PREFIX)
    token = await OAuthTokenRepository(db).add(
        OAuthToken(
            organization_id=app.organization_id,
            app_id=app.id,
            token_hash=hash_token(plain),
            scopes=requested,
            expires_at=datetime.now(UTC) + timedelta(seconds=OAUTH_ACCESS_TTL_SECONDS),
        )
    )
    app.last_used_at = datetime.now(UTC)
    await db.commit()
    return token, app, plain
