"""API token, service account and OAuth app routes (M3 #24)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, Request, status

from app.api.deps import DB, CurrentUser, OrgMembership
from app.core.exceptions import PermissionDeniedError, ValidationFailedError
from app.core.rate_limit import ip_rate_limiter
from app.models import MembershipRole
from app.schemas import (
    ApiTokenCreate,
    ApiTokenCreated,
    ApiTokenRead,
    ApiTokenUpdate,
    ApiTokenUsage,
    OAuthAppCreate,
    OAuthAppCreated,
    OAuthAppRead,
    OAuthAppUpdate,
    OAuthTokenResponse,
    ServiceAccountCreate,
    ServiceAccountRead,
    ServiceAccountUpdate,
)
from app.services import api_tokens as token_service

router = APIRouter(prefix="/organizations/{slug}", tags=["api-tokens"])
oauth_router = APIRouter(prefix="/oauth", tags=["oauth"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _elevated(membership) -> bool:
    return membership.role != MembershipRole.MEMBER


@router.get("/api-tokens", response_model=list[ApiTokenRead])
async def list_tokens(
    org_membership: OrgMembership,
    current_user: CurrentUser,
    db: DB,
    mine: bool = Query(default=False, description="Only tokens I own"),
) -> list[ApiTokenRead]:
    org, membership = org_membership
    owner = current_user if (mine or not _elevated(membership)) else None
    tokens = await token_service.list_tokens(db, org, mine=owner)
    return [ApiTokenRead.model_validate(token) for token in tokens]


@router.post(
    "/api-tokens", status_code=status.HTTP_201_CREATED, response_model=ApiTokenCreated
)
async def create_token(
    data: ApiTokenCreate,
    org_membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> ApiTokenCreated:
    org, membership = org_membership
    token, plain = await token_service.create_token(
        db, current_user, org, membership, data, ip=_ip(request)
    )
    read = ApiTokenRead.model_validate(token)
    return ApiTokenCreated(**read.model_dump(), token=plain)


@router.get("/api-tokens/{token_id}/usage", response_model=ApiTokenUsage)
async def token_usage(
    token_id: uuid.UUID, org_membership: OrgMembership, db: DB
) -> ApiTokenUsage:
    org, _membership = org_membership
    return ApiTokenUsage(**await token_service.token_usage(db, org, token_id))


@router.patch("/api-tokens/{token_id}", response_model=ApiTokenRead)
async def update_token(
    token_id: uuid.UUID,
    data: ApiTokenUpdate,
    org_membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> ApiTokenRead:
    org, membership = org_membership
    token = await token_service.update_token(
        db, current_user, org, membership, token_id, data, ip=_ip(request)
    )
    return ApiTokenRead.model_validate(token)


@router.post("/api-tokens/{token_id}/rotate", response_model=ApiTokenCreated)
async def rotate_token(
    token_id: uuid.UUID,
    org_membership: OrgMembership,
    current_user: CurrentUser,
    db: DB,
) -> ApiTokenCreated:
    org, _membership = org_membership
    token, plain = await token_service.rotate_token(db, current_user, org, token_id)
    read = ApiTokenRead.model_validate(token)
    return ApiTokenCreated(**read.model_dump(), token=plain)


@router.delete("/api-tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(
    token_id: uuid.UUID,
    org_membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> None:
    org, membership = org_membership
    await token_service.revoke_token(
        db, current_user, org, membership, token_id, ip=_ip(request)
    )


@router.get("/service-accounts", response_model=list[ServiceAccountRead])
async def list_service_accounts(
    org_membership: OrgMembership, current_user: CurrentUser, db: DB
) -> list[ServiceAccountRead]:
    org, membership = org_membership
    if not _elevated(membership):
        raise PermissionDeniedError("Only managers and above can view service accounts")
    accounts = await token_service.list_service_accounts(db, org)
    return [ServiceAccountRead.model_validate(account) for account in accounts]


@router.post(
    "/service-accounts",
    status_code=status.HTTP_201_CREATED,
    response_model=ServiceAccountRead,
)
async def create_service_account(
    data: ServiceAccountCreate,
    org_membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> ServiceAccountRead:
    org, membership = org_membership
    account = await token_service.create_service_account(
        db, current_user, org, membership, data, ip=_ip(request)
    )
    return ServiceAccountRead.model_validate(account)


@router.patch("/service-accounts/{account_id}", response_model=ServiceAccountRead)
async def update_service_account(
    account_id: uuid.UUID,
    data: ServiceAccountUpdate,
    org_membership: OrgMembership,
    current_user: CurrentUser,
    db: DB,
) -> ServiceAccountRead:
    org, membership = org_membership
    account = await token_service.update_service_account(
        db, current_user, org, membership, account_id, data
    )
    return ServiceAccountRead.model_validate(account)


@router.delete(
    "/service-accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_service_account(
    account_id: uuid.UUID,
    org_membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> None:
    org, membership = org_membership
    await token_service.delete_service_account(
        db, current_user, org, membership, account_id, ip=_ip(request)
    )


@router.get("/oauth-apps", response_model=list[OAuthAppRead])
async def list_oauth_apps(
    org_membership: OrgMembership, current_user: CurrentUser, db: DB
) -> list[OAuthAppRead]:
    org, membership = org_membership
    if not _elevated(membership):
        raise PermissionDeniedError("Only managers and above can view OAuth apps")
    apps = await token_service.list_oauth_apps(db, org)
    return [OAuthAppRead.model_validate(app) for app in apps]


@router.post(
    "/oauth-apps", status_code=status.HTTP_201_CREATED, response_model=OAuthAppCreated
)
async def create_oauth_app(
    data: OAuthAppCreate,
    org_membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> OAuthAppCreated:
    org, membership = org_membership
    app, secret = await token_service.create_oauth_app(
        db, current_user, org, membership, data, ip=_ip(request)
    )
    read = OAuthAppRead.model_validate(app)
    return OAuthAppCreated(**read.model_dump(), client_secret=secret)


@router.patch("/oauth-apps/{app_id}", response_model=OAuthAppRead)
async def update_oauth_app(
    app_id: uuid.UUID,
    data: OAuthAppUpdate,
    org_membership: OrgMembership,
    current_user: CurrentUser,
    db: DB,
) -> OAuthAppRead:
    org, membership = org_membership
    app = await token_service.update_oauth_app(
        db, current_user, org, membership, app_id, data
    )
    return OAuthAppRead.model_validate(app)


@router.post("/oauth-apps/{app_id}/rotate", response_model=OAuthAppCreated)
async def rotate_oauth_secret(
    app_id: uuid.UUID,
    org_membership: OrgMembership,
    current_user: CurrentUser,
    db: DB,
) -> OAuthAppCreated:
    org, membership = org_membership
    app, secret = await token_service.rotate_oauth_secret(
        db, current_user, org, membership, app_id
    )
    read = OAuthAppRead.model_validate(app)
    return OAuthAppCreated(**read.model_dump(), client_secret=secret)


@router.delete("/oauth-apps/{app_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_oauth_app(
    app_id: uuid.UUID,
    org_membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> None:
    org, membership = org_membership
    await token_service.delete_oauth_app(
        db, current_user, org, membership, app_id, ip=_ip(request)
    )


@oauth_router.post("/token", response_model=OAuthTokenResponse)
async def oauth_token(
    db: DB,
    grant_type: Annotated[str, Form()],
    client_id: Annotated[str, Form()],
    client_secret: Annotated[str, Form()],
    scope: Annotated[str | None, Form()] = None,
    _limit: None = Depends(ip_rate_limiter("oauth_token", 20, 60)),
) -> OAuthTokenResponse:
    """OAuth2 token endpoint (client_credentials)."""
    if grant_type != "client_credentials":
        raise ValidationFailedError("Only grant_type=client_credentials is supported")
    _token, app, plain = await token_service.client_credentials_grant(
        db, client_id=client_id, client_secret=client_secret, scope=scope
    )
    return OAuthTokenResponse(
        access_token=plain,
        expires_in=token_service.OAUTH_ACCESS_TTL_SECONDS,
        scope=" ".join(_token.scopes),
    )
