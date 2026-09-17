# FastAPI 04 — Response Models & Status Codes

## Concept

`response_model=` declares what a route returns. FastAPI validates the returned
object against it, **filters out undeclared fields**, and uses it for the
OpenAPI schema.

## Why it exists

Two problems in one feature:

1. **Accidental leakage.** Return a SQLModel `User` and `hashed_password` goes
   over the wire. A response model is an allow-list, not a shape hint.
2. **Contract drift.** Without a declared response, docs describe nothing.

## TeamFlow implementation

### The allow-list pattern

`app/schemas/auth.py`:

```python
class UserRead(SQLModel):
    id: uuid.UUID
    email: str
    full_name: str
    is_active: bool
    created_at: datetime
```

`hashed_password` is not in the schema → cannot leak, even though the route
returns the ORM object:

```python
@router.get("/me", response_model=UserRead)
async def me(current_user: CurrentUser) -> UserRead:
    return UserRead.model_validate(current_user)
```

TeamFlow goes further and often validates explicitly
(`model_validate`) rather than relying on FastAPI's coercion, which keeps the
mapping visible in the router.

### Nested responses

`app/schemas/task.py`:

```python
class TaskRead(SQLModel):
    id: uuid.UUID
    ...
    assignee: UserRead | None = None
    creator: UserRead | None = None
    labels: list[LabelRead] = Field(default_factory=list)
    watcher_ids: list[uuid.UUID] = Field(default_factory=list)
```

The nested objects are populated from eager-loaded relationships — see
`app/api/routes/tasks.py`:

```python
def _serialize(task) -> TaskRead:
    read = TaskRead.model_validate(task)
    read.watcher_ids = [w.id for w in task.watchers]
    return read
```

`watcher_ids` is derived (not a column), which is why it is assigned after
validation. If the relationship were lazily loaded, this line would explode in
async (`MissingGreenlet`) or silently N+1 — the eager strategies in
`app/models/task.py` are what make it a no-op cost-wise.

### Generic pages

`app/schemas/common.py`:

```python
ItemT = TypeVar("ItemT")

class Page(BaseModel, Generic[ItemT]):
    items: list[ItemT]
    total: int
    offset: int
    limit: int
```

Used as `response_model=Page[TaskRead]` in the task list. Pydantic v2 generics
give you per-instantiation JSON schemas in `/docs` for free.

### Status codes

```python
@router.post("", status_code=status.HTTP_201_CREATED, response_model=UserRead)
async def register(...): ...

@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(...) -> None: ...
```

- 201 for created resources (register, org/project/task/label/comment/webhook...
  — webhook creation returns **201** with the plaintext secret *once*:
  `WebhookCreated`).
- 204 for deletes and "action acknowledgements" (watchers/me, logout,
  mark-all-read returns a body instead — it reports `{marked: n}`).
- 202 for `forgot-password` — accepted, no information disclosed.

Note the deliberate choices a reviewer should check: `POST /auth/refresh` returns
**200** (it creates a new token pair but the resource is the session — 200 is
idiomatic); `POST /tasks/{id}/move` returns **200** with the updated task, not
204, because the client needs the new state including `completed_at`.

### Response headers

TeamFlow sets headers where status alone is insufficient:

- `Idempotency-Replayed: true` on replayed responses
  (`app/core/idempotency.py`, and exposed via CORS
  `expose_headers=[...]`).
- `Retry-After` on 429s and 409-in-flight — carried by the exception:

```python
class RateLimitError(AppError):
    def __init__(self, detail=None, retry_after=None):
        super().__init__(detail)
        if retry_after is not None:
            self.headers = {"Retry-After": str(retry_after)}
```

`WWW-Authenticate: Bearer` on 401s (`UnauthorizedError.headers`) — required by
the OAuth2 spec for token endpoints.

## Django/DRF comparison 🔵

| DRF | FastAPI |
| --- | --- |
| Serializer for input and output | schemas for input, separate `Read` schemas for output |
| `fields = [...]` / `exclude` | declared fields = allow-list |
| `Response(data, status=201)` | `status_code=` on the decorator + return value |
| `SerializerMethodField` | computed field assigned after validation (`watcher_ids`) |
| `PageNumberPagination` envelope | `Page[T]` generic schema |

DRF's default is "whatever the serializer declares"; FastAPI's default is
"whatever you return" — the response model is opt-in, which is why reviewers
must check every route has one (all 46 routes in TeamFlow declare one, or use
`204`/`None`).

## Production perspective

- Filtering costs a little CPU per response but prevents entire classes of
  incidents (leaked password hashes, internal flags, future columns).
- `response_model` is **not** a serializer for DB writes — it never touches the
  database.
- Changing a response model is a breaking API change; treat `app/schemas/` as a
  public contract in review.

## Common mistakes

1. **Returning ORM objects from routes without `response_model`** — SQLModel
   will happily serialize `hashed_password`.
2. **Reusing one schema for create and read.** A `UserRead` with
   `hashed_password` added for an internal path defeats the allow-list; TeamFlow
   keeps `UserCreate`/`UserUpdate`/`UserRead` separate.
3. **Returning 200 for everything.** Use 201/202/204 deliberately — clients and
   metrics depend on it.
4. **Declaring `response_model` but returning a different shape** and relying on
   coercion — it "works" until a field is missing and you get a 500 at
   serialization time. TeamFlow's `model_validate` calls make failures happen at
   one obvious line.

## Cheat sheet

```python
@router.post("", status_code=201, response_model=TaskRead)
async def create(...) -> TaskRead: return TaskRead.model_validate(task)

@router.delete("/{id}", status_code=204)
async def delete(...) -> None: ...

@router.get("", response_model=Page[TaskRead])
async def list(...) -> Page[TaskRead]:
    return Page(items=[...], total=n, offset=o, limit=l)
```

## Review questions

1. Where exactly is `hashed_password` prevented from leaving the API?
2. Why does TeamFlow assign `watcher_ids` after `model_validate` instead of
   adding a property to the model?
3. Why 202 for forgot-password? What would 404 leak?
4. Why does the webhook *create* response include the secret but no other
   webhook response does?
