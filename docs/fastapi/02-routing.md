# FastAPI 02 — Routing

## Concept

Routers map `(HTTP method, path)` to Python functions. FastAPI adds typed
extraction of path/query/body and dependency declaration on top. An
`APIRouter` is a group of routes with shared `prefix` and `tags`, included into
the app once.

## Why it exists

Django's `urls.py` maps to views; DRF ViewSets bundle routes into classes.
FastAPI's `APIRouter` is the middle ground: composable route groups, but routes
stay plain functions you can call in tests.

## TeamFlow implementation

Every feature area has a router file; `app/api/router.py` is the single include
point:

```python
api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(organizations.router)
api_router.include_router(organizations.members_router)
api_router.include_router(invitations.router)
api_router.include_router(invitations.org_router)
api_router.include_router(projects.router)
api_router.include_router(projects.project_router)
api_router.include_router(tasks.org_task_router)
api_router.include_router(tasks.project_task_router)
api_router.include_router(tasks.task_router)
...
```

Notice the pattern in `app/api/routes/tasks.py`: **several routers per file**,
each with a different prefix, because the same resource has org-scoped,
project-scoped, and id-addressed URLs:

```python
task_router = APIRouter(prefix="/tasks", tags=["tasks"])
project_task_router = APIRouter(prefix="/projects/{project_id}/tasks", tags=["tasks"])
org_task_router = APIRouter(prefix="/organizations/{slug}/tasks", tags=["tasks"])
```

That yields:

```
GET   /api/v1/organizations/{slug}/tasks      # filtered list for the dashboard
POST  /api/v1/projects/{project_id}/tasks     # create inside a project
GET   /api/v1/tasks/{task_id}                 # id-addressed item
PATCH /api/v1/tasks/{task_id}
POST  /api/v1/tasks/{task_id}/move            # explicit transition
```

## Path vs query vs body — the routing decision table

| Example in TeamFlow | Where the input comes from | Why |
| --- | --- | --- |
| `/tasks/{task_id}` | path | identity of the resource |
| `GET /tasks/{task_id}/comments?offset=0&limit=50` | query | navigation of a collection |
| `GET /organizations/{slug}/tasks?status=todo&search=x&sort=-created_at` | query | filtering/sorting |
| `POST /tasks/{task_id}/move` + `{"status": "done"}` | body | a *state change* with a value, not a resource identity |

A rule of thumb for review: **if it selects which row you mean, it's a path
parameter; if it shapes the response, it's a query parameter; if it's the
payload of a write, it's the body.**

## Decorators you will see

```python
@router.post("", status_code=status.HTTP_201_CREATED, response_model=UserRead,
             summary="Create a new user account")
async def register(...): ...
```

- `@router.<method>` — registers the handler.
- `status_code=` — the default success status (201/204 where appropriate).
- `response_model=` — output filtering + OpenAPI schema (`04-response-models.md`).
- `summary=`/`description=` — OpenAPI documentation (`13-openapi.md`).
- `dependencies=[...]` — route-level dependencies without using a parameter
  (TeamFlow prefers explicit parameters; see `07-advanced-dependencies.md`).
- `@router.websocket(...)` — WebSocket endpoint (`12-websockets.md`).

## Route ordering traps

```python
@router.get("/{task_id}")            # matches anything
@router.get("/{task_id}/watchers")   # more specific
```

FastAPI/Starlette matches routes **in registration order**. A literal segment
must be registered before a parameterized one that could swallow it. TeamFlow's
`/tasks/{task_id}/watchers/me` vs `/tasks/{task_id}` example works because the
segments differ in *count*, not just shape. Watch for cases like
`/notifications/read-all` vs `/notifications/{notification_id}/read` — different
segment counts save us here:

```python
@router.get("/unread-count")               # registered from notifications.py
@router.post("/read-all")
@router.post("/{notification_id}/read")
```

If you ever add `/notifications/{id}` (one segment), register it *after*
`/unread-count` or it will shadow it.

## Django/DRF comparison 🔵

| DRF | FastAPI |
| --- | --- |
| `path("tasks/<uuid:pk>/", view)` | `@router.get("/tasks/{task_id}")` + `task_id: UUID` |
| `DefaultRouter` ViewSet routes (`/tasks/`, `/tasks/{pk}/`) | you write each route; no implicit CRUD |
| `@action(detail=True, methods=["post"]) def move(...)` | `@task_router.post("/{task_id}/move")` |
| `permission_classes` | dependencies (`CurrentUser`, `TaskAccess`) |
| `queryset` + `get_queryset()` filtering | repository methods taking explicit filters |

DRF hides the URL → code mapping behind a router; FastAPI keeps it explicit.
That is more typing, but every route is greppable and reviewable — which is
exactly why TeamFlow's 46 paths are easy to audit for missing tenant checks.

## Production perspective

- Router functions are cheap; put no I/O or state in module scope beyond router
  construction.
- 404 from a *route that doesn't exist* vs 404 from *tenant denial* are
  indistinguishable to attackers — by design (`auth/07-multi-tenancy.md`).
- `operation_id` collisions: FastAPI derives OpenAPI operation ids from
  function names. TeamFlow has unique handler names per file; if you copy-paste
  a handler, rename it or Swagger will merge the operations.

## Common mistakes

1. **Doing the work in the router.** TeamFlow routers are ~10–25 lines: resolve
   deps, call service, serialize. If a router grows business logic, it belongs
   in the service.
2. **Forgetting `response_model`.** Without it, FastAPI serializes whatever you
   return — including fields you forgot to exclude.
3. **Bare `""` vs `"/"` prefixes.** `APIRouter(prefix="/tasks")` + `@router.get("")`
   produces `/tasks` (no trailing slash). Mismatched slashes cause 307 redirects
   that confuse non-browser clients.
4. Expecting DRF-style automatic CRUD from an URL prefix. FastAPI has none;
   every method is declared.

## Cheat sheet

```python
router = APIRouter(prefix="/tasks", tags=["tasks"])

@router.get("/{task_id}", response_model=TaskRead)
async def get_task(task_access: TaskAccess) -> TaskRead: ...

@router.post("", status_code=201, response_model=TaskRead)
async def create_task(data: TaskCreate, ...) -> TaskRead: ...

@router.delete("/{task_id}", status_code=204)
async def delete_task(...) -> None: ...
```

## Review questions

1. Why does one feature area (tasks) have three routers instead of one?
2. Where does `/tasks/{task_id}/move`'s `{"status": "done"}` come from, and why
   not a query parameter?
3. What happens if you register `/notifications/{id}` before `/unread-count`,
   and why can TeamFlow's current routes not hit that bug?
