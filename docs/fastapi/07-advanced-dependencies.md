# FastAPI 07 — Advanced Dependencies

## Concept

Beyond simple `Depends(fn)`: dependencies that **yield** (setup/teardown),
dependencies parameterized at declaration time, dependencies that raise
domain errors, and dependency overrides for tests.

## Why it exists

Real applications need per-request resources with cleanup (DB sessions, clients),
configurable dependencies (rate limiters with different budgets), and test
seams. This lesson is where FastAPI's DI system proves it is a DI system, not
syntax sugar.

## 1. Generator (yield) dependencies — lifecycle

`app/core/db.py`:

```python
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
```

- Code before `yield` runs before the handler; after `yield` runs after the
  response (success **or** exception; FastAPI throws the exception into the
  generator).
- The session's context manager closes the connection and rolls back any
  uncommitted transaction — the safety net behind "services own commits".

`RedisDep` is a plain function because the Redis client is process-wide and
closed in the app lifespan, not per request:

```python
# app/core/redis.py
def get_redis_client() -> Redis: ...      # module-level singleton

async def get_redis() -> AsyncIterator[Redis]:
    yield get_redis_client()              # teardown happens at shutdown
```

Contrast with `Storage`: `StorageClient.from_settings()` constructs a
lightweight MinIO wrapper per request (the SDK client is stateless apart from
config), so no teardown is needed.

**Rule of thumb:** if the resource is expensive to create or holds a
connection → yield dependency scoped to request. If it is process-global with a
shutdown path → lifespan + plain accessor.

## 2. Parameterized dependency factories

Rate limiting needs the same logic with different budgets and scopes.
`app/core/rate_limit.py`:

```python
def ip_rate_limiter(scope: str, max_hits: int | None = None, window: int | None = None):
    if max_hits is None:
        max_hits = settings.auth_rate_limit_max
    if window is None:
        window = settings.auth_rate_limit_window

    async def _limit(request: Request, redis_client: RedisDep) -> None:
        if not settings.rate_limit_enabled:
            return
        await hit_rate_limit(redis_client, scope, client_ip(request), max_hits, window)

    return _limit
```

Used in `app/api/routes/auth.py`:

```python
@router.post("/register", status_code=201, response_model=UserRead)
async def register(
    data: UserCreate,
    request: Request,
    db: DB,
    _rl: None = Depends(ip_rate_limiter(
        "register",
        settings.register_rate_limit_max,
        settings.register_rate_limit_window,
    )),
) -> UserRead: ...
```

Why a factory instead of three near-identical dependencies? Because the
**budget** is configuration, and the **scope** string (`"auth_ip"`,
`"register"`, `"password_reset"`) is what separates Redis keys
(`teamflow:rl:{scope}:{identity}`). The dependency itself contains zero
duplication.

Note `_rl: None` — the dependency returns nothing; it either passes or raises
`RateLimitError` (429 with `Retry-After`). Dependencies are also a *guard*
mechanism, not just a provider mechanism.

## 3. Dependencies that perform authorization (raise)

`app/core/exceptions.py` defines the error hierarchy; dependencies raise it:

```python
class NotFoundError(AppError):    status_code = 404
class PermissionDeniedError(AppError): status_code = 403
```

Where each is used is a deliberate pattern:

| Situation | Error | Status |
| --- | --- | --- |
| Resource doesn't exist | `NotFoundError` | 404 |
| Resource exists, caller not a member of its org | `NotFoundError` | 404 (existence hidden) |
| Caller is a member but lacks role rank | `PermissionDeniedError` | 403 |
| Caller may act but business rule forbids it (bad transition) | `ValidationFailedError` | 422 |

That distinction is worth memorizing; it is the interface between security and
usability (`auth/05-authorization.md`).

## 4. Dependencies composing dependencies

`TaskAccess` needs `CurrentUser` and `DB`; `CurrentUser` needs `Token` and
`DB`. FastAPI resolves the DAG. The same `DB` instance flows everywhere
(caching). You never pass `db` down manually.

Deeper chains exist in production apps (feature flags → user → org → resource).
Design them shallow: every added dependency level is a query on every request.

## 5. Route-level dependencies (`dependencies=[...]`)

FastAPI supports `@router.get(..., dependencies=[Depends(require_superuser)])`
for guards whose return value you don't need. TeamFlow deliberately does not use
this: *every* guard either returns context the handler uses (`TaskAccess`) or is
written as an explicit parameter (`_rl: None = Depends(...)`). Explicit
parameters keep the security surface visible in the signature — a review
property worth the small verbosity.

## 6. Dependency overrides (tests)

`tests/integration/test_attachments.py`:

```python
from app.api.deps import get_storage
from app.main import app

class FakeStorage:
    def __init__(self): self.keys = set()
    def presign_put(self, key, content_type=None): return f"http://fake-storage/{key}"
    async def stat(self, key): return {"size": 1} if key in self.keys else None
    ...

@pytest.fixture
async def fake_storage():
    storage = FakeStorage()
    app.dependency_overrides[get_storage] = lambda: storage
    yield storage
    app.dependency_overrides.pop(get_storage, None)
```

Because routes get storage through `Depends(get_storage)`, the whole S3 path is
replaced with an in-memory fake — no MinIO needed in tests. This is the main
reason TeamFlow wraps MinIO in `StorageClient` at all.

## Django/DRF comparison 🔵

| DRF / Django | FastAPI |
| --- | --- |
| `Mixin` classes with `dispatch()` overriding | composed `Depends` chains |
| `permission_classes = [IsAdmin]` (class-based, no return value) | `Depends(ip_rate_limiter(...))` or `TaskAccess` |
| Custom `Middleware` for per-request state | yield dependency |
| `@override_settings` | `app.dependency_overrides[...]` |
| Factory function returning a view | dependency factory returning a callable |

Django's class-based permissions are equivalent to `dependencies=[...]`.
FastAPI's advantage is that the *result* of authorization is usable data, not
just a boolean gate.

## Production perspective

- A dependency that queries the DB is a query on **every** request to every
  route that declares it. TeamFlow's `TaskAccess` performs two queries
  (task + membership) — acceptable because it saves repeating logic and one of
  those queries replaces a query the handler would otherwise do.
- Failing fast in dependencies means your handler starts with a valid,
  authorized context. Handlers contain ~zero defensive checks — that is why
  they are readable.
- `use_cache` semantics: the same dependency instance with the same params is
  cached; two *different* factories (`ip_rate_limiter("a")` vs
  `ip_rate_limiter("b")`) are distinct callables → both run. Correct here: each
  scope must record its own hit.

## Common mistakes

1. **Swallowing exceptions in yield dependencies** — the session may be left
   with an open transaction. The `async with` in `get_db` is the correct
   pattern: it rolls back.
2. **Using request-scoped dependencies for process-global clients** — you end
   up creating an HTTP client per request (see `infrastructure/08-httpx.md`).
3. **Expecting `dependencies=[...]` return values** — they are discarded.
4. **Overriding dependencies by monkeypatching module attributes.** Overrides
   are the supported seam; monkeypatching bypasses caching and lifecycle.
5. **Building 5-layer dependency chains** "just in case" — each layer costs a
   query and a stack frame in every request.

## Cheat sheet

```python
def guard(scope, max_hits):                     # factory
    async def dep(request: Request, r: RedisDep): ...
    return dep

Access = Annotated[tuple[Thing, Membership], Depends(get_access)]  # returns data

@router.post("", dependencies=[Depends(dep_factory("x", 5))])      # discard return
```

## Review questions

1. Why does `get_db` use `yield` while `get_redis` could have used a plain
   return? Where is Redis actually closed?
2. What does FastAPI do with the return value of a dependency declared in
   `dependencies=[...]`?
3. Compare `TaskAccess` (returns data) with `ip_rate_limiter` (returns nothing).
   When is each style appropriate?
4. Why is `app.dependency_overrides` a better test seam than monkeypatching?
