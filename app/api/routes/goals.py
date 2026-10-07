"""Goals/OKR routes (M4): CRUD under an org plus task linking."""

import uuid

from fastapi import APIRouter, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import DB, CurrentUser, OrgMembership
from app.schemas.goal import (
    GoalCreate,
    GoalRead,
    GoalTaskLinkRequest,
    GoalUpdate,
)
from app.services import goals as goal_service

router = APIRouter(prefix="/organizations/{slug}/goals", tags=["goals"])


async def _read(db: AsyncSession, org_id: uuid.UUID, goal) -> GoalRead:
    payloads = await goal_service.goal_payloads(db, org_id, [goal])
    return GoalRead.model_validate(payloads[0])


@router.get("", response_model=list[GoalRead])
async def list_goals(membership: OrgMembership, db: DB) -> list[GoalRead]:
    org, _m = membership
    goals = await goal_service.list_goals(db, org.id)
    payloads = await goal_service.goal_payloads(db, org.id, goals)
    return [GoalRead.model_validate(payload) for payload in payloads]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=GoalRead)
async def create_goal(
    data: GoalCreate,
    membership: OrgMembership,
    current_user: CurrentUser,
    db: DB,
) -> GoalRead:
    org, _m = membership
    goal = await goal_service.create_goal(db, current_user, org, data)
    return await _read(db, org.id, goal)


@router.get("/{goal_id}", response_model=GoalRead)
async def get_goal(
    goal_id: uuid.UUID, membership: OrgMembership, db: DB
) -> GoalRead:
    org, _m = membership
    goal = await goal_service.get_goal_for_org(db, goal_id, org.id)
    return await _read(db, org.id, goal)


@router.patch("/{goal_id}", response_model=GoalRead)
async def update_goal(
    goal_id: uuid.UUID,
    data: GoalUpdate,
    membership: OrgMembership,
    current_user: CurrentUser,
    db: DB,
) -> GoalRead:
    org, _m = membership
    goal = await goal_service.get_goal_for_org(db, goal_id, org.id)
    updated = await goal_service.update_goal(db, current_user, org, goal, data)
    return await _read(db, org.id, updated)


@router.delete("/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_goal(
    goal_id: uuid.UUID,
    membership: OrgMembership,
    current_user: CurrentUser,
    db: DB,
) -> None:
    org, _m = membership
    goal = await goal_service.get_goal_for_org(db, goal_id, org.id)
    await goal_service.delete_goal(db, current_user, org, goal)


@router.post("/{goal_id}/tasks", response_model=GoalRead)
async def link_goal_tasks(
    goal_id: uuid.UUID,
    data: GoalTaskLinkRequest,
    membership: OrgMembership,
    current_user: CurrentUser,
    db: DB,
) -> GoalRead:
    org, _m = membership
    goal = await goal_service.get_goal_for_org(db, goal_id, org.id)
    await goal_service.link_tasks(db, current_user, org, goal, data.task_ids)
    return await _read(db, org.id, goal)


@router.delete(
    "/{goal_id}/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def unlink_goal_task(
    goal_id: uuid.UUID,
    task_id: uuid.UUID,
    membership: OrgMembership,
    current_user: CurrentUser,
    db: DB,
) -> None:
    org, _m = membership
    goal = await goal_service.get_goal_for_org(db, goal_id, org.id)
    await goal_service.unlink_task(db, current_user, org, goal, task_id)
