"""Task repository: tenant-safe fetch, filtered/sorted/paginated listing.

All list queries share one condition builder so the page query and the COUNT
query always apply identical filters. Sorting is whitelist-based; user input
never reaches ORDER BY directly (no column-name injection).
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, ColumnElement, case
from sqlmodel import func, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Task, TaskLabelLink, TaskStatus

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
# Hard ceiling for tree assembly so one gigantic project cannot blow up the
# response or the in-memory grouping.
MAX_TREE_SIZE = 2000

SORT_COLUMNS = {
    "created_at": Task.created_at,
    "updated_at": Task.updated_at,
    "title": Task.title,
    "priority": Task.priority,
    "status": Task.status,
    "due_date": Task.due_date,
    "type": Task.type,
}


class TaskFilters:
    """Typed filter bag; validated upstream by FastAPI query params."""

    def __init__(
        self,
        *,
        project_id: uuid.UUID | None = None,
        status: list[str] | None = None,
        priority: list[str] | None = None,
        type: list[str] | None = None,
        parent_id: uuid.UUID | None = None,
        roots_only: bool | None = None,
        assignee_id: uuid.UUID | None = None,
        unassigned: bool | None = None,
        label_id: uuid.UUID | None = None,
        search: str | None = None,
        due_before: datetime | None = None,
        due_after: datetime | None = None,
        overdue: bool | None = None,
    ) -> None:
        self.project_id = project_id
        self.status = status or None
        self.priority = priority or None
        self.type = type or None
        self.parent_id = parent_id
        self.roots_only = roots_only
        self.assignee_id = assignee_id
        self.unassigned = unassigned
        self.label_id = label_id
        self.search = search
        self.due_before = due_before
        self.due_after = due_after
        self.overdue = overdue

    def conditions(self) -> list[ColumnElement[bool]]:
        conds: list[ColumnElement[bool]] = []
        if self.project_id:
            conds.append(Task.project_id == self.project_id)
        if self.status:
            conds.append(Task.status.in_(self.status))
        if self.priority:
            conds.append(Task.priority.in_(self.priority))
        if self.type:
            conds.append(Task.type.in_(self.type))
        if self.parent_id is not None:
            conds.append(Task.parent_id == self.parent_id)
        if self.roots_only:
            conds.append(Task.parent_id.is_(None))
        if self.assignee_id is not None:
            conds.append(Task.assignee_id == self.assignee_id)
        if self.unassigned:
            conds.append(Task.assignee_id.is_(None))
        if self.label_id:
            conds.append(
                Task.id.in_(
                    select(TaskLabelLink.task_id).where(
                        TaskLabelLink.label_id == self.label_id
                    )
                )
            )
        if self.search:
            term = f"%{self.search}%"
            conds.append(
                or_(Task.title.ilike(term), Task.description.ilike(term))
            )
        if self.due_before is not None:
            conds.append(Task.due_date <= self.due_before)
        if self.due_after is not None:
            conds.append(Task.due_date >= self.due_after)
        if self.overdue:
            conds.append(Task.due_date < datetime.now(UTC))
            conds.append(Task.status != "done")
        return conds


def parse_sort(sort: str | None) -> ColumnElement | Column:
    """'-priority' -> Task.priority DESC; unknown fields fall back to created_at."""
    if not sort:
        return Task.created_at.desc()
    direction, _, field = sort.partition("-")
    if direction == "":  # leading dash
        column = SORT_COLUMNS.get(field)
        if column is not None:
            return column.desc()
        return Task.created_at.desc()
    column = SORT_COLUMNS.get(sort)
    if column is None:
        return Task.created_at.desc()
    return column.asc()


class TaskRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, task_id: uuid.UUID) -> Task | None:
        return await self.db.get(Task, task_id)

    async def get_in_org(self, task_id: uuid.UUID, organization_id: uuid.UUID) -> Task | None:
        """Tenant-safe single fetch: relationships eager-load (no N+1 later)."""
        statement = select(Task).where(
            Task.id == task_id,
            Task.organization_id == organization_id,
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def list_for_org(
        self,
        organization_id: uuid.UUID,
        filters: TaskFilters,
        *,
        offset: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
        sort: str | None = None,
    ) -> tuple[list[Task], int]:
        conds = [Task.organization_id == organization_id, *filters.conditions()]
        statement = (
            select(Task)
            .where(*conds)
            .order_by(parse_sort(sort))
            .offset(offset)
            .limit(min(limit, MAX_PAGE_SIZE))
        )
        items = list((await self.db.execute(statement)).scalars().all())
        count_stmt = select(func.count(Task.id)).where(*conds)
        total = (await self.db.execute(count_stmt)).scalar_one()
        return items, total

    async def list_children(
        self,
        organization_id: uuid.UUID,
        parent_id: uuid.UUID,
        *,
        limit: int = MAX_PAGE_SIZE,
    ) -> list[Task]:
        """Direct children of one task, shallowest level first."""
        statement = (
            select(Task)
            .where(
                Task.organization_id == organization_id,
                Task.parent_id == parent_id,
            )
            .order_by(Task.type.asc(), Task.created_at.asc())
            .limit(min(limit, MAX_TREE_SIZE))
        )
        return list((await self.db.execute(statement)).scalars().all())

    async def list_for_project(
        self,
        organization_id: uuid.UUID,
        project_id: uuid.UUID,
        *,
        limit: int = MAX_TREE_SIZE,
    ) -> list[Task]:
        """Bounded full-project fetch used to assemble the hierarchy tree."""
        statement = (
            select(Task)
            .where(
                Task.organization_id == organization_id,
                Task.project_id == project_id,
            )
            .order_by(Task.type.asc(), Task.created_at.asc())
            .limit(min(limit, MAX_TREE_SIZE))
        )
        return list((await self.db.execute(statement)).scalars().all())

    async def child_stats(
        self,
        organization_id: uuid.UUID,
        parent_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, tuple[int, int]]:
        """`parent_id -> (direct child count, done child count)` in one query.

        Batched for list endpoints so progress badges never cause N+1.
        """
        if not parent_ids:
            return {}
        done_expr = func.sum(case((Task.status == TaskStatus.DONE, 1), else_=0))
        statement = (
            select(Task.parent_id, func.count(Task.id), done_expr)
            .where(
                Task.organization_id == organization_id,
                Task.parent_id.in_(parent_ids),
            )
            .group_by(Task.parent_id)
        )
        rows = (await self.db.execute(statement)).all()
        return {row[0]: (int(row[1]), int(row[2] or 0)) for row in rows}

    async def children_types(self, task_id: uuid.UUID) -> list[str]:
        statement = select(Task.type).where(Task.parent_id == task_id)
        return list((await self.db.execute(statement)).scalars().all())

    async def get_parent_id(self, task_id: uuid.UUID) -> uuid.UUID | None:
        """Immediate parent id (None for roots) — used for cycle checks."""
        statement = select(Task.parent_id).where(Task.id == task_id)
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def add(self, task: Task) -> Task:
        self.db.add(task)
        await self.db.flush()
        return task

    async def update(self, task: Task) -> Task:
        self.db.add(task)
        await self.db.flush()
        return task

    async def delete(self, task: Task) -> None:
        await self.db.delete(task)
        await self.db.flush()
