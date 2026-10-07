"""SSO (OIDC) routes + SCIM token administration.

Public (unauthenticated) SSO flow:
  GET /auth/sso/{slug}/start   -> redirect to the IdP
  GET /auth/sso/callback       -> exchange + redirect to the SPA
  GET /auth/sso/{slug}/config  -> SPA bootstrap: enabled/provider/login_url

Org-admin routes require admin or owner:
  GET/PUT  /organizations/{slug}/sso
  GET/POST /organizations/{slug}/scim-tokens
  DELETE   /organizations/{slug}/scim-tokens/{token_id}
"""

import hashlib
import logging
import secrets
import uuid
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import RedirectResponse
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import DB, CurrentUser, OrgMembership
from app.core.config import settings
from app.core.exceptions import (
    AppError,
    NotFoundError,
    PermissionDeniedError,
    ValidationFailedError,
)
from app.core.rate_limit import ip_rate_limiter
from app.models import MembershipRole, ScimToken, SsoConfig
from app.repositories import OrganizationRepository
from app.schemas.sso import (
    ScimTokenCreate,
    ScimTokenCreated,
    ScimTokenRead,
    SsoConfigRead,
    SsoConfigUpdate,
    SsoPublicConfig,
)
from app.services import sso as sso_service
from app.services.organizations import role_rank

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/sso", tags=["sso"])
org_router = APIRouter(prefix="/organizations/{slug}/sso", tags=["sso"])
scim_token_router = APIRouter(
    prefix="/organizations/{slug}/scim-tokens", tags=["sso"]
)


def _require_sso_admin(role: str) -> None:
    if role_rank(role) < role_rank(MembershipRole.ADMIN):
        raise PermissionDeniedError("Only admins and owners can manage SSO")


async def _config_for_org(db: AsyncSession, organization_id: uuid.UUID) -> SsoConfig | None:
    statement = select(SsoConfig).where(SsoConfig.organization_id == organization_id)
    return (await db.execute(statement)).scalar_one_or_none()


def _read_config(config: SsoConfig) -> SsoConfigRead:
    return SsoConfigRead(
        provider=config.provider,
        issuer=config.issuer,
        client_id=config.client_id,
        scopes=list(config.scopes or []),
        is_enabled=config.is_enabled,
        auto_provision=config.auto_provision,
        default_role=config.default_role,
        has_secret=bool(config.client_secret),
    )


def _frontend_callback(code: str | None = None, error: str | None = None) -> RedirectResponse:
    params = {"code": code} if code else {"error": error or "sso_sign_in_failed"}
    return RedirectResponse(
        f"{settings.frontend_base_url}/auth/callback?{urlencode(params)}",
        status_code=status.HTTP_302_FOUND,
    )


# ------------------------------------------------------------- public flow


@router.get(
    "/{slug}/start",
    name="sso_start",
    summary="Start SSO sign-in (redirects to the identity provider)",
    response_class=RedirectResponse,
)
async def sso_start(
    slug: str,
    request: Request,
    db: DB,
    _rl: None = Depends(ip_rate_limiter("sso_start", 20, 60)),
) -> RedirectResponse:
    org = await OrganizationRepository(db).get_by_slug(slug)
    if not org:
        raise NotFoundError("Organization not found")
    config = await _config_for_org(db, org.id)
    if not config or not config.is_enabled:
        raise NotFoundError("SSO is not enabled for this organization")
    redirect_uri = str(request.url_for("sso_callback"))
    url = await sso_service.start_authorize(config, redirect_uri)
    return RedirectResponse(url, status_code=status.HTTP_302_FOUND)


@router.get("/callback", name="sso_callback", summary="SSO authorization callback")
async def sso_callback(
    request: Request,
    db: DB,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    if error or not code or not state:
        return _frontend_callback(error=error or "sso_sign_in_failed")
    config = await sso_service.config_for_state(db, state)
    if config is None:
        return _frontend_callback(error="sso_sign_in_failed")
    try:
        handoff = await sso_service.complete_callback(db, config, code, state)
    except AppError as exc:
        logger.warning("SSO sign-in failed: %s", exc.detail)
        return _frontend_callback(error="sso_sign_in_failed")
    return _frontend_callback(code=handoff)


@router.get(
    "/{slug}/config",
    response_model=SsoPublicConfig,
    summary="Public SSO bootstrap for the login page",
)
async def sso_public_config(slug: str, db: DB) -> SsoPublicConfig:
    org = await OrganizationRepository(db).get_by_slug(slug)
    if not org:
        raise NotFoundError("Organization not found")
    config = await _config_for_org(db, org.id)
    return SsoPublicConfig(
        enabled=bool(config and config.is_enabled),
        provider=config.provider if config else "oidc",
        login_url=f"{settings.api_v1_prefix}/auth/sso/{slug}/start",
    )


# ------------------------------------------------------------- admin flow


@org_router.get("", response_model=SsoConfigRead, summary="Read the SSO config")
async def get_sso_config(membership: OrgMembership, db: DB) -> SsoConfigRead:
    org, current = membership
    _require_sso_admin(current.role)
    config = await _config_for_org(db, org.id)
    if not config:
        raise NotFoundError("SSO is not configured for this organization")
    return _read_config(config)


@org_router.put("", response_model=SsoConfigRead, summary="Create or update SSO config")
async def put_sso_config(
    data: SsoConfigUpdate,
    membership: OrgMembership,
    current_user: CurrentUser,
    db: DB,
) -> SsoConfigRead:
    org, current = membership
    _require_sso_admin(current.role)

    config = await _config_for_org(db, org.id)
    if config is None:
        if not data.client_secret:
            raise ValidationFailedError("client_secret is required")
        config = SsoConfig(
            organization_id=org.id,
            issuer=data.issuer,
            client_id=data.client_id,
            client_secret=data.client_secret,
            scopes=list(data.scopes),
            is_enabled=data.is_enabled,
            auto_provision=data.auto_provision,
            default_role=data.default_role,
            created_by_id=current_user.id,
        )
    else:
        config.issuer = data.issuer
        config.client_id = data.client_id
        # An empty secret on update keeps the stored one (write-only field).
        if data.client_secret:
            config.client_secret = data.client_secret
        config.scopes = list(data.scopes)
        config.is_enabled = data.is_enabled
        config.auto_provision = data.auto_provision
        config.default_role = data.default_role
    db.add(config)
    await db.commit()
    await db.refresh(config)
    return _read_config(config)


# --------------------------------------------------------- SCIM tokens


@scim_token_router.get("", response_model=list[ScimTokenRead])
async def list_scim_tokens(membership: OrgMembership, db: DB) -> list[ScimTokenRead]:
    org, current = membership
    _require_sso_admin(current.role)
    statement = (
        select(ScimToken)
        .where(ScimToken.organization_id == org.id)
        .order_by(ScimToken.created_at.desc())
    )
    tokens = (await db.execute(statement)).scalars().all()
    return [ScimTokenRead.model_validate(token) for token in tokens]


@scim_token_router.post(
    "", status_code=status.HTTP_201_CREATED, response_model=ScimTokenCreated
)
async def create_scim_token(
    data: ScimTokenCreate,
    membership: OrgMembership,
    current_user: CurrentUser,
    db: DB,
) -> ScimTokenCreated:
    org, current = membership
    _require_sso_admin(current.role)
    plain = f"scim_{secrets.token_urlsafe(32)}"
    token = ScimToken(
        organization_id=org.id,
        name=data.name,
        token_hash=hashlib.sha256(plain.encode()).hexdigest(),
        created_by_id=current_user.id,
    )
    db.add(token)
    await db.commit()
    await db.refresh(token)
    return ScimTokenCreated(
        id=token.id,
        name=token.name,
        is_active=token.is_active,
        last_used_at=token.last_used_at,
        created_at=token.created_at,
        token=plain,
    )


@scim_token_router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scim_token(
    token_id: uuid.UUID, membership: OrgMembership, db: DB
) -> None:
    org, current = membership
    _require_sso_admin(current.role)
    statement = select(ScimToken).where(
        ScimToken.id == token_id, ScimToken.organization_id == org.id
    )
    token = (await db.execute(statement)).scalar_one_or_none()
    if not token:
        raise NotFoundError("SCIM token not found")
    await db.delete(token)
    await db.commit()
