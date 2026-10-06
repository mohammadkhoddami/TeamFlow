"""Calendar view route (M3 #17)."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Query

from app.api.deps import DB, OrgMembership
from app.schemas import CalendarResponse, CalendarTaskRead
from app.services import calendar as calendar_service

router = APIRouter(prefix="/organizations/{slug}/calendar", tags=["calendar"])


@router.get("", response_model=CalendarResponse)
async def get_calendar(
    org_membership: OrgMembership,
    db: DB,
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    project_id: uuid.UUID | None = Query(default=None),
    assignee: str | None = Query(default=None, description="'me' or a user UUID"),
) -> CalendarResponse:
    org, _membership = org_membership
    assignee_id: uuid.UUID | None = None
    if assignee == "me":
        assignee_id = org_membership[1].user_id
    elif assignee:
        try:
            assignee_id = uuid.UUID(assignee)
        except ValueError:
            assignee_id = None
    window_start, window_end, rows = await calendar_service.calendar_tasks(
        db,
        org,
        start=start,
        end=end,
        project_id=project_id,
        assignee_id=assignee_id,
    )
    return CalendarResponse(
        start=window_start,
        end=window_end,
        tasks=[
            CalendarTaskRead(
                id=task.id,
                key=task.key,
                title=task.title,
                due_date=task.due_date,
                status=task.status,
                status_category=task.status_category,
                priority=task.priority,
                type=task.type,
                project_id=task.project_id,
                project_name=project_name,
                estimate=task.estimate,
                assignee=task.assignee,
            )
            for task, project_name in rows
        ],
    )
