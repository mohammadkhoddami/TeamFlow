# Architecture 04 — Services

## Concept

The service layer contains business rules: what is true, what transitions are
legal, who may act, what side effects follow. Services are the only layer that
owns transactions. Routers call them; workers call them; tests call them
directly.

## The service contract

```
input:  AsyncSession, actor (User), context (Organization/Membership), schema(s), ip
output: models, or raises AppError subclasses
side effects: audit rows, notifications, WS events, webhook dispatch, cache invalidation
never: imports fastapi, touches Request/Response, builds SQL
```

Grep checks a reviewer can run:

```bash
grep -rn "from fastapi" app/services/     # must be empty (integrations excepted)
grep -rn "select(" app/services/          # only justified exceptions
grep -rn "await db.commit" app/services/  # expected — this is the layer that commits
```

## What a service function actually does — annotated example

`app/services/tasks.py::create_task` (condensed):

```python
task = Task(organization_id=org.id, project_id=project.id, title=data.title, ...)

if data.assignee_id is not None:                       # rule: assignee ∈ org
    await _assert_assignee_in_org(db, org.id, data.assignee_id)
    task.assignee_id = data.assignee_id

task = await TaskRepository(db).add(task)              # repository: flush only

if data.label_ids:                                     # rule: labels ∈ org
    valid_ids = await _resolve_label_ids(db, org.id, data.label_ids)
    await _set_task_labels(db, task.id, valid_ids)     # link-table writes

watcher_ids = {actor.id} | ({data.assignee_id} if data.assignee_id else set())
await _add_watchers(db, task.id, watcher_ids)          # policy: auto-watch

await audit.log(db, AuditAction.TASK_CREATED, ...)     # audit in same tx

if task.assignee_id and task.assignee_id != actor.id:  # side effect 1: notify
    await audit.log(db, AuditAction.TASK_ASSIGNED, ...)
    await events.notify(db, user_id=task.assignee_id, ...)

await db.commit()                                      # THE transaction boundary

task = await refetch_task(db, task.id)                 # identity-map-safe reload
payload = task_event_payload(task)
await events.publish_project_event(project.id, "task.created", payload)
await events.dispatch_webhooks(db, organization_id=org.id, event="task.created", data=payload)
await cache.invalidate_dashboard(org.id)
return task
```

Read it as a sequence of *decisions* with the mechanics hidden in
repositories/helpers. The ordering (rules → persist → commit → side effects) is
the lesson from `database/06-transactions.md`.

## Service module inventory

| Module | Rules it owns |
| --- | --- |
| `auth.py` | registration uniqueness, login, token rotation/reuse, password reset |
| `organizations.py` | org CRUD rules, rank hierarchy, membership add/change/remove |
| `invitations.py` | invite creation permissions, accept/decline/revoke state machine |
| `projects.py` | manager+ gate for project writes |
| `tasks.py` | transition whitelist, assignee validation, watchers, delete policy |
| `labels.py` | uniqueness per org, manager+ gate |
| `comments.py` | mention parsing, author-or-manager edit policy, notifications |
| `attachments.py` | upload validation (type/size), key generation, confirm/download |
| `notifications.py` | inbox queries, mark-read |
| `webhooks.py` | admin gate, secret generation, CRUD |
| `dashboard.py` | aggregation + cache orchestration |
| `events.py` | notification persistence, WS publishing, webhook dispatch |
| `audit.py` | audit row creation (used *by* other services) |
| `cache.py` | cache get/set/invalidate for dashboard |
| `token_store.py` | Redis refresh/reset token lifecycle |

## Small services are still services

`app/services/labels.py::_require_write` is two lines — but the rule lives in
one place and both `create_label` and `update_label`/`delete_label` share it.
The service layer is not only for complex flows; it is for **every rule that
must not be duplicated**.

## Service-to-service calls

Sometimes one service needs another's rules:

- `app/services/invitations.py` imports `get_organization_for_user` and
  `role_rank` from `organizations.py` → invitation permissions reuse the same
  rank arithmetic.
- `app/services/comments.py` uses `events.notify` for fan-out.
- `app/api/routes/labels.py` (router) calls `tasks.update_task` for
  label attach/detach → the label link change goes through the *task* service's
  validation and event side effects. That is deliberate: link changes are task
  updates.

Import direction stays acyclic: `invitations → organizations`,
`comments → events`, `tasks → events/cache/audit`. `events` imports
repositories, not services.

## Why not put services *inside* models (Django style)?

Django devs often reach for model methods (`task.move_to(status)`) or managers.
In async SQLAlchemy, model methods that query need a session argument anyway
(`async def move_to(self, db, ...)`), at which point you have written a service
with worse discoverability. TeamFlow centralizes rules in `app/services/` so
the product logic reads as one document.

## Django/DRF comparison 🔵

| Django/DRF | TeamFlow |
| --- | --- |
| Model methods / managers | `app/services/*.py` functions |
| Serializer `validate_*` + `create()` | schemas (input only) + services (rules) |
| Signals (`post_save`) | explicit calls in the service (visible order) |
| `transaction.atomic` in a service | `await db.commit()` at the service's end |
| Celery task bodies as "business logic" | workers call the same service/repo functions |

Signals deserve emphasis: TeamFlow's equivalent of `post_save` is an explicit
`await events.notify(...)` line. Explicit beats implicit — you can see the
order, and failures are attributable.

## Production perspective

- **Services are where retries are safe or not**: most are idempotent by
  construction (guarded by state checks); creation flows rely on unique
  constraints or idempotency keys.
- **Services are the natural unit for metrics** (e.g., time `create_task`), not
  routes — a Celery task calling the same service gets the same instrumentation.
- **Rule changes are one-file diffs.** The transition whitelist is one dict;
  the rank matrix is one dict; both are reviewable at a glance.

## Common mistakes

1. **Services returning schemas** — they should return models; the router maps.
   Mixing couples rules to the wire format.
2. **`db.commit()` mid-service** — breaks atomicity (`database/06`).
3. **Rules in helpers called by only one service** *and duplicated elsewhere* —
   if two services share a rule, it belongs in one of them (or a shared module
   like `events`/`audit`).
4. **Catching `AppError` inside services** — let it propagate to the handlers;
   catching loses the HTTP mapping.
5. **Pass-through services** for simple reads — accepted in TeamFlow for
   symmetry (events/audit), but never invent pass-throughs where the router
   already owns a single-purpose query (`list_tasks`).

## Cheat sheet

```python
async def do_thing(db, actor, org, data, ip=None):
    await check_rule_1(db, org.id, data.x)      # raises AppError subclasses
    entity = await Repo(db).add(Model(...))     # flush
    await audit.log(db, AuditAction.X, ...)     # same tx
    await db.commit()                           # boundary
    await events.publish_...()                  # side effects after commit
    return entity
```

## Review questions

1. Why does `create_task` commit *before* publishing the WS event?
2. What are the three categories of side effects it fires, and where is each
   implemented?
3. Where do shared rules live when two services need them (give the actual
   example in `invitations.py`)?
4. Why is `_require_admin` in `webhooks.py` a service concern if it only reads
   `membership.role`?
