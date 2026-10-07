"""OIDC SSO service (M4 enterprise identity).

Flow (authorization code + PKCE, mirroring the Google integration):
  1. `/auth/sso/{slug}/start` -> `start_authorize()` discovers the IdP
     (cached in Redis for an hour), builds the consent URL with state + nonce
     + S256 PKCE, and stashes the verifier in Redis for 10 minutes.
  2. The IdP redirects to `/auth/sso/callback` -> `config_for_state()` peeks at
     the pending state to resolve the org config, then `complete_callback()`
     consumes the state (single-use GETDEL), exchanges the code
     (client_secret_post), verifies the id_token via JWKS (RS256/ES256), and
     resolves the local user + membership.
  3. The SPA hand-off code is stored through the *same* token_store mechanism
     as Google login, so `/auth/oauth/exchange` works unchanged and tokens
     never travel in a redirect URL.
"""

import base64
import hashlib
import hmac
import json
import logging
import secrets
import uuid
from functools import lru_cache
from urllib.parse import urlencode

import httpx
import jwt
from redis.asyncio import Redis
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core import security
from app.core.config import settings
from app.core.exceptions import (
    ExternalServiceError,
    UnauthorizedError,
    ValidationFailedError,
)
from app.core.outbound import assert_deliverable_url
from app.core.redis import get_redis_client
from app.models import (
    AuditAction,
    Membership,
    MembershipRole,
    SsoConfig,
    SsoIdentity,
    User,
    utcnow,
)
from app.repositories import MembershipRepository, UserRepository
from app.services import audit, token_store

logger = logging.getLogger(__name__)

DISCOVERY_CACHE_PREFIX = "teamflow:sso:discovery"
STATE_PREFIX = "teamflow:sso:state"
DISCOVERY_TTL_SECONDS = 3600
DEFAULT_SCOPES = ["openid", "email", "profile"]
ID_TOKEN_ALGORITHMS = ["RS256", "ES256"]


def _code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


async def _load_discovery(redis: Redis, issuer: str) -> dict:
    key = f"{DISCOVERY_CACHE_PREFIX}:{issuer}"
    cached = await redis.get(key)
    if cached:
        try:
            return json.loads(cached)
        except ValueError:
            pass  # corrupted cache entry: re-fetch below

    url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
    try:
        # The issuer is admin-controlled; block SSRF to internal services.
        assert_deliverable_url(url)
    except ValidationFailedError as exc:
        raise ExternalServiceError("Identity provider URL is not allowed") from exc
    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
            response = await client.get(url)
    except httpx.HTTPError as exc:
        raise ExternalServiceError("Could not reach the identity provider") from exc
    if response.status_code != 200:
        logger.warning(
            "OIDC discovery failed (%s) for issuer %s: %s",
            response.status_code,
            issuer,
            response.text[:500],
        )
        raise ExternalServiceError("Identity provider discovery failed")

    discovery = response.json()
    await redis.set(key, json.dumps(discovery), ex=DISCOVERY_TTL_SECONDS)
    return discovery


async def start_authorize(config: SsoConfig, redirect_uri: str) -> str:
    """Stores one-time state/nonce/PKCE verifier and returns the consent URL."""
    redis = get_redis_client()
    discovery = await _load_discovery(redis, config.issuer)
    endpoint = discovery.get("authorization_endpoint")
    if not endpoint:
        raise ExternalServiceError("Identity provider has no authorization endpoint")

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    scopes = list(config.scopes or DEFAULT_SCOPES)
    if "openid" not in scopes:
        scopes.insert(0, "openid")

    payload = {
        "config_id": str(config.id),
        "verifier": verifier,
        "nonce": nonce,
        "redirect_uri": redirect_uri,
    }
    await redis.set(
        f"{STATE_PREFIX}:{state}",
        json.dumps(payload),
        ex=settings.oauth_state_ttl_seconds,
    )

    params = {
        "client_id": config.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
        "nonce": nonce,
        "code_challenge": _code_challenge(verifier),
        "code_challenge_method": "S256",
    }
    return f"{endpoint}?{urlencode(params)}"


async def config_for_state(db: AsyncSession, state: str) -> SsoConfig | None:
    """Peeks (does not consume) at a pending authorization state so the
    callback route can resolve which org's config to use."""
    redis = get_redis_client()
    raw = await redis.get(f"{STATE_PREFIX}:{state}")
    if not raw:
        return None
    try:
        state_data = json.loads(raw)
        config_id = uuid.UUID(state_data["config_id"])
    except (ValueError, KeyError, TypeError):
        return None
    return await db.get(SsoConfig, config_id)


@lru_cache(maxsize=16)
def _jwks_client(jwks_uri: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(
        jwks_uri,
        cache_keys=True,
        lifespan=DISCOVERY_TTL_SECONDS,
        timeout=settings.http_timeout_seconds,
    )


def _verify_id_token(id_token: str, jwks_uri: str, config: SsoConfig) -> dict:
    """Blocking (JWKS fetch) — call via run_in_threadpool from async code."""
    try:
        signing_key = _jwks_client(jwks_uri).get_signing_key_from_jwt(id_token)
        return jwt.decode(
            id_token,
            signing_key.key,
            algorithms=ID_TOKEN_ALGORITHMS,
            audience=config.client_id,
            issuer=config.issuer,
            options={"require": ["exp", "iat", "aud", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise ExternalServiceError("SSO identity token is invalid") from exc


async def complete_callback(
    db: AsyncSession, config: SsoConfig, code: str, state: str
) -> str:
    """Validates the IdP callback and returns the one-time SPA hand-off code."""
    redis = get_redis_client()
    raw = await redis.getdel(f"{STATE_PREFIX}:{state}")
    if not raw:
        raise UnauthorizedError("Invalid or expired SSO state")
    try:
        state_data = json.loads(raw)
    except ValueError:
        raise UnauthorizedError("Invalid or expired SSO state") from None
    if state_data.get("config_id") != str(config.id):
        raise UnauthorizedError("Invalid SSO state")

    discovery = await _load_discovery(redis, config.issuer)
    token_endpoint = discovery.get("token_endpoint")
    jwks_uri = discovery.get("jwks_uri")
    if not token_endpoint or not jwks_uri:
        raise ExternalServiceError("Identity provider discovery is incomplete")
    try:
        # Endpoints come from the (admin-controlled) discovery document.
        assert_deliverable_url(str(token_endpoint))
        assert_deliverable_url(str(jwks_uri))
    except ValidationFailedError as exc:
        raise ExternalServiceError("Identity provider endpoints are not allowed") from exc

    token_payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": state_data.get("redirect_uri", ""),
        "client_id": config.client_id,
        "client_secret": config.client_secret,
        "code_verifier": state_data.get("verifier", ""),
    }
    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
            response = await client.post(token_endpoint, data=token_payload)
    except httpx.HTTPError as exc:
        raise ExternalServiceError("Could not reach the identity provider") from exc
    if response.status_code != 200:
        logger.warning(
            "SSO token exchange failed (%s): %s", response.status_code, response.text[:500]
        )
        raise ExternalServiceError("Identity provider rejected the sign-in attempt")

    id_token = response.json().get("id_token")
    if not id_token:
        raise ExternalServiceError("Identity provider did not return an identity token")

    claims = await run_in_threadpool(_verify_id_token, id_token, jwks_uri, config)
    nonce = str(claims.get("nonce", ""))
    if not nonce or not hmac.compare_digest(nonce, str(state_data.get("nonce", ""))):
        raise UnauthorizedError("Invalid SSO nonce")

    email = str(claims.get("email", "")).lower().strip()
    if not email:
        raise UnauthorizedError("SSO account has no email address")
    # A tenant admin controls the issuer, so an unverified or absent
    # `email_verified` must never be trusted for linking/provisioning.
    if claims.get("email_verified") is not True:
        raise UnauthorizedError(
            "The identity provider has not verified this email address"
        )

    # Captured before provisioning: a concurrent-creation rollback inside
    # `_find_or_create_user` would expire the `config` instance.
    organization_id = config.organization_id
    issuer = config.issuer
    default_role = (
        config.default_role
        if config.default_role in MembershipRole.ASSIGNABLE
        else MembershipRole.MEMBER
    )
    auto_provision = config.auto_provision

    user = await _find_or_create_user(
        db, organization_id, issuer, auto_provision, claims, email
    )
    if not user.is_active:
        raise UnauthorizedError("Account is deactivated")

    membership_repo = MembershipRepository(db)
    membership = await membership_repo.get_for_user(user.id, organization_id)
    if membership is None:
        if not auto_provision:
            raise UnauthorizedError("Account is not provisioned for this organization")
        await membership_repo.add(
            Membership(
                user_id=user.id,
                organization_id=organization_id,
                role=default_role,
            )
        )
    elif not membership.is_active:
        raise UnauthorizedError("Account is deactivated")

    await audit.log(
        db,
        "user.login_sso",
        actor_id=user.id,
        organization_id=organization_id,
        meta={"email": email, "method": "sso"},
    )
    await db.commit()

    handoff = security.token_urlsafe()
    await token_store.store_oauth_login_code(
        redis, handoff, str(user.id), settings.oauth_login_code_ttl_seconds
    )
    return handoff


async def _link_identity(
    db: AsyncSession,
    organization_id: uuid.UUID,
    issuer: str,
    subject: str,
    user_id: uuid.UUID,
) -> None:
    """Binds (org, issuer, subject) -> user. A concurrent first login may win
    the unique constraint; ON CONFLICT keeps the loser idempotent."""
    now = utcnow()
    await db.execute(
        pg_insert(SsoIdentity.__table__)
        .values(
            id=uuid.uuid4(),
            organization_id=organization_id,
            issuer=issuer,
            subject=subject,
            user_id=user_id,
            last_login_at=now,
            created_at=now,
        )
        .on_conflict_do_nothing(constraint="uq_sso_identity_org_issuer_subject")
    )


async def _find_or_create_user(
    db: AsyncSession,
    organization_id: uuid.UUID,
    issuer: str,
    auto_provision: bool,
    claims: dict,
    email: str,
) -> User:
    subject = str(claims.get("sub") or "").strip()
    if not subject:
        raise UnauthorizedError("SSO identity token has no subject")

    # 1. A previously bound identity for this org+issuer+subject wins outright.
    identity = (
        await db.execute(
            select(SsoIdentity).where(
                SsoIdentity.organization_id == organization_id,
                SsoIdentity.issuer == issuer,
                SsoIdentity.subject == subject,
            )
        )
    ).scalar_one_or_none()
    if identity is not None:
        user = await db.get(User, identity.user_id)
        if user is None:
            raise UnauthorizedError("Linked account no longer exists")
        identity.last_login_at = utcnow()
        db.add(identity)
        return user

    # 2. No link yet: linking an existing global account is only allowed for
    #    members of this org. Otherwise any tenant admin who controls an IdP
    #    could impersonate users of other tenants by asserting their email.
    repo = UserRepository(db)
    existing = await repo.get_by_email(email)
    if existing is not None:
        membership = await MembershipRepository(db).get_for_user(
            existing.id, organization_id
        )
        if membership is None:
            raise UnauthorizedError(
                "An account with this email already exists; ask an "
                "organization admin to add you"
            )
        await _link_identity(db, organization_id, issuer, subject, existing.id)
        return existing

    if not auto_provision:
        raise UnauthorizedError("Account is not provisioned for this organization")

    full_name = str(claims.get("name") or claims.get("preferred_username") or email)[:255]
    hashed = await run_in_threadpool(
        security.hash_password, secrets.token_urlsafe(32)
    )
    user = User(email=email, full_name=full_name, hashed_password=hashed)
    try:
        user = await repo.add(user)
    except IntegrityError:
        # A concurrent first-login raced; the loser links to the winner.
        await db.rollback()
        existing = await repo.get_by_email(email)
        if existing is None:
            raise UnauthorizedError("Could not provision the account") from None
        membership = await MembershipRepository(db).get_for_user(
            existing.id, organization_id
        )
        if membership is None:
            raise UnauthorizedError(
                "An account with this email already exists; ask an "
                "organization admin to add you"
            )
        await _link_identity(db, organization_id, issuer, subject, existing.id)
        return existing
    await audit.log(
        db,
        AuditAction.USER_REGISTERED,
        actor_id=user.id,
        meta={"email": email, "method": "sso"},
    )
    await _link_identity(db, organization_id, issuer, subject, user.id)
    return user
