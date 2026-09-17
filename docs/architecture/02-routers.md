# Architecture 02 — Routers

## Concept

A router is an `APIRouter` collection of route handlers. In TeamFlow's layered
architecture the router owns **exactly four responsibilities**:

1. declare the HTTP contract (method, path, status, response model),
2. extract request data (path/query/body/headers),
3. resolve dependencies (auth, tenant context, storage),
4. delegate to a service and serialize the result.

Nothing else. This lesson compares the theory with the actual code so you can
review routers mechanically.

## The mandatory shape

Every TeamFlow handler follows this skeleton:

```python
@<router>.<method>("<path>", status_code=..., response_model=...)
async def <name>(
    <body schema(s)>,
    <access dependency>: <AccessType>,
    current_user: CurrentUser,        # when the actor matters
    request: Request,                 # only when ip/besides is needed
    db: DB,
) -> <Read schema>:
    <unpack dependency>               # e.g. task, org, _m = task_access
    <call service>                    # e.g. await task_service.update_task(...)
    <serialize>                       # e.g. return _serialize(updated)
```

Count the lines of logic in any handler: if it exceeds ~15, something belongs
in a service.

## Real examples, graded by complexity

### Simplest — a delegation with a dependency (`organizations.py`)

```python
@router.get("/{slug}", response_model=OrganizationRead)
async def get_organization(membership: OrgMembership, current_user: CurrentUser) -> OrganizationRead:
    org, my_membership = membership
    return OrganizationRead.model_validate(org).model_copy(
        update={"my_role": my_membership.role}
    )
```

No DB call in the handler at all — the dependency already loaded both rows.
The `model_copy` attaches the caller's role (a view-model detail — HTTP-layer
concern, correctly placed).

### Collection + delegation (`projects.py`)

```python
@router.get("", response_model=list[ProjectRead])
async def list_projects(
    membership: OrgMembership, db: DB,
    status_filter: str | None = Query(default=None, alias="status"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[ProjectRead]:
    org, _m = membership
    projects, _total = await services.projects.list_projects(
        db, org.id, status=status_filter, offset=offset, limit=limit
    )
    return [ProjectRead.model_validate(p) for p in projects]
```

Note `alias="status"` — the Python parameter is renamed to avoid shadowing
`fastapi.status`, but the public query param stays `?status=`. Small detail,
common review miss.

### The one exception — query building in the router (`tasks.py`)

```python
@org_task_router.get("", response_model=Page[TaskRead])
async def list_tasks(membership, db, current_user, project_id=None, ..., sort=None,
                     offset=0, limit=DEFAULT_PAGE_SIZE) -> Page[TaskRead]:
    org, _m = membership
    filters = TaskFilters(project_id=project_id, status=status, priority=priority,
                          assignee_id=assignee_id, unassigned=unassigned,
                          label_id=label_id, search=search, due_before=due_before,
                          due_after=due_after, overdue=overdue)
    items, total = await TaskRepository(db).list_for_org(
        org.id, filters, offset=offset, limit=limit, sort=sort
    )
    return Page[TaskRead](items=[_serialize(t) for t in items], total=total,
                          offset=offset, limit=limit)
```

This is the documented exception: the endpoint's *entire* logic is a filtered
query; wrapping it in a service would be a pass-through. The `TaskFilters`
object keeps the SQL parameterized and the repository keeps the SQL itself.

### Serialization helper

```python
def _serialize(task) -> TaskRead:
    read = TaskRead.model_validate(task)
    read.watcher_ids = [w.id for w in task.watchers]
    return read
```

Routers own mapping from model → response schema. This helper is the only
"transform" allowed in the router layer, and it depends on eager loading
(`database/08-loading-and-n-plus-one.md`).

### The `ip` pattern

```python
def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None
```

Each router file defines `_ip` and passes `ip=_ip(request)` to services that
audit. `Request` appears in signatures only for this.

## Router inventory (14 files)

| File | Prefix(es) | Notable |
| --- | --- | --- |
| `health.py` | `/health` | no auth |
| `auth.py` | `/auth` | rate-limit dependencies, OAuth2 form login |
| `organizations.py` | `/organizations` + `/organizations/{slug}/members` | two routers, one file |
| `invitations.py` | `/invitations` + `/organizations/{slug}/invitations` | invitee + admin surfaces |
| `projects.py` | `/organizations/{slug}/projects` + `/projects` | create (slug-scoped) + item routes (id) |
| `tasks.py` | `/organizations/{slug}/tasks` + `/projects/{project_id}/tasks` + `/tasks` | the richest filters |
| `labels.py` | org labels + `/labels` + task label links | 3 routers |
| `comments.py` | `/tasks/{task_id}/comments` + `/comments` | |
| `attachments.py` | `/tasks/{task_id}/attachments` + `/attachments` | presigned URL grants |
| `notifications.py` | `/notifications` | own inbox only |
| `webhooks.py` | `/organizations/{slug}/webhooks` | secret returned once |
| `audit.py` | `/organizations/{slug}/audit-logs` | admin check inline |
| `dashboard.py` | `/organizations/{slug}/dashboard` | cache toggle query param |
| websocket router (`app/websocket/router.py`) | `/ws/projects/{id}` | not an APIRouter route method |

## Django/DRF comparison 🔵

| DRF | TeamFlow router |
| --- | --- |
| `APIView.get()` | route function |
| `ViewSet` + `DefaultRouter` (implicit URLs) | explicit `@router.<method>` per path |
| `@action(detail=True)` | separate route (`/tasks/{id}/move`) |
| `get_serializer_class()` | `response_model=` + typed schemas |
| `permission_classes` | dependencies declared in the signature |
| `pagination_class` | `Page[T]` envelope + offset/limit params |

DRF's implicit routing makes it easy to lose track of which URLs exist; the
TeamFlow style means `/docs` and `grep "@router"` are always complete and
accurate inventories.

## Production perspective

- **Handler signatures are the API contract**; changing parameter names changes
  query params unless you use `alias`.
- **Router-level dependency resolution is where failures happen fast** (401/404
  before any business work) — keep expensive work in dependencies minimal
  (`auth/05`).
- **Status codes are part of the contract** (201 vs 200 vs 204) — choose
  deliberately per route, not uniformly.

## Common mistakes

1. **Fat handlers**: DB queries, rule checks, and loops of side effects. Move
   to services.
2. **Serializing table models directly** — leaks fields (`fastapi/04`).
3. **`db.commit()` in a handler** — transactions belong to services. If you see
   a commit in `app/api/routes/`, it is a bug.
4. **Forgetting the response model** while building a new route by copy-paste.
5. **Importing services as `from app.services.tasks import update_task`** in
   some files and `services.tasks.update_task` in others — TeamFlow stays
   consistent with `from app import services` + `services.tasks.x` so the
   module path is always visible in the call.

## Cheat sheet

```python
@router.post("", status_code=201, response_model=ThingRead)
async def create_thing(data: ThingCreate, access: ThingAccess,
                       current_user: CurrentUser, request: Request, db: DB) -> ThingRead:
    thing, org, _m = access
    created = await thing_service.create_thing(db, current_user, org, data, ip=_ip(request))
    return ThingRead.model_validate(created)
```

## Review questions

1. Justify the `list_tasks` router bypassing the service layer. What property
   keeps it safe?
2. Why does `list_projects` rename `status` to `status_filter` with `alias`?
3. Where would you put "when a task is created, also create a default comment"? 
4. What is the tell-tale sign that a handler should be split into a service?
