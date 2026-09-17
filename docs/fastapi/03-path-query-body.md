# FastAPI 03 — Path, Query, and Body Parameters

## Concept

FastAPI infers where each function parameter comes from:

- declared in the path template → **path parameter**
- a scalar type not in the path → **query parameter** (with `Query()` defaults)
- a Pydantic model → **JSON body**

The function signature *is* the request contract and the OpenAPI schema.

## Why it exists

Manually parsing `request.GET`, `request.POST`, and `request.path` is error-prone
and undocumented. FastAPI makes the request shape visible in the signature and
generates docs from it.

## TeamFlow implementation

### Path parameters

Always typed as the real type, so garbage never reaches handlers:

```python
# app/api/routes/tasks.py
@task_router.get("/{task_id}", response_model=TaskRead)
async def get_task(task_access: TaskAccess) -> TaskRead: ...

# app/api/routes/invitations.py
@router.post("/{invitation_id}/accept", response_model=MembershipRead)
async def accept_invitation(invitation_id: uuid.UUID, ...) -> MembershipRead: ...
```

`/tasks/not-a-uuid` produces a 422 before any DB access. Django would route it
to the view and you'd `get_object_or_404` — here the type system stops it.

### Query parameters — the task list (the richest example)

`app/api/routes/tasks.py`, simplified to the interesting parts:

```python
@org_task_router.get("", response_model=Page[TaskRead])
async def list_tasks(
    membership: OrgMembership,
    db: DB,
    current_user: CurrentUser,
    project_id: uuid.UUID | None = None,
    assignee_id: uuid.UUID | None = None,
    unassigned: bool = False,
    label_id: uuid.UUID | None = None,
    status: list[StatusLiteral] | None = Query(default=None),
    priority: list[PriorityLiteral] | None = Query(default=None),
    search: str | None = Query(default=None, max_length=100),
    due_before: datetime | None = None,
    due_after: datetime | None = None,
    overdue: bool = False,
    sort: str | None = Query(default=None, description="Sortable field, '-' for desc"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=100),
) -> Page[TaskRead]:
```

Things worth noticing (this is a review masterclass):

- **`list[StatusLiteral] | None`** — repeatable query params:
  `?status=todo&status=in_progress`. The `Literal` type rejects typo values
  at validation time.
- **Constraints live in the signature**: `ge=0`, `ge=1, le=100`,
  `max_length=100`. The endpoint cannot receive `limit=100000` — that is a
  performance guard, not decoration.
- **Optional parameters default to `None`/`False`** — the repository's
  `TaskFilters` only adds SQL conditions for values actually present:

```python
# app/repositories/task.py
def conditions(self) -> list[ColumnElement[bool]]:
    conds: list[ColumnElement[bool]] = []
    if self.project_id:
        conds.append(Task.project_id == self.project_id)
    if self.status:
        conds.append(Task.status.in_(self.status))
    ...
    if self.search:
        term = f"%{self.search}%"
        conds.append(or_(Task.title.ilike(term), Task.description.ilike(term)))
```

- **`sort` is a string, not an enum** — because it supports a `-` prefix
  (`-created_at`). It is whitelisted in the repository
  (`parse_sort`), never interpolated into SQL:

```python
SORT_COLUMNS = {"created_at": ..., "priority": Task.priority, ...}

def parse_sort(sort: str | None):
    direction, _, field = sort.partition("-")
    column = SORT_COLUMNS.get(field or sort)
    return column.desc() if ... else column.asc()
```

## Body parameters

```python
# app/schemas/task.py
class TaskCreate(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20_000)
    priority: PriorityLiteral = "medium"
    due_date: datetime | None = None
    assignee_id: uuid.UUID | None = None
    label_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)

class TaskUpdate(SQLModel):
    title: str | None = None
    status: StatusLiteral | None = None
    ...
```

A route may combine both — `/tasks/{task_id}` (path) + body (`TaskUpdate`) +
headers read via `Request` (`ip`).

## The PATCH semantics problem (important)

`TaskUpdate` fields are all optional. "Omitted" and "explicitly null" both arrive
as `None` if you only look at values — but they mean different things for
`assignee_id`. TeamFlow reads **`data.model_fields_set`**:

```python
changed = data.model_fields_set

if "assignee_id" in changed and data.assignee_id != task.assignee_id:
    if data.assignee_id is not None:
        await _assert_assignee_in_org(db, org.id, data.assignee_id)
    task.assignee_id = data.assignee_id        # null => unassign

if "due_date" in changed:
    task.due_date = data.due_date              # null => clear
```

DRF solves the same problem with `partial=True` plus `serializer.validated_data`
membership. Same idea, different mechanism.

## Header parameters

TeamFlow does not model headers as typed parameters because the only custom
header (`Idempotency-Key`) is handled in middleware, where it must run *before*
routing. Headers exist as a concept in a few places:

```python
# app/api/routes/auth.py — ip for audit
def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None
```

If you needed a typed header, it would be
`x_api_version: str = Header(default="1")` — same mechanics as Query.

## Django/DRF comparison 🔵

| DRF | FastAPI |
| --- | --- |
| URL converter `<uuid:pk>` | `task_id: uuid.UUID` |
| `request.query_params.get("status")` + manual validation | `status: list[Literal[...]] \| None = Query(...)` |
| Serializer `validate_status` | `Literal` / `Field(ge=..., le=...)` on the schema |
| `required=False` serializer fields | `X \| None = None` |
| `request.data` (loosely typed dict) | validated Pydantic model |
| `partial=True` + `.validated_data` keys | `model_fields_set` |

The mental shift: in DRF validation is a step *you call*; in FastAPI it happens
*before your function exists*. If your function is running, the input is already
valid.

## Production perspective

- **Bound `limit` everywhere.** TeamFlow caps at 100 and the repository clamps
  again (`min(limit, MAX_PAGE_SIZE)`) — defense in depth against a caller
  bypassing the route.
- **Date filters are typed (`datetime`)** — FastAPI parses ISO-8601. A malformed
  timestamp is a 422, not a 500 deep in the query builder.
- **Multi-value params + indexes**: `status IN (...)` uses the
  `ix_tasks_org_status` index (`database/07-indexes-and-constraints.md`).

## Common mistakes

1. **Stringly-typed ids.** `task_id: str` then `uuid.UUID(task_id)` in the body —
   conversion errors become 500s. Type it in the signature.
2. **No upper bound on `limit`.** One `?limit=1000000` can exhaust a worker.
3. **Using `Query()` where a body belongs** (e.g., sending `new_status` as a
   query param on a POST) — mutating state via query strings breaks caching,
   logging, and idempotency reasoning.
4. **Forgetting `model_fields_set`** and treating `None` as "no change" — users
   can then never clear a field.
5. Booleans as query strings: `?unassigned=false` parses correctly; `?unassigned=0`
   is *not* a Python falsy parse — use `true`/`false`.

## Cheat sheet

```python
@router.get("/{task_id}")                                  # path
async def f(task_id: uuid.UUID, q: str | None = None,      # query (optional)
            limit: int = Query(20, ge=1, le=100),          # query + constraints
            status: list[Literal["todo","done"]] | None = Query(None),
            body: TaskUpdate = ...,                        # JSON body (model)
            request: Request = ...) -> ...: ...
```

## Review questions

1. Why is `status` a `list[Literal[...]]` instead of `str`?
2. Where do `ge=1, le=100` on `limit` actually get enforced, and why does the
   repository clamp again?
3. How does TeamFlow distinguish "set assignee to null" from "don't touch
   assignee"?
4. Why is `sort` not a `Literal` of column names?
