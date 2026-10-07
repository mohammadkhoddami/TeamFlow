"""Task repository: tenant-safe fetch, filtered/sorted/paginated listing.

All list queries share one condition builder so the page query and the COUNT
query always apply identical filters. Sorting is whitelist-based; user input
never reaches ORDER BY directly (no column-name injection).
"""

import base64
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, ColumnElement, Text, and_, case
from sqlalchemy import func as sa_func
from sqlalchemy.orm import aliased
from sqlmodel import func, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import (
    CustomFieldValue,
    Label,
    Project,
    Task,
    TaskLabelLink,
    TaskLink,
    TaskStatus,
)

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
    "estimate": Task.estimate,
    "number": Task.number,
    "key": Task.key,
    "backlog_rank": Task.backlog_rank,
}


def fts_condition(column_expression, term: str) -> ColumnElement[bool]:
    """PostgreSQL full-text match using the expression GIN indexes.

    `websearch_to_tsquery` accepts natural input (`auth login -legacy`) and
    never raises on malformed syntax, unlike `to_tsquery`.
    """
    return column_expression.op("@@")(func.websearch_to_tsquery("english", term))


# Must stay byte-identical to the `ix_tasks_search_vector` expression in
# migration c9f31a7d5e21 (use `||`, not concat(), or the GIN index is unused).
TASK_SEARCH_VECTOR = sa_func.to_tsvector(
    "english",
    sa_func.coalesce(Task.title, "")
    .op("||")(" ")
    .op("||")(sa_func.coalesce(Task.description, "")),
)


class TaskFilters:
    """Typed filter bag; validated upstream by FastAPI query params / TeamQL."""

    def __init__(
        self,
        *,
        project_id: uuid.UUID | None = None,
        project_name: str | None = None,
        status: list[str] | None = None,
        categories: list[str] | None = None,
        blocked: bool | None = None,
        custom_filters: list[tuple[uuid.UUID, str, object]] | None = None,
        priority: list[str] | None = None,
        type: list[str] | None = None,
        exclude_status: list[str] | None = None,
        exclude_priority: list[str] | None = None,
        exclude_type: list[str] | None = None,
        parent_id: uuid.UUID | None = None,
        roots_only: bool | None = None,
        assignee_id: uuid.UUID | None = None,
        exclude_assignee_id: uuid.UUID | None = None,
        unassigned: bool | None = None,
        label_id: uuid.UUID | None = None,
        exclude_label_id: uuid.UUID | None = None,
        label_name: str | None = None,
        search: str | None = None,
        text: str | None = None,
        keys: list[str] | None = None,
        exclude_keys: list[str] | None = None,
        sprint_id: uuid.UUID | None = None,
        backlog_only: bool | None = None,
        include_archived: bool | None = None,
        archived_only: bool | None = None,
        due_before: datetime | None = None,
        due_after: datetime | None = None,
        due_empty: bool | None = None,
        overdue: bool | None = None,
        created_before: datetime | None = None,
        created_after: datetime | None = None,
        updated_before: datetime | None = None,
        updated_after: datetime | None = None,
        estimate_min: float | None = None,
        estimate_max: float | None = None,
        estimate_empty: bool | None = None,
    ) -> None:
        self.project_id = project_id
        self.project_name = project_name
        self.status = status or None
        self.categories = categories or None
        self.blocked = blocked
        self.custom_filters = custom_filters or None
        self.priority = priority or None
        self.type = type or None
        self.exclude_status = exclude_status or None
        self.exclude_priority = exclude_priority or None
        self.exclude_type = exclude_type or None
        self.parent_id = parent_id
        self.roots_only = roots_only
        self.assignee_id = assignee_id
        self.exclude_assignee_id = exclude_assignee_id
        self.unassigned = unassigned
        self.label_id = label_id
        self.exclude_label_id = exclude_label_id
        self.label_name = label_name
        self.search = search
        self.text = text
        self.keys = keys or None
        self.exclude_keys = exclude_keys or None
        self.sprint_id = sprint_id
        self.backlog_only = backlog_only
        self.include_archived = include_archived
        self.archived_only = archived_only
        self.due_before = due_before
        self.due_after = due_after
        self.due_empty = due_empty
        self.overdue = overdue
        self.created_before = created_before
        self.created_after = created_after
        self.updated_before = updated_before
        self.updated_after = updated_after
        self.estimate_min = estimate_min
        self.estimate_max = estimate_max
        self.estimate_empty = estimate_empty

    def conditions(self) -> list[ColumnElement[bool]]:
        conds: list[ColumnElement[bool]] = []
        if self.project_id:
            conds.append(Task.project_id == self.project_id)
        if self.project_name:
            conds.append(
                Task.project_id.in_(
                    select(Project.id).where(
                        Project.name.ilike(self.project_name)
                    )
                )
            )
        if self.status:
            conds.append(Task.status.in_(self.status))
        if self.categories:
            conds.append(Task.status_category.in_(self.categories))
        if self.blocked is not None:
            blocker = aliased(Task, name="blocker")
            blocked_exists = (
                select(TaskLink.id)
                .join(blocker, blocker.id == TaskLink.from_task_id)
                .where(
                    TaskLink.to_task_id == Task.id,
                    TaskLink.link_type == "blocks",
                    blocker.status_category != TaskStatus.DONE,
                )
                .exists()
            )
            conds.append(blocked_exists if self.blocked else ~blocked_exists)
        for field_id, op, value in self.custom_filters or []:
            matching = select(CustomFieldValue.task_id).where(
                CustomFieldValue.field_id == field_id
            )
            if op in ("=", "!="):
                candidates = {str(value)}
                try:
                    numeric = float(str(value))
                    candidates.add(str(numeric))
                    candidates.add(f"{numeric:g}")
                except ValueError:
                    pass
                matching = matching.where(
                    sa_func.cast(CustomFieldValue.value, Text).in_(candidates)
                )
            elif op == "~":
                matching = matching.where(
                    sa_func.cast(CustomFieldValue.value, Text).ilike(f"%{value}%")
                )
            else:
                continue
            conds.append(
                Task.id.not_in(matching) if op == "!=" else Task.id.in_(matching)
            )
        if self.priority:
            conds.append(Task.priority.in_(self.priority))
        if self.type:
            conds.append(Task.type.in_(self.type))
        if self.exclude_status:
            conds.append(Task.status.not_in(self.exclude_status))
        if self.exclude_priority:
            conds.append(Task.priority.not_in(self.exclude_priority))
        if self.exclude_type:
            conds.append(Task.type.not_in(self.exclude_type))
        if self.parent_id is not None:
            conds.append(Task.parent_id == self.parent_id)
        if self.roots_only:
            conds.append(Task.parent_id.is_(None))
        if self.assignee_id is not None:
            conds.append(Task.assignee_id == self.assignee_id)
        if self.exclude_assignee_id is not None:
            conds.append(
                or_(
                    Task.assignee_id != self.exclude_assignee_id,
                    Task.assignee_id.is_(None),
                )
            )
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
        if self.exclude_label_id:
            conds.append(
                Task.id.not_in(
                    select(TaskLabelLink.task_id).where(
                        TaskLabelLink.label_id == self.exclude_label_id
                    )
                )
            )
        if self.label_name:
            conds.append(
                Task.id.in_(
                    select(TaskLabelLink.task_id)
                    .join(Label, Label.id == TaskLabelLink.label_id)
                    .where(Label.name.ilike(self.label_name))
                )
            )
        if self.search:
            term = f"%{self.search}%"
            conds.append(
                or_(Task.title.ilike(term), Task.description.ilike(term))
            )
        if self.text:
            conds.append(fts_condition(TASK_SEARCH_VECTOR, self.text))
        if self.keys:
            conds.append(Task.key.in_([k.upper() for k in self.keys]))
        if self.exclude_keys:
            conds.append(Task.key.not_in([k.upper() for k in self.exclude_keys]))
        if self.sprint_id is not None:
            conds.append(Task.sprint_id == self.sprint_id)
        if self.backlog_only:
            conds.append(Task.sprint_id.is_(None))
        if self.archived_only:
            conds.append(Task.archived_at.is_not(None))
        elif not self.include_archived:
            conds.append(Task.archived_at.is_(None))
        if self.due_before is not None:
            conds.append(Task.due_date <= self.due_before)
        if self.due_after is not None:
            conds.append(Task.due_date >= self.due_after)
        if self.due_empty:
            conds.append(Task.due_date.is_(None))
        if self.overdue:
            conds.append(Task.due_date < datetime.now(UTC))
            conds.append(Task.status_category != TaskStatus.DONE)
        if self.created_before is not None:
            conds.append(Task.created_at <= self.created_before)
        if self.created_after is not None:
            conds.append(Task.created_at >= self.created_after)
        if self.updated_before is not None:
            conds.append(Task.updated_at <= self.updated_before)
        if self.updated_after is not None:
            conds.append(Task.updated_at >= self.updated_after)
        if self.estimate_min is not None:
            conds.append(Task.estimate >= self.estimate_min)
        if self.estimate_max is not None:
            conds.append(Task.estimate <= self.estimate_max)
        if self.estimate_empty:
            conds.append(Task.estimate.is_(None))
        return conds


def encode_cursor(created_at: datetime, task_id: uuid.UUID) -> str:
    """Opaque keyset cursor: (created_at, id) of the last row on the page."""
    raw = json.dumps({"t": created_at.isoformat(), "id": str(task_id)}).encode()
    return base64.urlsafe_b64encode(raw).decode()


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """Raises ValueError on malformed cursors (mapped to 422 by the route)."""
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        return datetime.fromisoformat(data["t"]), uuid.UUID(data["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Invalid cursor") from exc


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

    async def list_cursor(
        self,
        organization_id: uuid.UUID,
        filters: TaskFilters,
        *,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[Task], str | None]:
        """Keyset pagination over (created_at DESC, id DESC).

        Unlike OFFSET, the query cost does not grow with page depth: Postgres
        walks `ix_tasks_created` and stops after limit+1 rows. This is the
        hot-path listing for large orgs (M3 #37).
        """
        limit = min(limit, MAX_PAGE_SIZE)
        conds = [Task.organization_id == organization_id, *filters.conditions()]
        if cursor:
            last_time, last_id = decode_cursor(cursor)
            conds.append(
                or_(
                    Task.created_at < last_time,
                    and_(Task.created_at == last_time, Task.id < last_id),
                )
            )
        statement = (
            select(Task)
            .where(*conds)
            .order_by(Task.created_at.desc(), Task.id.desc())
            .limit(limit + 1)
        )
        rows = list((await self.db.execute(statement)).scalars().all())
        has_more = len(rows) > limit
        items = rows[:limit]
        next_cursor = (
            encode_cursor(items[-1].created_at, items[-1].id)
            if has_more and items
            else None
        )
        return items, next_cursor

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
        done_expr = func.sum(case((Task.status_category == TaskStatus.DONE, 1), else_=0))
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
