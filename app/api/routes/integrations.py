"""Integration routes (M3 #23).

Authenticated CRUD lives under the org; two endpoints are public by design:
  - POST /integrations/{provider}/{id}          verified VCS webhook receiver
  - GET  /integrations/google-calendar/{id}/feed.ics?token=  ICS subscription
"""

import json
import uuid

from fastapi import APIRouter, Header, Query, Request, Response, status

from app.api.deps import DB, CurrentUser, OrgMembership
from app.core.exceptions import NotFoundError, UnauthorizedError, ValidationFailedError
from app.repositories import IntegrationRepository
from app.schemas import (
    IntegrationCreate,
    IntegrationCreated,
    IntegrationEventRead,
    IntegrationRead,
    IntegrationUpdate,
)
from app.services import permissions
from app.services.integrations import hub as integration_service

router = APIRouter(prefix="/organizations/{slug}/integrations", tags=["integrations"])
public_router = APIRouter(prefix="/integrations", tags=["integrations"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("", response_model=list[IntegrationRead])
async def list_integrations(
    org_membership: OrgMembership,
    db: DB,
    provider: str | None = Query(default=None),
) -> list[IntegrationRead]:
    org, _m = org_membership
    entries = await integration_service.list_integrations(db, org, provider=provider)
    return [IntegrationRead(**integration_service.to_read(entry)) for entry in entries]


@router.post(
    "", status_code=status.HTTP_201_CREATED, response_model=IntegrationCreated
)
async def create_integration(
    data: IntegrationCreate,
    org_membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> IntegrationCreated:
    org, membership = org_membership
    await permissions.require_permission(db, membership, "integrations.manage")
    integration, secret = await integration_service.create_integration(
        db, current_user, org, data, ip=_ip(request)
    )
    payload = IntegrationCreated(**integration_service.to_read(integration))
    payload.secret = secret
    return payload


@router.get("/events", response_model=list[IntegrationEventRead])
async def list_integration_events(
    org_membership: OrgMembership,
    db: DB,
    integration_id: uuid.UUID | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[IntegrationEventRead]:
    org, _m = org_membership
    events, _total = await integration_service.list_events(
        db, org, integration_id=integration_id, offset=offset, limit=limit
    )
    return [IntegrationEventRead.model_validate(event) for event in events]


@router.get("/{integration_id}", response_model=IntegrationRead)
async def get_integration(
    integration_id: uuid.UUID, org_membership: OrgMembership, db: DB
) -> IntegrationRead:
    org, _m = org_membership
    integration = await integration_service.get_integration_for_org(
        db, integration_id, org.id
    )
    return IntegrationRead(**integration_service.to_read(integration))


@router.patch("/{integration_id}", response_model=IntegrationCreated)
async def update_integration(
    integration_id: uuid.UUID,
    data: IntegrationUpdate,
    org_membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> IntegrationCreated:
    org, membership = org_membership
    await permissions.require_permission(db, membership, "integrations.manage")
    integration = await integration_service.get_integration_for_org(
        db, integration_id, org.id
    )
    updated, secret = await integration_service.update_integration(
        db, current_user, org, integration, data, ip=_ip(request)
    )
    payload = IntegrationCreated(**integration_service.to_read(updated))
    payload.secret = secret
    return payload


@router.delete("/{integration_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_integration(
    integration_id: uuid.UUID,
    org_membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> None:
    org, membership = org_membership
    await permissions.require_permission(db, membership, "integrations.manage")
    integration = await integration_service.get_integration_for_org(
        db, integration_id, org.id
    )
    await integration_service.delete_integration(
        db, current_user, org, integration, ip=_ip(request)
    )


# --- public endpoints (no JWT; secret/token is the auth) -------------------


@public_router.post("/{provider}/{integration_id}")
async def vcs_webhook(
    provider: str,
    integration_id: uuid.UUID,
    request: Request,
    db: DB,
    x_github_event: str | None = Header(default=None),
    x_gitlab_event: str | None = Header(default=None),
    x_event_key: str | None = Header(default=None),
) -> dict:
    integration = await IntegrationRepository(db).get(integration_id)
    if integration is None or integration.provider != provider:
        raise NotFoundError("Integration not found")
    if not integration.is_active or integration.secret is None:
        raise UnauthorizedError("Integration is disabled")
    body = await request.body()
    integration_service.verify_webhook_signature(
        provider, integration.secret, body, dict(request.headers)
    )
    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError:
        raise ValidationFailedError("Invalid JSON payload") from None
    event_type = x_github_event or x_gitlab_event or x_event_key or "unknown"
    return await integration_service.handle_vcs_webhook(
        db, integration, event_type=event_type, payload=payload, body=body
    )


@public_router.get("/google-calendar/{integration_id}/feed.ics")
async def google_calendar_feed(
    integration_id: uuid.UUID, db: DB, token: str = Query(default="")
) -> Response:
    integration = await IntegrationRepository(db).get(integration_id)
    if (
        integration is None
        or integration.provider != "google_calendar"
        or not integration.is_active
        or not integration.secret
        or token != integration.secret
    ):
        raise NotFoundError("Calendar feed not found")
    tasks, project_names = await integration_service.load_feed_tasks(db, integration)
    ics = integration_service.build_ics(integration, tasks, project_names)
    return Response(
        content=ics,
        media_type="text/calendar; charset=utf-8",
        headers={"Cache-Control": "private, max-age=300"},
    )
