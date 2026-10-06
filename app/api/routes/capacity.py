"""Sprint capacity routes."""

from fastapi import APIRouter

from app.api.deps import DB, CurrentUser, SprintAccess
from app.schemas import CapacityMemberRead, CapacityUpdate
from app.services import capacity as capacity_service

router = APIRouter(prefix="/sprints/{sprint_id}/capacity", tags=["capacity"])


@router.get("", response_model=list[CapacityMemberRead])
async def get_capacity(sprint_access: SprintAccess, db: DB) -> list[CapacityMemberRead]:
    sprint, org, _m = sprint_access
    rows = await capacity_service.get_capacity(db, org.id, sprint)
    return [CapacityMemberRead.model_validate(row) for row in rows]


@router.put("", response_model=list[CapacityMemberRead])
async def set_capacity(
    data: CapacityUpdate,
    sprint_access: SprintAccess,
    current_user: CurrentUser,
    db: DB,
) -> list[CapacityMemberRead]:
    sprint, org, m = sprint_access
    rows = await capacity_service.set_capacity(db, current_user, org, m, sprint, data)
    return [CapacityMemberRead.model_validate(row) for row in rows]
