"""Calendar view data source (M3 #17).

Returns every non-archived task with a due date in [start, end), org-scoped,
optionally filtered by project/assignee. The frontend renders month/week grids
and reschedules by PATCHing `due_date` through the normal task endpoint.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Organization, Project, Task

MAX_CALENDAR_TASKS = 2000


def default_window(anchor: datetime | None = None) -> tuple[datetime, datetime]:
    """The month containing `anchor` (or now), padded to full weeks."""
    anchor = anchor or datetime.now(UTC)
    start = anchor.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        next_month = start.replace(year=start.year + 1, month=1)
    else:
        next_month = start.replace(month=start.month + 1)
    end = next_month
    # Pad to week boundaries for a stable 5-6 week grid.
    start -= timedelta(days=(start.weekday() + 1) % 7)  # week starts Sunday
    end += timedelta(days=(6 - end.weekday()) % 7)
    end = end + timedelta(days=1)  # exclusive upper bound
    return start, end


async def calendar_tasks(
    db: AsyncSession,
    org: Organization,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    project_id: uuid.UUID | None = None,
    assignee_id: uuid.UUID | None = None,
) -> tuple[datetime, datetime, list[tuple[Task, str]]]:
    if start is None or end is None:
        default_start, default_end = default_window(start)
        start = start or default_start
        end = end or default_end
    if end <= start:
        end = start + timedelta(days=1)

    conds = [
        Task.organization_id == org.id,
        Task.due_date.is_not(None),
        Task.due_date >= start,
        Task.due_date < end,
        Task.archived_at.is_(None),
    ]
    if project_id is not None:
        conds.append(Task.project_id == project_id)
    if assignee_id is not None:
        conds.append(Task.assignee_id == assignee_id)

    statement = (
        select(Task, Project.name)
        .join(Project, Project.id == Task.project_id)
        .where(*conds)
        .order_by(Task.due_date.asc())
        .limit(MAX_CALENDAR_TASKS)
    )
    rows = (await db.execute(statement)).all()
    return start, end, [(row[0], row[1]) for row in rows]
