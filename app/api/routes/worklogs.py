"""Worklog + timesheet routes."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Query, Request, status

from app.api.deps import DB, CurrentUser, OrgMembership, TaskAccess
from app.schemas import (
    TimesheetReport,
    WorklogCreate,
    WorklogRead,
    WorklogUpdate,
)
from app.services import worklogs as worklog_service

task_worklog_router = APIRouter(prefix="/tasks/{task_id}/worklogs", tags=["worklogs"])
worklog_router = APIRouter(
    prefix="/organizations/{slug}/worklogs", tags=["worklogs"]
)
timesheet_router = APIRouter(prefix="/organizations/{slug}/timesheet", tags=["worklogs"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _serialize(worklog) -> WorklogRead:
    read = WorklogRead.model_validate(worklog)
    if worklog.user is not None:
        read.user_name = worklog.user.full_name or worklog.user.email
    return read


@task_worklog_router.get("", response_model=list[WorklogRead])
async def list_worklogs(
    task_access: TaskAccess,
    db: DB,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[WorklogRead]:
    task, _org, _m = task_access
    rows = await worklog_service.list_worklogs(db, task.id, offset=offset, limit=limit)
    return [_serialize(row) for row in rows]


@task_worklog_router.post("", status_code=status.HTTP_201_CREATED, response_model=WorklogRead)
async def create_worklog(
    data: WorklogCreate,
    task_access: TaskAccess,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> WorklogRead:
    task, org, _m = task_access
    worklog = await worklog_service.create_worklog(
        db, current_user, org, task, data, ip=_ip(request)
    )
    return _serialize(worklog)


@worklog_router.patch("/{worklog_id}", response_model=WorklogRead)
async def update_worklog(
    worklog_id: uuid.UUID,
    data: WorklogUpdate,
    membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> WorklogRead:
    org, m = membership
    worklog = await worklog_service.get_worklog_for_org(db, worklog_id, org.id)
    updated = await worklog_service.update_worklog(
        db, current_user, org, m, worklog, data, ip=_ip(request)
    )
    return _serialize(updated)


@worklog_router.delete("/{worklog_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_worklog(
    worklog_id: uuid.UUID,
    membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> None:
    org, m = membership
    worklog = await worklog_service.get_worklog_for_org(db, worklog_id, org.id)
    await worklog_service.delete_worklog(
        db, current_user, org, m, worklog, ip=_ip(request)
    )


@timesheet_router.get("", response_model=TimesheetReport)
async def timesheet(
    membership: OrgMembership,
    db: DB,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    user_id: uuid.UUID | None = None,
) -> TimesheetReport:
    org, _m = membership
    start, end = worklog_service.default_window(date_from, date_to)
    report = await worklog_service.timesheet(db, org.id, start, end, user_id)
    return TimesheetReport.model_validate(report)
