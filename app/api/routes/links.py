"""Task link/dependency routes."""

import uuid

from fastapi import APIRouter, status

from app.api.deps import DB, CurrentUser, TaskAccess
from app.schemas import TaskLinkCreate, TaskLinkSummary
from app.services import task_links as link_service

task_link_router = APIRouter(prefix="/tasks/{task_id}/links", tags=["links"])


@task_link_router.get("", response_model=TaskLinkSummary)
async def list_links(task_access: TaskAccess, db: DB) -> TaskLinkSummary:
    task, _org, _m = task_access
    return await link_service.list_links(db, task)


@task_link_router.post("", status_code=status.HTTP_201_CREATED, response_model=TaskLinkSummary)
async def create_link(
    data: TaskLinkCreate,
    task_access: TaskAccess,
    current_user: CurrentUser,
    db: DB,
) -> TaskLinkSummary:
    task, org, _m = task_access
    await link_service.create_link(db, current_user, org, task, data)
    return await link_service.list_links(db, task)


@task_link_router.delete("/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_link(
    link_id: uuid.UUID,
    task_access: TaskAccess,
    current_user: CurrentUser,
    db: DB,
) -> None:
    _task, org, _m = task_access
    link = await link_service.get_link_for_org(db, link_id, org.id)
    await link_service.delete_link(db, current_user, org, link)
