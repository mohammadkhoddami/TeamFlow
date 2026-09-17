# FastAPI 06 — Dependency Injection

## Concept

`Depends` lets a function declare what it needs; FastAPI builds and caches those
values per request. Dependencies can be functions, classes, or generator
functions (for setup/teardown). They can depend on other dependencies, forming a
graph that FastAPI resolves before calling your route.

## Why it exists

In Django, cross-cutting request concerns are done with middleware (global),
decorators (per-view, opaque), or mixins on class-based views. FastAPI replaces
most of that with **composable, typed, testable functions**. `Depends` is the
single most important FastAPI concept to master, and TeamFlow relies on it for
every cross-cutting concern it has.

## Mental model

```
Depends is a recipe, not a call.
Your signature says "I need a User"; the framework figures out HOW.
```

```
CurrentUser  ─► Token ─► oauth2_scheme ────────────────── reads Authorization header
     │       └─► DB ───► get_db ─────────────────────── yields an AsyncSession
     └─► db.get(User, ...) ──────────────────────────── loads the user row

TaskAccess ─► DB + CurrentUser + task_id (path) ─► task + org + membership
```

FastAPI computes each dependency **once per request** (cached); requesting `DB`
in three places opens one session, not three.

## TeamFlow implementation — `app/api/deps.py`

### 1. The session: generator dependency

```python
# app/core/db.py
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: one session per request, always closed."""
    async with AsyncSessionLocal() as session:
        yield session

# app/api/deps.py
DB = Annotated[AsyncSession, Depends(get_db)]
```

`yield` = setup + teardown in one place. The session is closed after the
response, whether the request succeeded or raised. In Django terms: this is
per-request state without middleware and without thread-local magic.

### 2. Authentication dependency

```python
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
Token = Annotated[str, Depends(oauth2_scheme)]

async def get_current_user(token: Token, db: DB) -> User:
    try:
        payload = security.decode_token(token)
        user_id = uuid.UUID(payload["sub"])
    except (PyJWTError, KeyError, ValueError):
        raise UnauthorizedError("Invalid or expired token") from None

    user = await db.get(User, user_id)
    if not user or not user.is_active:
        raise UnauthorizedError("User not found or deactivated")
    user_id_ctx.set(str(user.id))          # bind user to log context
    return user

CurrentUser = Annotated[User, Depends(get_current_user)]
```

Points to internalize:

- `OAuth2PasswordBearer` both enforces the `Authorization: Bearer` header shape
  *and* feeds Swagger's Authorize button (the `tokenUrl`).
- Failure raises `UnauthorizedError` (an `AppError`) → handled centrally →
  401 JSON, never a stack trace.
- Side effect: binds `user.id` into the logging contextvar. Dependencies can do
  more than fetch — they can establish **request context**.

### 3. Tenant boundary dependency

```python
async def get_org_membership(slug, current_user: CurrentUser, db: DB
) -> tuple[Organization, Membership]:
    org = await OrganizationRepository(db).get_by_slug(slug)
    if not org:
        raise NotFoundError("Organization not found")
    membership = await MembershipRepository(db).get_for_user(current_user.id, org.id)
    if not membership or not membership.is_active:
        raise NotFoundError("Organization not found")   # 404 for non-members
    org_id_ctx.set(str(org.id))
    return org, membership

OrgMembership = Annotated[tuple[Organization, Membership], Depends(get_org_membership)]
```

`get_org_membership` takes `slug: str` — a **path parameter** — proving that
dependencies participate in the same parameter extraction the route does. This
is the trick that makes resource-scoped authorization declarative:

```python
@router.get("/{slug}/members", response_model=list[MembershipRead])
async def list_members(membership: OrgMembership, db: DB): ...
```

The membership check happens before the handler body. You cannot forget it —
if you don't declare the dependency, you don't get `org`.

### 4. Id-addressed resources: `ProjectAccess`, `TaskAccess`, `AttachmentAccess`, `CommentAccess`, `LabelAccess`

Same pattern without a slug: load the row, then check membership in *its* org.

```python
async def get_task_access(task_id, current_user, db) -> tuple[Task, Organization, Membership]:
    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    if not task:
        raise NotFoundError("Task not found")
    membership = await MembershipRepository(db).get_for_user(current_user.id, task.organization_id)
    if not membership or not membership.is_active:
        raise NotFoundError("Task not found")
    ...
    return task, org, membership
```

Note `select(Task)` rather than `db.get(Task, id)`: the explicit SELECT honors
the eager-loading strategies on the mapper (assignee/labels/watchers), which
matters for serialization and avoids lazy-load traps in async sessions
(`database/08-loading-and-n-plus-one.md`).

### 5. Shared infrastructure clients

```python
RedisDep = Annotated[Redis, Depends(get_redis_client)]

def get_storage() -> StorageClient:
    return StorageClient.from_settings()
Storage = Annotated[StorageClient, Depends(get_storage)]
```

`get_storage` is the seam that makes tests easy: `tests/integration/test_attachments.py`
overrides exactly this:

```python
app.dependency_overrides[get_storage] = lambda: storage   # FakeStorage
```

That is `dependency_overrides` — FastAPI's purpose-built test hook, far cleaner
than monkeypatching Django settings.

## Why dependencies instead of middleware or decorators?

| Concern | Middleware | Decorator | Depends (TeamFlow) |
| --- | --- | --- | --- |
| Needs to know about the route (path params, models) | no | fragile | **yes** |
| Return value usable in the handler | no | no | **yes** |
| Testable in isolation | awkward | awkward | **yes** |
| Per-request caching | manual | manual | **yes** |
| Documented in OpenAPI | no | no | **yes** (security schemes) |

TeamFlow uses middleware only for things that are truly request-global and must
wrap everything: request id/access log and idempotency (`08-middleware.md`).
Everything resource-aware is a dependency.

## Annotated style vs default style

TeamFlow uses one consistent style:

```python
DB = Annotated[AsyncSession, Depends(get_db)]

async def route(db: DB, user: CurrentUser): ...
```

Not the older `db: AsyncSession = Depends(get_db)`. The annotated alias is
reusable, readable in signatures, and the direction FastAPI itself recommends.

## Django/DRF comparison 🔵

| Django/DRF | FastAPI |
| --- | --- |
| Middleware (`process_request`) | `Depends` (when route-aware) or middleware (when global) |
| `request.user` via `AuthenticationMiddleware` | `CurrentUser` dependency (explicit, SWR— well, JWT here) |
| DRF `permission_classes` / custom permission | dependency that raises `PermissionDeniedError` |
| `get_queryset()` scoping | repository calls inside services/deps |
| Custom context manager per view | generator dependency with `yield` |
| `@login_required` decorator | `current_user: CurrentUser` parameter |

The philosophical shift: authorization in DRF runs *around* the view via
classes; in FastAPI it runs *inside the parameter list* and its result is data
you can use. TeamFlow exploits that — `TaskAccess` returns the loaded task,
saving the handler a second query.

## Production perspective

- Dependencies run on **every** request that declares them; keep them cheap or
  cacheable. `get_current_user` costs one JWT decode + one `db.get` — fine.
  A dependency that calls an external API must be designed carefully.
- `use_cache=True` is the default; FastAPI caches by (callable, params) per
  request. Two different routes/deps requesting `CurrentUser` share one result.
- Dependency failures are normal flow: they raise `AppError` subclasses, which
  the exception handlers convert (401/403/404) — not 500s.
- Dependency code is executed **outside** your route's try/except; you cannot
  wrap it. Put cleanup in generator dependencies' `finally`/`except`.

## Common mistakes

1. **Checking permissions in the handler body** while also using a dependency
   that loads the resource. Two places to update, one will rot. TeamFlow's
   `TaskAccess` makes the loaded resource and the check inseparable.
2. **Returning a 403 for missing resources.** Non-members get 404 here — 403
   confirms the resource exists (IDOR probing). Services use 403 only when the
   caller *is* a member but lacks rank (e.g., member cannot delete another's
   task).
3. **Doing DB writes in a dependency.** Mutating state before validation of the
   body is a bug factory. TeamFlow's deps are read-only.
4. **Forgetting `Annotated` aliases and repeating `Depends(...)`.** Inconsistent
   signatures; also the alias is where you centralize documentation.
5. **Overriding the wrong reference in tests.** Override where looked up:
   `app.dependency_overrides[get_storage]`, not a re-imported copy.

## Cheat sheet

```python
DB = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
ThingAccess = Annotated[tuple[Thing, Organization, Membership],
                        Depends(get_thing_access)]

@router.get("/{thing_id}")
async def read(access: ThingAccess, db: DB): ...
```

## Review questions

1. Why does `get_org_membership` accept `slug`, and where does that value come
   from at runtime?
2. How many `AsyncSession` objects are created for a request that declares
   `DB`, `CurrentUser`, and `TaskAccess`? Why?
3. Why does `TaskAccess` use `select(Task)` instead of `db.get(Task, id)`?
4. When should a concern be middleware instead of a dependency?
