"""Label routes: org-scoped label CRUD + task label assignment."""

import uuid

from fastapi import APIRouter, Query, Request, status
from sqlmodel import SQLModel

from app.api.deps import DB, CurrentUser, LabelAccess, OrgMembership, TaskAccess
from app.schemas import LabelCreate, LabelRead, LabelUpdate, TaskUpdate
from app.services import labels as label_service
from app.services import tasks as task_service

router = APIRouter(prefix="/organizations/{slug}/labels", tags=["labels"])
label_router = APIRouter(prefix="/labels", tags=["labels"])
task_label_router = APIRouter(prefix="/tasks/{task_id}/labels", tags=["labels"])


class LabelAssign(SQLModel):
    label_id: uuid.UUID


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("", status_code=status.HTTP_201_CREATED, response_model=LabelRead)
async def create_label(
    data: LabelCreate,
    membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> LabelRead:
    org, m = membership
    label = await label_service.create_label(db, current_user, org, m, data, ip=_ip(request))
    return LabelRead.model_validate(label)


@router.get("", response_model=list[LabelRead])
async def list_labels(
    membership: OrgMembership,
    db: DB,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
) -> list[LabelRead]:
    org, _m = membership
    labels = await label_service.list_labels(db, org.id, offset=offset, limit=limit)
    return [LabelRead.model_validate(l) for l in labels]


@label_router.get("/{label_id}", response_model=LabelRead)
async def get_label(label_access: LabelAccess) -> LabelRead:
    label, _org, _m = label_access
    return LabelRead.model_validate(label)


@label_router.patch("/{label_id}", response_model=LabelRead)
async def update_label(
    data: LabelUpdate,
    label_access: LabelAccess,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> LabelRead:
    label, org, m = label_access
    updated = await label_service.update_label(
        db, current_user, org, m, label, data, ip=_ip(request)
    )
    return LabelRead.model_validate(updated)


@label_router.delete("/{label_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_label(
    label_access: LabelAccess,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> None:
    label, org, m = label_access
    await label_service.delete_label(db, current_user, org, m, label, ip=_ip(request))


@task_label_router.post("", status_code=status.HTTP_201_CREATED, response_model=list[LabelRead])
async def assign_label(
    data: LabelAssign,
    task_access: TaskAccess,
    current_user: CurrentUser,
    db: DB,
) -> list[LabelRead]:
    task, org, _m = task_access
    task = await task_service.update_task(
        db, current_user, org, task, TaskUpdate(label_ids=_existing_ids(task) + [data.label_id])
    )
    return [LabelRead.model_validate(l) for l in task.labels]


@task_label_router.delete("/{label_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unassign_label(
    label_id: uuid.UUID, task_access: TaskAccess, current_user: CurrentUser, db: DB
) -> None:
    task, org, _m = task_access
    remaining = [i for i in _existing_ids(task) if i != label_id]
    await task_service.update_task(
        db, current_user, org, task, TaskUpdate(label_ids=remaining)
    )


def _existing_ids(task) -> list[uuid.UUID]:
    return [l.id for l in task.labels]
