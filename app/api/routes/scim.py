"""SCIM 2.0 user provisioning routes (`/scim/v2`).

Authenticated with a per-org SCIM bearer token (no JWT): the presented
`scim_...` value is hashed and looked up in `scim_tokens`. The token's
organization is the tenant boundary for every operation. Users are org
members; DELETE and PATCH active=false deactivate both the User and the
Membership. Errors follow RFC 7644 (`Error` schema).
"""

import hashlib
import re
import secrets
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api.deps import DB
from app.core import security
from app.core.exceptions import UnauthorizedError
from app.models import (
    Membership,
    MembershipRole,
    Organization,
    ScimToken,
    SsoConfig,
    User,
    utcnow,
)
from app.schemas.scim import ScimPatchRequest, ScimUserCreate

router = APIRouter(prefix="/scim/v2", tags=["scim"])

SCIM_USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
SCIM_ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"

_FILTER_RE = re.compile(
    r'^\s*(?P<attr>[A-Za-z][A-Za-z0-9.]*)\s+eq\s+'
    r'(?:"(?P<quoted>[^"]*)"|(?P<bare>[^\s"]+))\s*$'
)


async def get_scim_auth(request: Request, db: DB) -> tuple[Organization, ScimToken]:
    """Bearer `scim_...` token -> (organization, token row). 401 otherwise."""
    scheme, _, credentials = request.headers.get("Authorization", "").partition(" ")
    credentials = credentials.strip()
    if scheme.lower() != "bearer" or not credentials:
        raise UnauthorizedError("A SCIM bearer token is required")

    token_hash = hashlib.sha256(credentials.encode()).hexdigest()
    statement = select(ScimToken).where(
        ScimToken.token_hash == token_hash,
        ScimToken.is_active == True,
    )
    token = (await db.execute(statement)).scalar_one_or_none()
    if token is None:
        raise UnauthorizedError("Invalid or inactive SCIM token")
    org = await db.get(Organization, token.organization_id)
    if org is None or not org.is_active:
        raise UnauthorizedError("Invalid or inactive SCIM token")

    token.last_used_at = utcnow()
    db.add(token)
    await db.commit()
    return org, token


ScimAuth = Annotated[tuple[Organization, ScimToken], Depends(get_scim_auth)]


def _scim_error(status_code: int, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "schemas": [SCIM_ERROR_SCHEMA],
            "detail": detail,
            "status": str(status_code),
        },
    )


def _parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
    return None


def _user_resource(user: User, membership: Membership) -> dict:
    resource: dict[str, Any] = {
        "schemas": [SCIM_USER_SCHEMA],
        "id": str(user.id),
        "userName": user.email,
        "name": {"formatted": user.full_name or user.email},
        "active": bool(user.is_active and membership.is_active),
        "emails": [{"value": user.email, "primary": True}],
        "meta": {"resourceType": "User"},
    }
    if user.created_at:
        resource["meta"]["created"] = user.created_at.isoformat()
    if user.updated_at:
        resource["meta"]["lastModified"] = user.updated_at.isoformat()
    return resource


async def _get_org_member(
    db: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID
) -> tuple[User, Membership] | None:
    statement = (
        select(User, Membership)
        .join(Membership, Membership.user_id == User.id)
        .where(
            Membership.organization_id == organization_id,
            User.id == user_id,
            User.is_service_account == False,
        )
    )
    row = (await db.execute(statement)).first()
    return (row[0], row[1]) if row else None


# ------------------------------------------------------------ discovery


@router.get("/ServiceProviderConfig")
async def service_provider_config(_auth: ScimAuth) -> dict:
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "documentationUri": "https://www.rfc-editor.org/rfc/rfc7644",
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": 200},
        "changePassword": {"supported": False},
        "sort": {"supported": False},
        "etag": {"supported": False},
        "authenticationSchemes": [
            {
                "type": "oauthbearer",
                "name": "OAuth Bearer Token",
                "description": "SCIM bearer token issued by TeamFlow",
            }
        ],
        "meta": {
            "resourceType": "ServiceProviderConfig",
            "location": "/scim/v2/ServiceProviderConfig",
        },
    }


@router.get("/Schemas")
async def list_schemas(_auth: ScimAuth) -> dict:
    return {
        "schemas": [SCIM_LIST_SCHEMA],
        "totalResults": 1,
        "startIndex": 1,
        "itemsPerPage": 1,
        "Resources": [
            {
                "id": SCIM_USER_SCHEMA,
                "name": "User",
                "description": "User Account",
                "attributes": [
                    {"name": "userName", "type": "string", "required": True},
                    {"name": "name", "type": "complex"},
                    {"name": "active", "type": "boolean"},
                    {"name": "emails", "type": "complex", "multiValued": True},
                ],
            }
        ],
    }


# ----------------------------------------------------------------- users


@router.get("/Users")
async def list_users(
    auth: ScimAuth,
    db: DB,
    filter: str | None = Query(default=None),
    start_index: int = Query(default=1, alias="startIndex", ge=1),
    count: int = Query(default=100, alias="count", ge=0, le=500),
):
    org, _token = auth
    conditions = [
        Membership.organization_id == org.id,
        User.is_service_account == False,
    ]
    if filter:
        match = _FILTER_RE.match(filter)
        if not match:
            return _scim_error(400, "Unsupported filter expression")
        attribute = match.group("attr").lower()
        quoted, bare = match.group("quoted"), match.group("bare")
        raw_value = quoted if quoted is not None else bare
        if attribute == "username":
            conditions.append(func.lower(User.email) == raw_value.lower())
        elif attribute == "active":
            active = _parse_bool(raw_value)
            if active is None:
                return _scim_error(400, "The active filter must be true or false")
            conditions.append(User.is_active == active)
            conditions.append(Membership.is_active == active)
        else:
            return _scim_error(400, f"Unsupported filter attribute: {attribute}")

    total = (
        await db.execute(
            select(func.count())
            .select_from(User)
            .join(Membership, Membership.user_id == User.id)
            .where(*conditions)
        )
    ).scalar_one()
    statement = (
        select(User, Membership)
        .join(Membership, Membership.user_id == User.id)
        .where(*conditions)
        .order_by(User.created_at.asc())
        .offset(start_index - 1)
        .limit(count)
    )
    rows = (await db.execute(statement)).all()
    return {
        "schemas": [SCIM_LIST_SCHEMA],
        "totalResults": int(total),
        "startIndex": start_index,
        "itemsPerPage": len(rows),
        "Resources": [_user_resource(user, membership) for user, membership in rows],
    }


@router.post("/Users", status_code=status.HTTP_201_CREATED)
async def create_user(data: ScimUserCreate, auth: ScimAuth, db: DB):
    org, _token = auth
    email = data.userName.strip().lower()

    existing = (
        await db.execute(select(User).where(func.lower(User.email) == email))
    ).scalar_one_or_none()
    if existing is not None:
        return _scim_error(409, "A user with this userName already exists")

    config = (
        await db.execute(
            select(SsoConfig).where(SsoConfig.organization_id == org.id)
        )
    ).scalar_one_or_none()
    role = (
        config.default_role
        if config and config.default_role in MembershipRole.ALL
        else MembershipRole.MEMBER
    )
    full_name = (data.name.formatted if data.name and data.name.formatted else email)[:255]
    hashed = await run_in_threadpool(
        security.hash_password, secrets.token_urlsafe(32)
    )
    user = User(
        email=email,
        full_name=full_name,
        hashed_password=hashed,
        is_active=data.active,
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        return _scim_error(409, "A user with this userName already exists")

    membership = Membership(
        user_id=user.id,
        organization_id=org.id,
        role=role,
        is_active=data.active,
    )
    db.add(membership)
    await db.flush()
    await db.commit()
    return _user_resource(user, membership)


@router.get("/Users/{user_id}")
async def get_user(user_id: uuid.UUID, auth: ScimAuth, db: DB):
    org, _token = auth
    found = await _get_org_member(db, org.id, user_id)
    if found is None:
        return _scim_error(404, "User not found")
    return _user_resource(*found)


@router.patch("/Users/{user_id}")
async def patch_user(
    user_id: uuid.UUID, data: ScimPatchRequest, auth: ScimAuth, db: DB
):
    org, _token = auth
    found = await _get_org_member(db, org.id, user_id)
    if found is None:
        return _scim_error(404, "User not found")
    user, membership = found

    for operation in data.Operations:
        if operation.op.lower() not in ("replace", "add"):
            return _scim_error(400, f"Unsupported operation: {operation.op}")
        path = (operation.path or "").strip().lower()
        if path:
            targets = {path: operation.value}
        elif isinstance(operation.value, dict):
            targets = {key.lower(): value for key, value in operation.value.items()}
        else:
            return _scim_error(400, "Each operation needs a path or an object value")

        for target, value in targets.items():
            if target == "active":
                active = _parse_bool(value)
                if active is None:
                    return _scim_error(400, "active must be true or false")
                user.is_active = active
                membership.is_active = active
            elif target == "name.formatted":
                if value is None:
                    return _scim_error(400, "name.formatted cannot be null")
                user.full_name = str(value)[:255]
            else:
                return _scim_error(400, f"Unsupported path: {target}")

    db.add(user)
    db.add(membership)
    await db.commit()
    return _user_resource(user, membership)


@router.delete("/Users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: uuid.UUID, auth: ScimAuth, db: DB):
    org, _token = auth
    found = await _get_org_member(db, org.id, user_id)
    if found is None:
        return _scim_error(404, "User not found")
    user, membership = found
    user.is_active = False
    membership.is_active = False
    db.add(user)
    db.add(membership)
    await db.commit()
