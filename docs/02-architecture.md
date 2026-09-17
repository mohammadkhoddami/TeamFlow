# 02 — Architecture

## Concept

TeamFlow is a **modular monolith with a layered request path**:

```
Client
   ↓
FastAPI (ASGI)
   ↓
Middleware         request id, idempotency, CORS        app/main.py, app/core/*
   ↓
Router             HTTP shape only                       app/api/routes/*.py
   ↓
Dependencies       auth, tenant context, storage         app/api/deps.py
   ↓
Service            business rules, authorization          app/services/*.py
   ↓
Repository         every SQL query                       app/repositories/*.py
   ↓
SQLModel           table models                          app/models/*.py
   ↓
PostgreSQL
```

Supporting infrastructure (nothing below knows about anything above it):

```
                 ┌── Redis      token store, rate limits, WS pub/sub, cache
FastAPI ─────────┼── Celery     email, webhooks, cleanup, scheduled jobs
                 ├── WebSocket  realtime project events
                 ├── MinIO/S3   attachment bytes
                 └── HTTPX      external webhook receivers
```

## Why this exists

The alternative — putting queries, business rules, and HTTP handling in one
function — works for demos and dies at scale: you cannot test business rules
without HTTP, you cannot audit queries, and authorization gets copy-pasted.
Layering gives each concern exactly one home, which matters even more in
FastAPI than in Django because **FastAPI gives you no enforced structure at
all**. Django has apps/models/views conventions; FastAPI hands you a router and
trusts you. TeamFlow's structure is the discipline FastAPI doesn't impose.

## Mental model: who is allowed to know what

| Layer | Knows about | Must NOT know about |
| --- | --- | --- |
| Router | HTTP, status codes, schemas, dependencies | SQL, business rules |
| Dependency | request context (user, org, session) | business rules |
| Service | business rules, authorization, transactions | HTTP objects (`Request`, `Response`) |
| Repository | SQLModel models, SQL | business rules |
| Model | table shape | everything else |

A quick test you can apply while reviewing: if you deleted FastAPI entirely,
could the service and repository still run? In TeamFlow, yes — services only use
`AsyncSession`, models, schemas and exceptions. That is what makes
`tests/workers/*` possible: Celery tasks call repositories/models without any
HTTP layer.

## TeamFlow implementation per layer

### Routers — `app/api/routes/`

```python
# app/api/routes/tasks.py (excerpt)
@task_router.patch("/{task_id}", response_model=TaskRead)
async def update_task(
    data: TaskUpdate,
    task_access: TaskAccess,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> TaskRead:
    task, org, _m = task_access
    updated = await task_service.update_task(
        db, current_user, org, task, data, ip=_ip(request)
    )
    return _serialize(updated)
```

The router: validates input (`data`), resolves context (`task_access` already
performed the tenant check), delegates, serializes. No business rule appears.

### Dependencies — `app/api/deps.py`

```python
async def get_task_access(task_id, current_user, db) -> tuple[Task, Organization, Membership]:
    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    if not task:
        raise NotFoundError("Task not found")
    membership = await MembershipRepository(db).get_for_user(
        current_user.id, task.organization_id
    )
    if not membership or not membership.is_active:
        raise NotFoundError("Task not found")     # 404, not 403 — no ID probing
    ...
    return task, org, membership
```

This is where **authentication meets tenant isolation**. Every id-addressed
resource in TeamFlow goes through a dependency like this.

### Services — `app/services/`

Business rules, for example the task transition whitelist
(`app/services/tasks.py`):

```python
STATUS_TRANSITIONS: dict[str, set[str]] = {
    TaskStatus.TODO: {TaskStatus.IN_PROGRESS},
    TaskStatus.IN_PROGRESS: {TaskStatus.TODO, TaskStatus.IN_REVIEW},
    TaskStatus.IN_REVIEW: {TaskStatus.IN_PROGRESS, TaskStatus.DONE},
    TaskStatus.DONE: {TaskStatus.IN_PROGRESS},
}
```

Services own the transaction boundary: they call repositories (which only
`flush`) and then `await db.commit()` once, at the end. They emit side effects —
audit rows, notifications, webhook deliveries, WS events — in a deliberate
order (see `database/06-transactions.md`).

### Repositories — `app/repositories/`

Every SQL statement lives here. Example from `app/repositories/task.py`:

```python
class TaskRepository:
    async def list_for_org(self, organization_id, filters, *, offset, limit, sort):
        conds = [Task.organization_id == organization_id, *filters.conditions()]
        statement = select(Task).where(*conds).order_by(parse_sort(sort)) \
            .offset(offset).limit(min(limit, MAX_PAGE_SIZE))
        items = list((await self.db.execute(statement)).scalars().all())
        count_stmt = select(func.count(Task.id)).where(*conds)
        total = (await self.db.execute(count_stmt)).scalar_one()
        return items, total
```

Repositories **never commit** — that is the services' job. This is what allows a
service to compose several repository calls into one atomic operation.

### Models — `app/models/`

SQLModel tables with explicit indexes, FK cascades, and eager-loading
strategies. Details in `database/02-models-fields-and-keys.md`.

## Why a modular monolith (not microservices)

| Dimension | Monolith (chosen) | Microservices |
| --- | --- | --- |
| Transactions | One DB, real ACID (org + membership created atomically) | Sagas/outbox, eventual consistency |
| Deployment | One image, six processes | N images + service discovery |
| Debugging | One log stream, one stack trace | Distributed tracing required |
| Team size fit | 1–10 devs | needs platform maturity |
| Modularity | Enforced by folders/imports | Enforced by process boundaries |

TeamFlow keeps the *modularity* (services/repositories are clean seams) without
paying the distributed-systems tax. If a module ever needed its own deployment
(the classic candidate here would be WebSockets or workers), the seams make the
extraction mechanical.

⚠️ What the monolith costs you: one Python process image must carry every
dependency (MinIO client, Celery, etc.), and one bad synchronous call can affect
every endpoint in that worker. TeamFlow mitigates the second with strict async
discipline (`async/03-blocking-vs-nonblocking.md`).

## Supporting infrastructure boundaries

- **Redis** is never a source of truth. Everything in Redis is reconstructible
  (caches) or intentionally ephemeral (rate limits, token whitelist).
- **Celery** never holds state that only exists in workers. Every job is driven
  by a DB row (`webhook_deliveries`, `idempotency_keys`) so a crashed worker
  loses nothing but time.
- **WebSockets** never receive business state directly from a service in another
  worker — the path is always publish → Redis → listener → sockets.

## Review questions

1. Why can `tests/workers/*` run Celery task functions without FastAPI?
2. A reviewer proposes moving the transition whitelist into the router "because
   it's just validation". What breaks?
3. Why must repositories not commit?
4. Which layer decides that a non-member sees 404 instead of 403?
