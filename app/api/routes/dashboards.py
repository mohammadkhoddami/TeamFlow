"""Saved dashboard routes (M4): CRUD under an org plus widget data."""

import uuid

from fastapi import APIRouter, status

from app.api.deps import DB, CurrentUser, OrgMembership
from app.schemas.dashboard import (
    DashboardCreate,
    DashboardData,
    DashboardRead,
    DashboardUpdate,
)
from app.services import dashboards as dashboard_service

router = APIRouter(prefix="/organizations/{slug}/dashboards", tags=["dashboards"])


@router.get("", response_model=list[DashboardRead])
async def list_dashboards(membership: OrgMembership, db: DB) -> list[DashboardRead]:
    org, _m = membership
    dashboards = await dashboard_service.list_dashboards(db, org.id)
    return [DashboardRead.model_validate(entry) for entry in dashboards]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=DashboardRead)
async def create_dashboard(
    data: DashboardCreate,
    membership: OrgMembership,
    current_user: CurrentUser,
    db: DB,
) -> DashboardRead:
    org, _m = membership
    dashboard = await dashboard_service.create_dashboard(db, current_user, org, data)
    return DashboardRead.model_validate(dashboard)


@router.get("/{dashboard_id}", response_model=DashboardRead)
async def get_dashboard(
    dashboard_id: uuid.UUID, membership: OrgMembership, db: DB
) -> DashboardRead:
    org, _m = membership
    dashboard = await dashboard_service.get_dashboard_for_org(
        db, dashboard_id, org.id
    )
    return DashboardRead.model_validate(dashboard)


@router.get("/{dashboard_id}/data", response_model=DashboardData)
async def get_dashboard_data(
    dashboard_id: uuid.UUID, membership: OrgMembership, db: DB
) -> DashboardData:
    org, _m = membership
    dashboard = await dashboard_service.get_dashboard_for_org(
        db, dashboard_id, org.id
    )
    return DashboardData.model_validate(
        await dashboard_service.dashboard_data(db, dashboard)
    )


@router.patch("/{dashboard_id}", response_model=DashboardRead)
async def update_dashboard(
    dashboard_id: uuid.UUID,
    data: DashboardUpdate,
    membership: OrgMembership,
    current_user: CurrentUser,
    db: DB,
) -> DashboardRead:
    org, _m = membership
    dashboard = await dashboard_service.get_dashboard_for_org(
        db, dashboard_id, org.id
    )
    updated = await dashboard_service.update_dashboard(
        db, current_user, org, dashboard, data
    )
    return DashboardRead.model_validate(updated)


@router.delete("/{dashboard_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dashboard(
    dashboard_id: uuid.UUID,
    membership: OrgMembership,
    current_user: CurrentUser,
    db: DB,
) -> None:
    org, _m = membership
    dashboard = await dashboard_service.get_dashboard_for_org(
        db, dashboard_id, org.id
    )
    await dashboard_service.delete_dashboard(db, current_user, org, dashboard)
