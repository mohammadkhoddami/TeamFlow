"""Email notification preference routes + unsubscribe."""

from fastapi import APIRouter, HTTPException, status

from app.api.deps import DB, CurrentUser
from app.schemas import (
    NotificationPreferenceRead,
    NotificationPreferenceUpdate,
)
from app.services import preferences as preference_service

router = APIRouter(prefix="/auth", tags=["notification-preferences"])


def _serialize(preference) -> NotificationPreferenceRead:
    read = NotificationPreferenceRead.model_validate(preference)
    read.unsubscribe_url = preference_service.unsubscribe_url(preference)
    return read


@router.get("/me/notification-preferences", response_model=NotificationPreferenceRead)
async def get_my_preferences(
    current_user: CurrentUser, db: DB
) -> NotificationPreferenceRead:
    preference = await preference_service.get_or_create(db, current_user)
    return _serialize(preference)


@router.put("/me/notification-preferences", response_model=NotificationPreferenceRead)
async def update_my_preferences(
    data: NotificationPreferenceUpdate, current_user: CurrentUser, db: DB
) -> NotificationPreferenceRead:
    preference = await preference_service.update(db, current_user, data)
    return _serialize(preference)


@router.post("/unsubscribe", response_model=dict)
async def unsubscribe(token: str, db: DB) -> dict:
    """Token-authenticated opt-out (no login needed; token is unguessable)."""
    ok = await preference_service.unsubscribe(db, token)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Invalid unsubscribe token"
        )
    return {"detail": "You will no longer receive email notifications."}
