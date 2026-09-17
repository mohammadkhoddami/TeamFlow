# Mastery 03 — Architecture Cheat Sheet

## The layer contract

```
Middleware  → every request (ids, logs, idempotency)      app/core/
Router      → HTTP shape only                             app/api/routes/
Dependency  → request context + tenant gate (read-only)   app/api/deps.py
Service     → rules, authorization, ONE commit, effects   app/services/
Repository  → SQL only, flush never commit                app/repositories/
Model       → table shape, indexes, load strategies       app/models/
Schema      → wire contract                               app/schemas/
```

## Function template (copy for every new feature)

```python
# 1. schema: app/schemas/thing.py
class ThingCreate(SQLModel):
    name: str = Field(min_length=1, max_length=64)

class ThingRead(SQLModel):
    id: uuid.UUID; name: str; created_at: datetime

# 2. model: app/models/thing.py  (organization_id CASCADE + index, __init__ defaults)

# 3. repository: app/repositories/thing.py
class ThingRepository:
    def __init__(self, db): self.db = db
    async def get_in_org(self, thing_id, org_id) -> Thing | None: ...
    async def list_for_org(self, org_id, *, offset, limit) -> tuple[list[Thing], int]: ...
    async def add(self, thing) -> Thing: self.db.add(thing); await self.db.flush(); return thing

# 4. dependency (only if id-addressed): app/api/deps.py
async def get_thing_access(thing_id, current_user, db) -> tuple[Thing, Organization, Membership]: ...
ThingAccess = Annotated[tuple[Thing, Organization, Membership], Depends(get_thing_access)]

# 5. service: app/services/thing.py
async def create_thing(db, actor, org, membership, data, ip=None) -> Thing:
    _require_manager(membership)                       # rank rule
    thing = await ThingRepository(db).add(Thing(organization_id=org.id, name=data.name))
    await audit.log(db, "thing.created", actor_id=actor.id, organization_id=org.id, ...)
    await db.commit()
    await cache.invalidate_dashboard(org.id)
    return thing

# 6. router: app/api/routes/thing.py
@router.post("", status_code=201, response_model=ThingRead)
async def create_thing(data: ThingCreate, membership: OrgMembership,
                       current_user: CurrentUser, request: Request, db: DB) -> ThingRead:
    org, m = membership
    thing = await thing_service.create_thing(db, current_user, org, m, data, ip=_ip(request))
    return ThingRead.model_validate(thing)

# 7. include in app/api/router.py
api_router.include_router(thing.router)
```

## Tenant isolation (never break these)

```
tenant id  ← server (membership lookup), never the client
deps       → OrgMembership only for /{slug}/ routes (never on id-addressed routes)
repos      → methods that span tenants take organization_id and are named *_in_org
writes     → validate referenced ids belong to the org (assignee, labels)
denials    → 404 for non-members (no existence oracle); 403 for rank
```

## Transactions & side effects

```
service:   validate → repo.add/update (flush) → audit.log → db.commit()
after:     refetch → publish WS → dispatch webhooks → invalidate cache
never:     commit in router/repo; side effects before commit; commit in a loop
```

## Authorization matrix (extend when adding features)

```
read org data      any member        │ create/update task   any member
update org         admin+            │ delete task          manager+ or creator
delete org         owner only        │ labels/projects      manager+
invite             manager+ (admin+ for admin role)
role change        strictly outrank target & granted role
```

## Async hygiene

```
API:      async DB (asyncpg), async Redis; presign inline; stat/remove via threadpool
enqueue:  run_in_threadpool(celery_app.send_task, ...)
workers:  sync sessions (session_scope), never async repositories
never:    requests/sync DB/time.sleep inline; asyncio.run inside the API process
```

## Errors

```
NotFoundError 404   PermissionDeniedError 403   ConflictError 409
UnauthorizedError 401 (+ WWW-Authenticate)      ValidationFailedError 422
RateLimitError 429 (+ Retry-After)              handlers in app/core/exceptions.py
```

## Infra quick keys

```
Redis keys:  teamflow:rt:{u}:{jti} | teamflow:prl:{scope}:{id} | teamflow:cache:dashboard:{org} | teamflow:ws
Celery:      queues default/emails/webhooks | beat: cleanup 6h, warm cache 1h, reminders 24h
Storage:     orgs/{org}/tasks/{task}/{uuid}{ext} | presigned PUT/GET only
Webhooks:    row per delivery → Celery → HMAC v1=sha256(ts.body) → X-TeamFlow-Delivery
WS:          publish → teamflow:ws → per-worker listener → rooms project:{id} | user:{id}
```
