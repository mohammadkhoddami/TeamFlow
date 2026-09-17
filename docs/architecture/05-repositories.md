# Architecture 05 — Repositories

## Concept

Repositories are the only place SQL is written. Each repository wraps one
aggregate (task, comment, webhook, ...) and exposes intention-revealing methods
(`get_in_org`, `list_for_task`, `pending_older_than`). They never commit, never
apply business rules, and never raise domain errors beyond returning `None`.

## The rules

| Rule | Why |
| --- | --- |
| `flush`, never `commit` | services own transaction boundaries |
| Tenant-scoped reads take `organization_id` | structural IDOR defense |
| No business logic | rule changes must not require touching SQL |
| `None` for missing rows | "not found" is a policy decision for services |
| No schemas, no HTTP, no exceptions | keeps repositories usable everywhere |

## Anatomy — `app/repositories/task.py`

The most interesting repository. Three parts:

### 1. A filter object (typed, shared)

```python
class TaskFilters:
    def __init__(self, *, project_id=None, status=None, priority=None, assignee_id=None,
                 unassigned=None, label_id=None, search=None, due_before=None,
                 due_after=None, overdue=None): ...
    def conditions(self) -> list[ColumnElement[bool]]: ...
```

`conditions()` returns SQLAlchemy boolean expressions. The caller (router) fills
the object from query params; the repository never sees raw HTTP input.

### 2. A sort mapper (whitelist)

```python
SORT_COLUMNS = {"created_at": Task.created_at, "updated_at": Task.updated_at,
                "title": Task.title, "priority": Task.priority,
                "status": Task.status, "due_date": Task.due_date}

def parse_sort(sort: str | None): ...  # '-field' -> col.desc(), unknown -> created_at desc
```

User input selects a *column object from a dict*, never an `ORDER BY` string.

### 3. Methods that do one thing

```python
class TaskRepository:
    async def get(self, task_id) -> Task | None            # by id (deps use select() variant)
    async def get_in_org(self, task_id, organization_id)   # tenant-safe single fetch
    async def list_for_org(self, organization_id, filters, *, offset, limit, sort)
    async def add(task) / update(task) / delete(task)      # flush only
```

## The tenant rule in method signatures

```python
async def get_in_org(self, task_id: uuid.UUID, organization_id: uuid.UUID) -> Task | None:
    statement = select(Task).where(
        Task.id == task_id,
        Task.organization_id == organization_id,
    )
    return (await self.db.execute(statement)).scalar_one_or_none()
```

The name *is* the contract. A reviewer can (and should) grep:

```bash
grep -n "async def get\|async def list" app/repositories/*.py
# every method that can span tenants must take organization_id
```

Methods that intentionally are **not** org-scoped:

| Method | Why safe |
| --- | --- |
| `UserRepository.get_by_email` | users are global identities |
| `AttachmentRepository.pending_older_than` | called only by the cleanup worker across all orgs |
| `IdempotencyRepository.*` | keyed by a globally-unique claim key |
| `NotificationRepository.*` | keyed by `user_id` (the tenant for personal data) |

## The "return None, let services decide" doctrine

```python
async def get_by_name(self, organization_id, name) -> Label | None:
```

The repository cannot know whether a missing label is a 404, a 422, or a
create-if-missing opportunity. That policy lives in services. Keeping
repositories policy-free is what makes them reusable (the same
`pending_older_than` serves the cleanup task and could serve an admin tool).

## Repository inventory and their specialties

| Repository | Specialty |
| --- | --- |
| `user.py` | small; email uniqueness lookup |
| `organization.py` | `list_for_user` returns parallel `(orgs, roles)` via one JOIN |
| `project.py` | `get_in_org` + filtered listing with count |
| `task.py` | the filter/sort machinery |
| `label.py` | per-org uniqueness lookups |
| `comment.py` | per-task chronological listing |
| `attachment.py` | task listing + `pending_older_than` for cleanup |
| `notification.py` | inbox queries + **bulk update** (`mark_all_read` via `update()`) |
| `webhook.py` | CRUD + `active_for_org_and_event` (in-Python event matching) + delivery history |
| `audit.py` | admin listing with filters + `purge_older_than` |
| `invitation.py` | pending-by-email lookups (state machine lives in the service) |
| `idempotency.py` | claim/complete/fail/purge — the idempotency state store |

Two methods deserve a closer look:

```python
# notification.py — bulk update without loading rows
async def mark_all_read(self, user_id: uuid.UUID) -> int:
    from sqlalchemy import update
    statement = (update(Notification)
                 .where(Notification.user_id == user_id, Notification.read_at.is_(None))
                 .values(read_at=datetime.now(UTC)))
    result = await self.db.execute(statement)
    return int(result.rowcount or 0)
```

A `UPDATE ... WHERE` is one statement for N notifications — the alternative
(load all, mutate, flush) is O(N) memory and queries.

```python
# webhook.py — documented in-Python filtering
async def active_for_org_and_event(self, organization_id, event) -> list[Webhook]:
    """Filter in Python: webhook counts per org are tiny; keeps the query
    portable across PG/SQLite without JSON-array dialect gymnastics."""
```

An accepted trade-off with the upgrade path noted in the docstring
(`jsonb @>` containment at scale — `database/09-database-performance.md`).

## Django/DRF comparison 🔵

| Django/DRF | TeamFlow |
| --- | --- |
| `Model.objects.filter(...)` (implicit query) | explicit `select()` inside a repository method |
| Custom `QuerySet` / manager methods | repository methods |
| `get_object_or_404` | `get_in_org` + service raises `NotFoundError` |
| QuerySet laziness | statements execute immediately (awaited) |
| `select_related` chaining | eager strategies on the model |

Django's manager methods are effectively repositories *attached to models*.
TeamFlow detaches them so models stay dumb persistence shapes and every query
lives in one auditable folder.

## Production perspective

- **One file per aggregate** means query changes are localized diffs; a slow
  query is found by endpoint → service → repository.
- **Repositories are the natural place for future query tuning** (index hints,
  `selectinload` tweaks, keyset pagination) without touching rules.
- **Row-locking** (the only `with_for_update()` in the codebase) lives in
  `IdempotencyRepository.complete` — data-access policy in the data layer.
- **Statement count discipline**: list endpoints = page + count + selectin
  collections; any repository method that loops issuing queries is a bug.

## Common mistakes

1. **`commit()` in a repository** — the fastest way to break service-level
   atomicity.
2. **Business rules in SQL** (`WHERE status != 'done'` is fine;
   `WHERE can_transition(...)` is not) — policy creeps into data access and
   becomes untestable.
3. **Returning dicts/tuples instead of models** — loses ORM identity and
   loads strategies.
4. **Forgetting `organization_id` on a new read method.** The naming convention
   (`*_in_org`) plus review checklist is the defense.
5. **`LIKE` built by string concatenation** — use bound parameters
   (`.ilike(f"%{term}%")` binds `term`).

## Cheat sheet

```python
class ThingRepository:
    def __init__(self, db): self.db = db

    async def get_in_org(self, thing_id, organization_id) -> Thing | None: ...
    async def list_for_org(self, organization_id, *, offset, limit) -> tuple[list[Thing], int]: ...
    async def add(self, thing) -> Thing:
        self.db.add(thing); await self.db.flush(); return thing
```

## Review questions

1. Why does `get_in_org` take `organization_id` even though the service already
   checked membership?
2. What are the three parts of `task.py`'s query machinery, and which one is the
   injection defense?
3. Why is `mark_all_read` written as a bulk `UPDATE`?
4. Name two repository methods that are deliberately not org-scoped and justify
   each.
