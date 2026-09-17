# Database 04 — Queries (select, filters, aggregates)

## Concept

SQLModel queries are SQLAlchemy 2.0 `select()` statements executed on an
`AsyncSession` via `await session.execute(...)`. TeamFlow wraps every query in a
repository method.

```python
statement = select(User).where(User.email == email)
user = (await self.db.execute(statement)).scalar_one_or_none()
```

## Why not `session.get()` everywhere?

`session.get(Model, pk)` is a convenience for primary-key lookups. TeamFlow uses
it for plain lookups (`db.get(User, user_id)` in `get_current_user`) but uses
`select()` whenever:

- the lookup needs filters (`get_by_email`, `get_for_user`),
- relationships must be eager-loaded (`TaskAccess`), or
- results need ordering/limits/joins.

That last point matters: `select(Task)` honors the mapper's loader strategies
(`lazy="joined"/"selectin"`), while `get()`-on-identity-map-hit may not — a
distinction covered in `database/03-relationships.md`.

## Query patterns in TeamFlow, by file

### Point lookups with a filter — `app/repositories/user.py`

```python
async def get_by_email(self, email: str) -> User | None:
    statement = select(User).where(User.email == email)
    return (await self.db.execute(statement)).scalar_one_or_none()
```

`.scalar_one_or_none()` is the safe idiom: exactly zero or one row, error on
multiplicity. Django's `get()` has the same contract (DoesNotExist /
MultipleObjectsReturned); here the no-row case is a `None` you handle at the
service, and the multi-row case is a `MultipleResultsFound` exception.

### Tenant-scoped fetch — `app/repositories/project.py`

```python
async def get_in_org(self, project_id: uuid.UUID, organization_id: uuid.UUID) -> Project | None:
    statement = select(Project).where(
        Project.id == project_id,
        Project.organization_id == organization_id,
    )
    return (await self.db.execute(statement)).scalar_one_or_none()
```

Note the method *name* encodes the security property: `get_in_org`, not `get`.
You cannot accidentally call `get_in_org` without passing the org, and a
reviewer can grep for `.get(` calls on project/task repositories that skip the
org filter.

### Joined read for authorization — `app/repositories/organization.py`

```python
async def list_for_user(self, user_id, *, offset, limit) -> tuple[list[Organization], list[str]]:
    statement = (
        select(Organization, Membership.role)
        .join(Membership, Membership.organization_id == Organization.id)
        .where(Membership.user_id == user_id)
        .order_by(Organization.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = (await self.db.execute(statement)).all()
    return [row[0] for row in rows], [row[1] for row in rows]
```

Selecting two entities/columns and unzipping into parallel lists — one query
answering "which orgs and with what role". The tuple return is consumed by the
route to build `OrganizationMemberRead`.

### The filtered list builder — `app/repositories/task.py`

The centerpiece. `TaskFilters` is a typed bag:

```python
class TaskFilters:
    def __init__(self, *, project_id=None, status=None, priority=None,
                 assignee_id=None, unassigned=None, label_id=None, search=None,
                 due_before=None, due_after=None, overdue=None): ...

    def conditions(self) -> list[ColumnElement[bool]]:
        conds: list[ColumnElement[bool]] = []
        if self.project_id:
            conds.append(Task.project_id == self.project_id)
        if self.status:
            conds.append(Task.status.in_(self.status))
        if self.priority:
            conds.append(Task.priority.in_(self.priority))
        if self.assignee_id is not None:
            conds.append(Task.assignee_id == self.assignee_id)
        if self.unassigned:
            conds.append(Task.assignee_id.is_(None))
        if self.label_id:
            conds.append(Task.id.in_(
                select(TaskLabelLink.task_id).where(TaskLabelLink.label_id == self.label_id)))
        if self.search:
            term = f"%{self.search}%"
            conds.append(or_(Task.title.ilike(term), Task.description.ilike(term)))
        if self.due_before is not None:
            conds.append(Task.due_date <= self.due_before)
        if self.due_after is not None:
            conds.append(Task.due_date >= self.due_after)
        if self.overdue:
            conds.append(Task.due_date < datetime.now(UTC))
            conds.append(Task.status != "done")
        return conds
```

Why this shape matters:

1. **One condition builder feeds both the page query and the COUNT query** —
   pagination totals can never drift from the filter set:

```python
conds = [Task.organization_id == organization_id, *filters.conditions()]
items = list((await self.db.execute(
    select(Task).where(*conds).order_by(parse_sort(sort)).offset(offset).limit(...)
)).scalars().all())
total = (await self.db.execute(select(func.count(Task.id)).where(*conds))).scalar_one()
```

2. **`label_id` uses a subquery, not a join** — no row duplication and no
   `DISTINCT` needed:

```python
Task.id.in_(select(TaskLabelLink.task_id).where(TaskLabelLink.label_id == self.label_id))
```

3. **`search` uses `ILIKE`** (case-insensitive) with parameter binding — the
   `%...%` term is a bound parameter, never string-interpolated SQL. SQL
   injection is structurally impossible here.

4. **`unassigned` and `assignee_id` are separate flags** — "tasks with no
   assignee" (`is_(None)`) is a different query from "tasks assigned to X".

### Sorting — whitelist, not f-string

```python
SORT_COLUMNS = {
    "created_at": Task.created_at,
    "updated_at": Task.updated_at,
    "title": Task.title,
    "priority": Task.priority,
    "status": Task.status,
    "due_date": Task.due_date,
}

def parse_sort(sort: str | None):
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
```

The client sends `-priority`; the server maps it through a dict to a **column
object**. No user string ever reaches `ORDER BY`. Unknown fields fall back to
`created_at DESC` (silent) — an alternative would be a 422; TeamFlow documents
the fallback in the route's docstring.

### Aggregates — `app/services/dashboard.py`

```python
by_status_rows = (await db.execute(
    select(Task.status, func.count(Task.id))
    .where(Task.organization_id == organization_id)
    .group_by(Task.status)
)).all()
by_status = {row[0]: row[1] for row in by_status_rows}
```

```python
extra = (await db.execute(
    select(
        func.count(Task.id).filter(Task.due_date < now, Task.status != TaskStatus.DONE),
        func.count(Task.id).filter(Task.assignee_id.is_(None), Task.status != TaskStatus.DONE),
    ).where(Task.organization_id == organization_id)
)).one()
```

Two techniques worth stealing:

- **`GROUP BY` instead of Python counting** — one row per status, not one row
  per task.
- **`FILTER (WHERE ...)` aggregated counts** — overdue and unassigned computed
  in a single query, rendered as `count(tasks.id) FILTER (WHERE ...)`. This is
  standard SQL PostgreSQL supports well.

Per-member stats use a join + group + limit:

```python
select(User.id, User.full_name, func.count(Task.id))
.join(Task, Task.assignee_id == User.id)
.where(Task.organization_id == organization_id, Task.status != TaskStatus.DONE)
.group_by(User.id, User.full_name)
.order_by(func.count(Task.id).desc())
.limit(20)
```

## Django ORM comparison 🔵

| Django | SQLModel |
| --- | --- |
| `User.objects.filter(email=e).first()` | `select(User).where(...)` + `.scalar_one_or_none()` |
| `Org.objects.annotate(n=Count("tasks"))` | `select(..., func.count(...)).group_by(...)` |
| `Q(title__icontains=q) \| Q(desc__icontains=q)` | `or_(Task.title.ilike(...), ...)` |
| `.order_by("-priority")` | `parse_sort("-priority")` → column objects |
| `.values("status").annotate(n=Count("id"))` | `select(Task.status, func.count(Task.id)).group_by(...)` |
| `Count("x", filter=Q(...))` | `func.count(...).filter(...)` |

Django builds SQL from keyword strings with a lookup DSL. SQLAlchemy builds it
from Python *expressions* — more verbose, fully typed, and composable as
values (hence `TaskFilters.conditions()` returning a list).

## Production perspective

- **Parameter binding everywhere.** Queries are compiled with bound parameters;
  no concatenation exists in the codebase.
- **`COUNT` queries use the same WHERE as the page** — no drift, at the cost of
  one extra query per list call. For very large tables, keyset pagination
  replaces `OFFSET` (noted in `database/09-database-performance.md`).
- **`ILIKE '%term%'` cannot use a B-tree index** — full scan at scale. The fix
  is a `pg_trgm` GIN index; noted as a scale path, not needed at this size.
- **Search is capped** (`max_length=100`) at the API edge and only scans
  `title`/`description`, not JSON columns.

## Common mistakes

1. **`f"SELECT ... WHERE x = '{term}'"`** anywhere — SQL injection. Never seen
   in TeamFlow; `text()` is used only for `SELECT 1` health checks.
2. **Building `ORDER BY` from user input** — solved by the `SORT_COLUMNS`
   whitelist.
3. **Counting in Python** (`len(await ...all())`) — loads every row; use
   `func.count`.
4. **Filtering label membership with a join** without `DISTINCT` — duplicate
   task rows. Subquery avoids it.
5. **`.scalar()` vs `.scalar_one_or_none()`**: the former returns the first row
   of possibly many (silent bug). Be explicit about expected multiplicity.

## Cheat sheet

```python
select(Model).where(*conds).order_by(col).offset(o).limit(l)
(await db.execute(stmt)).scalars().all()          # models
(await db.execute(stmt)).scalar_one_or_none()     # 0..1
select(func.count(Model.id)).where(*conds)        # count
select(func.count(X).filter(cond1, cond2))        # filtered count
select(A, B).join(B, ...).group_by(...)           # multi-column
```

## Review questions

1. Why does `list_for_org` reuse `filters.conditions()` for both items and count?
2. How does `parse_sort` prevent SQL injection without validating against an
   enum?
3. Why is `label_id` a subquery instead of a join?
4. Where could `ILIKE '%x%'` become a performance problem, and what is the
   standard PostgreSQL fix?
