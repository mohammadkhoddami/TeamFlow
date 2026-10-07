"""Saved filter routes (TeamQL views)."""

import uuid

from fastapi import APIRouter, status

from app.api.deps import DB, CurrentUser, OrgMembership
from app.schemas import (
    SavedFilterCreate,
    SavedFilterRead,
    SavedFilterUpdate,
)
from app.services import saved_filters as saved_filter_service

router = APIRouter(prefix="/organizations/{slug}/saved-filters", tags=["saved-filters"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=SavedFilterRead)
async def create_saved_filter(
    data: SavedFilterCreate,
    membership: OrgMembership,
    current_user: CurrentUser,
    db: DB,
) -> SavedFilterRead:
    org, m = membership
    saved = await saved_filter_service.create_saved_filter(
        db, current_user, org, m, data
    )
    return SavedFilterRead.model_validate(saved)


@router.get("", response_model=list[SavedFilterRead])
async def list_saved_filters(
    membership: OrgMembership, current_user: CurrentUser, db: DB
) -> list[SavedFilterRead]:
    org, _m = membership
    saved = await saved_filter_service.list_saved_filters(db, org.id, current_user)
    return [SavedFilterRead.model_validate(entry) for entry in saved]


@router.patch("/{saved_filter_id}", response_model=SavedFilterRead)
async def update_saved_filter(
    saved_filter_id: uuid.UUID,
    data: SavedFilterUpdate,
    membership: OrgMembership,
    current_user: CurrentUser,
    db: DB,
) -> SavedFilterRead:
    org, m = membership
    saved = await saved_filter_service.get_saved_filter_for_org(
        db, saved_filter_id, org.id
    )
    updated = await saved_filter_service.update_saved_filter(
        db, current_user, org, m, saved, data
    )
    return SavedFilterRead.model_validate(updated)


@router.delete("/{saved_filter_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved_filter(
    saved_filter_id: uuid.UUID,
    membership: OrgMembership,
    current_user: CurrentUser,
    db: DB,
) -> None:
    org, m = membership
    saved = await saved_filter_service.get_saved_filter_for_org(
        db, saved_filter_id, org.id
    )
    await saved_filter_service.delete_saved_filter(db, current_user, org, m, saved)
