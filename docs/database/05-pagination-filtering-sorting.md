# Database 05 — Pagination, Filtering, Sorting

## Concept

Pagination is offset-based (`offset`/`limit`) across TeamFlow, wrapped in a
generic envelope:

```python
class Page(BaseModel, Generic[ItemT]):
    items: list[ItemT]
    total: int
    offset: int
    limit: int
```

Filtering and sorting are *declared in the route signature*, translated to SQL
in the repository (`database/04-queries.md`).

## Why offset-based (and its cost)

Offset pagination is trivial to implement, works with any sort order, and lets
clients jump to arbitrary pages. Its cost grows with the offset: the database
scans and discards `offset` rows.

At TeamFlow's scale that's fine. The upgrade path (keyset/cursor pagination) is
documented in `database/09-database-performance.md`; the API shape (`Page[T]`)
would survive it (cursor field instead of offset).

## TeamFlow implementation

### The route — `app/api/routes/tasks.py`

```python
@org_task_router.get("", response_model=Page[TaskRead])
async def list_tasks(
    ...,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=100),
) -> Page[TaskRead]:
    org, _m = membership
    filters = TaskFilters(...)
    items, total = await TaskRepository(db).list_for_org(
        org.id, filters, offset=offset, limit=limit, sort=sort
    )
    return Page[TaskRead](
        items=[_serialize(t) for t in items], total=total, offset=offset, limit=limit
    )
```

Three layers of limit enforcement:

1. Query param: `ge=1, le=100` → 422 outside the range.
2. `DEFAULT_PAGE_SIZE` (20) is the default; `MAX_PAGE_SIZE` is 100.
3. Repository clamps again: `.limit(min(limit, MAX_PAGE_SIZE))` — defense in
   depth so a future caller (Celery task, script) can't bypass the route.

### The repository — page + count

```python
async def list_for_org(self, organization_id, filters, *, offset=0, limit=DEFAULT_PAGE_SIZE, sort=None):
    conds = [Task.organization_id == organization_id, *filters.conditions()]
    statement = (select(Task).where(*conds)
                 .order_by(parse_sort(sort))
                 .offset(offset).limit(min(limit, MAX_PAGE_SIZE)))
    items = list((await self.db.execute(statement)).scalars().all())
    total = (await self.db.execute(select(func.count(Task.id)).where(*conds))).scalar_one()
    return items, total
```

`total` is computed with the same conditions (see `database/04`) so
`Page.total` is the count of the *filtered* set, not the table.

### Which endpoints paginate what

| Endpoint | Pagination | Default / max |
| --- | --- | --- |
| `GET /organizations/{slug}/tasks` | offset/limit | 20 / 100 |
| `GET /organizations` | offset/limit | 20 / 100 |
| `GET /organizations/{slug}/members` | offset/limit | 50 / 200 |
| `GET /tasks/{id}/comments` | offset/limit | 50 / 200 |
| `GET /notifications` | offset/limit | 20 / 100 |
| `GET /organizations/{slug}/audit-logs` | offset/limit | 50 / 200 |
| `GET /organizations/{slug}/webhooks/{id}/deliveries` | offset/limit | 50 / 200 |
| `GET /projects` (per org), labels, webhooks | `limit` only (bounded lists) | 100 / 100–200 |

Bounded lists (projects/labels/webhooks) are realistically small per org; they
still cap `limit` so a hostile client can't request everything.

### Filtering semantics worth knowing

- **Multi-value**: `?status=todo&status=in_progress` → SQL `IN`. Repeated query
  params map to `list[Literal[...]]`.
- **Search**: `?search=payment` → `ILIKE` on title/description.
- **Overdue**: `?overdue=true` → `due_date < now() AND status != 'done'`.
- **Unassigned**: `?unassigned=true` → `assignee_id IS NULL`.
- **Date windows**: `?due_before=...&due_after=...` → typed `datetime`
  comparisons.
- **Combined filters AND together.** There is no OR-across-filters feature.

### Sorting

`?sort=-created_at` (desc), `?sort=title` (asc), unknown → `created_at DESC`.
Always deterministic? Almost — sorting by non-unique columns (`priority`) can
produce unstable page boundaries between requests. Adding a tiebreaker
(`.order_by(col, Task.id)`) is the standard hardening; TeamFlow relies on
`created_at` defaults for most flows. Noted as a known trade-off.

## Django/DRF comparison 🔵

| DRF | TeamFlow |
| --- | --- |
| `PageNumberPagination` (`?page=2&page_size=20`) | `?offset=40&limit=20` |
| `LimitOffsetPagination` | exactly this — chosen for its explicitness |
| `filter_backends = [DjangoFilterBackend]` | explicit query params → `TaskFilters` |
| `OrderingFilter` (`?ordering=-created_at`) | `?sort=-created_at` with a whitelist |
| `SearchFilter` (`?search=`) | `ILIKE` across title+description |

DRF hides pagination/filtering behind classes you configure; TeamFlow keeps it
in the signature and the repository so the SQL is visible next to the source of
the parameters.

## Production perspective

- **`total` costs an extra COUNT.** For very large tables, teams often make
  `total` optional (`?with_total=false`) or approximate. Not needed here.
- **Offset pagination + concurrent writes** can skip/duplicate rows between
  pages. Acceptable for task boards; unacceptable for financial ledgers
  (keyset pagination again).
- **`le=100` is a DoS control.** Without it, `?limit=10_000_000` forces the ORM
  to build a huge result.
- **Total pages** = `ceil(total / limit)` — clients compute it; the server
  doesn't send it (one less derived value to drift).

## Common mistakes

1. **`limit` with no upper bound** — memory and latency incident waiting to
   happen.
2. **Counting the unfiltered table** for `total` — pagination controls show the
   wrong page count.
3. **String-concatenated ORDER BY** — injection surface (solved by
   `SORT_COLUMNS`).
4. **No stable tiebreaker** when sorting by low-cardinality columns — page
   overlap/duplication under concurrent writes.
5. **Returning a bare list** instead of a page envelope — clients can't tell
   whether more data exists.

## Cheat sheet

```python
# route
offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)
# repo
select(M).where(*conds).order_by(parse_sort(sort)).offset(offset).limit(min(limit, MAX))
count = select(func.count(M.id)).where(*conds)
# envelope
Page(items=[...], total=count, offset=offset, limit=limit)
```

## Review questions

1. Why is the limit clamped in two places?
2. What exact SQL condition does `?overdue=true` produce?
3. Why does `total` come from a second query rather than `len(items)`?
4. When would offset pagination give a client duplicate rows, and what is the
   alternative?
