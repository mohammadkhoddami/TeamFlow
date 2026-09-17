# Architecture 01 — Layered Architecture

## Concept

TeamFlow enforces a one-way dependency between layers:

```
Router → Dependency → Service → Repository → Model → DB
```

Each layer may call the layers to its right; never to its left. This is the
single most important structural rule in the codebase, and it is enforced by
convention + review, not by the framework.

## Mental model: responsibilities as "questions"

| Layer | Answers the question | File pattern |
| --- | --- | --- |
| Middleware | "what wraps every request?" | `app/core/middleware.py`, `idempotency.py` |
| Router | "what is the HTTP shape?" | `app/api/routes/*.py` |
| Dependency | "what context does this request need?" | `app/api/deps.py` |
| Service | "what are the business rules and who may act?" | `app/services/*.py` |
| Repository | "what SQL does this need?" | `app/repositories/*.py` |
| Model | "what is the data shape?" | `app/models/*.py` |
| Schema | "what is the wire contract?" | `app/schemas/*.py` |

A useful test: for any function, ask "what question does it answer?" If a
function answers two questions, it is misplaced.

## The rule in code — one vertical slice

**Router** (`app/api/routes/tasks.py`) — HTTP shape only:

```python
@task_router.patch("/{task_id}", response_model=TaskRead)
async def update_task(
    data: TaskUpdate, task_access: TaskAccess, current_user: CurrentUser,
    request: Request, db: DB,
) -> TaskRead:
    task, org, _m = task_access
    updated = await task_service.update_task(db, current_user, org, task, data, ip=_ip(request))
    return _serialize(updated)
```

10 lines: unpack the dependency, call the service, serialize. No `if`, no SQL,
no role logic.

**Service** (`app/services/tasks.py`) — the rules:

```python
if "status" in changed and data.status and data.status != task.status:
    allowed = STATUS_TRANSITIONS.get(task.status, set())
    if data.status not in allowed:
        raise ValidationFailedError(f"Cannot move task from '{task.status}' to '{data.status}'")
    task.status = data.status
    task.completed_at = datetime.now(UTC) if data.status == TaskStatus.DONE else None
```

**Repository** (`app/repositories/task.py`) — the SQL:

```python
async def update(self, task: Task) -> Task:
    self.db.add(task)
    await self.db.flush()
    return task
```

**Model** (`app/models/task.py`) — the data shape (columns, indexes, load
strategies). **Schema** (`app/schemas/task.py`) — the wire contract.

## Why this matters more in FastAPI than in Django

Django ships conventions (models/views/urls) and DRF adds serializers/viewsets.
FastAPI ships a router and nothing else. Without deliberate layering, the
default FastAPI codebase degenerates into fat route functions that do
validation, SQL, business rules, and authorization in one place — and the
first symptom is always "we can't test anything without HTTP".

TeamFlow's layers exist so that:

- business rules are testable without HTTP (and callable from Celery),
- every SQL statement is in a greppable folder,
- HTTP concerns never appear in services (grep `fastapi` in `app/services/` →
  zero hits),
- tenant isolation has exactly three enforcement points
  (`auth/07-multi-tenancy.md`).

## Where the boundaries are enforced by code

| Boundary | Enforced by |
| --- | --- |
| Services can't touch HTTP | no FastAPI imports in `app/services/` (review + grep) |
| Repositories don't commit | every repo method flushes only; services call `commit` |
| Routers don't SQL | routers never import `select`/repositories (except two documented exceptions) |
| Workers don't need HTTP | Celery tasks import repositories/models only |

Two documented exceptions where routers touch repositories directly:

- `app/api/routes/audit.py` — a single read query, no business rule.
- `app/api/routes/tasks.py` (`list_tasks`) — builds `TaskFilters` and calls
  `TaskRepository.list_for_org`; the query *is* the endpoint.

These are pragmatic, not drift; a reviewer should accept them and reject new
ones without the same justification.

## The dependency direction (never violate)

```
       schemas ───────────► routers ───────────► services ───────────► repositories ───► models
          ▲                    │                     │                      │
          └──── services use schemas for input     └── services use models┘
```

- Services accept **schemas** for input (`TaskCreate`) and **models** for
  entities. They return models. Routers turn models into read-schemas.
- Models never import schemas; repositories never import routers; nothing
  imports `app.main`.

A quick architectural check while reviewing a diff: `git grep "from app.services"
app/api/` should only appear in routers (expected), and `git grep "from fastapi"
app/services/` should be empty.

## Modular monolith boundaries

Modules are folders, not services: `tasks`, `organizations`, `webhooks`, etc.
Cross-module calls happen through services (`comments.py` calls
`app.services.tasks.update_task` for label assignment in `labels.py`; events
fan out through `app.services.events`).

The seams are clean enough to extract a module later (the most realistic
candidates: WebSockets, workers), and tight enough to keep transactions atomic
today. Trade-offs in `architecture/07-design-decisions.md`.

## Django/DRF comparison 🔵

| Django app layout | TeamFlow |
| --- | --- |
| `models.py` | `app/models/*.py` |
| `serializers.py` | `app/schemas/*.py` |
| `views.py` / `viewsets.py` | `app/api/routes/*.py` |
| `services.py` (often absent!) | `app/services/*.py` (always present) |
| custom managers/querysets | `app/repositories/*.py` |
| `permissions.py` | dependencies + services |
| `tasks.py` (Celery) | `app/workers/tasks.py` |

The big difference: Django projects *frequently* skip the service/repository
layers and put ORM calls in views or serializer methods. TeamFlow treats them
as mandatory — because async sessions and authorization centralization make the
"fat view" pattern much more expensive than it is in DRF.

## Production perspective

- **Layering pays off at scale of change**, not scale of traffic: refactors are
  localized (swap how a query works without touching rules), and rules are
  localized (change a transition without touching HTTP).
- **Layering has a cost**: more files, more indirection, occasional pass-through
  functions. The team's discipline is to keep pass-throughs honest — if a
  service function is only a repository call, it is a sign the rule layer has
  nothing to add; TeamFlow keeps some anyway for event/audit symmetry.
- **Onboarding**: a new dev can read `app/services/` top-to-bottom and know the
  product. That is the layer's second job.

## Common mistakes

1. **Business rules in routers** because "it's just one if". Next sprint it is
   five ifs and untestable.
2. **SQL in services.** The moment a service imports `select`, repository
   discipline is gone.
3. **Repositories calling services** (inverting the arrow) — creates cycles and
   hides side effects inside data access.
4. **Schemas as DB models** (or vice versa) — leaks columns and couples wire
   format to schema (see `database/01-sqlmodel.md`).
5. **HTTPExceptions in services** — drags FastAPI into the rule layer and
   breaks worker reuse.

## Cheat sheet

```
router     → parse, call service, serialize        (no SQL, no rules)
dependency → context + tenant gate                 (read-only)
service    → rules, authorization, commit          (no HTTP)
repository → SQL, flush only                       (no commit, no rules)
model      → shape, indexes, load strategy
schema     → wire contract
```

## Review questions

1. A new endpoint needs a special rule ("only the assignee can reopen a task").
   Which layer and why?
2. Why is "repositories only flush" a layering rule *and* a transaction rule?
3. Which two router files bypass services, and what justifies them?
4. What is the fastest grep to prove services have no HTTP dependency?
