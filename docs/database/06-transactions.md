# Database 06 — Transactions

## Concept

A transaction is an atomic unit of work: either all statements commit or none
do. In SQLModel/SQLAlchemy async, a transaction begins implicitly on first use of
a session and ends at `await session.commit()` (or rollback on close).

## Why it exists

Real operations span multiple tables. Creating an organization also creates the
owner's membership; updating a task also writes an audit row. If the process
dies between the two, you get orphaned data and a trail that lies.

## TeamFlow's transaction rules

1. **The session is per request** (from the `get_db` dependency).
2. **Repositories `flush`; services `commit`; nothing else commits.**
3. **One unit of work per service function** — the commit is the last statement
   before side effects.
4. **Side effects that cross process boundaries happen *after* commit**
   (WS publish, webhook enqueue, cache invalidation).
5. **Idempotency rows are the exception** — the middleware commits the claim
   *before* the handler runs, by design.

## Rule 2 in practice — the repository contract

Every repository method flushes and returns:

```python
# app/repositories/user.py
async def add(self, user: User) -> User:
    """Persists without committing: the service owns the transaction."""
    self.db.add(user)
    await self.db.flush()
    return user
```

`flush` emits the INSERT so the row has an id and constraints are checked — but
the data is not durable and can still be rolled back. This makes composition
possible.

## Rule 3 in practice — atomic multi-table writes

`app/services/organizations.py`:

```python
async def create_organization(db, owner, data, ip=None) -> Organization:
    org_repo = OrganizationRepository(db)
    if await org_repo.get_by_slug(data.slug):
        raise ConflictError("An organization with this slug already exists")

    org = Organization(name=data.name, slug=data.slug, created_by_id=owner.id)
    org = await org_repo.add(org)                       # flush: org.id available

    await MembershipRepository(db).add(                 # second INSERT, same tx
        Membership(user_id=owner.id, organization_id=org.id, role=MembershipRole.OWNER)
    )
    await audit.log(db, AuditAction.ORG_CREATED, actor_id=owner.id,
                    organization_id=org.id, target_type="organization",
                    target_id=org.id, ip=ip)             # third INSERT, same tx

    await db.commit()                                    # one durability point
    await db.refresh(org)
    return org
```

If anything raises after the org INSERT, the session closes without commit and
the transaction rolls back — no org without an owner, no audit entry for an
org that doesn't exist.

The audit helper is deliberately session-scoped, not session-owning:

```python
# app/services/audit.py
async def log(db: AsyncSession, action: str, *, ...) -> AuditLog:
    record = AuditLog(...)
    return await AuditLogRepository(db).add(record)   # flush only
```

## Rule 4 in practice — order of side effects

`app/services/tasks.py` (`update_task` tail):

```python
await db.commit()

task = await refetch_task(db, task.id)
payload = task_event_payload(task)
event_type = "task.completed" if ... else "task.updated"
await events.publish_project_event(task.project_id, "task.updated", payload)
await events.dispatch_webhooks(db, organization_id=org.id, event=event_type, data=payload)
await cache.invalidate_dashboard(org.id)
```

Why this exact order:

- commit first → consumers can never see an event for data that later vanishes;
- `refetch` after commit → the payload reflects the committed state with
  relationships loaded (`database/03-relationships.md`);
- WS publish before webhooks → realtime is cheap and immediate; webhook
  enqueueing is a broker round trip;
- cache invalidation last → even if it fails, the TTL bounds staleness
  (`infrastructure/02-caching.md`).

And inside `dispatch_webhooks`, a **second commit boundary** exists because the
delivery rows must be durable *before* the broker sees them:

```python
for webhook in matching:
    delivery = await delivery_repo.add(WebhookDelivery(...))   # flush
    delivery.payload["id"] = str(delivery.id)
    pending.append(delivery)

await db.commit()                                              # durable

for delivery in pending:
    try:
        await run_in_threadpool(celery_app.send_task, "teamflow.deliver_webhook", [str(delivery.id)])
    except Exception:
        logger.exception("Failed to enqueue webhook delivery %s", delivery.id)
```

This is the async equivalent of Django's `transaction.on_commit` pattern, with
an extra property: a broker outage does not lose the event (the cleanup task
re-enqueues stale `pending` rows — `infrastructure/04-celery.md`).

## Rule 5 in practice — the idempotency claim

`app/core/idempotency.py` claims *before* the handler runs:

```python
async def _claim(self, key, path, method, identity, request_hash):
    try:
        async with AsyncSessionLocal() as db:
            record = IdempotencyKey(key=key, user_id=..., method=method,
                                    path=path, request_hash=request_hash)
            db.add(record)
            await db.commit()                 # claimed and durable NOW
            return _Claim(action="proceed")
    except IntegrityError:
        return await self._handle_conflict(key, request_hash)
```

Why commit immediately:

- the claim must be visible to a *concurrent duplicate request* (possibly on
  another worker) — an uncommitted row is invisible, and the two requests would
  both proceed;
- if the handler then fails with a 5xx, the middleware calls `_mark_failed`, so
  the claim's `failed` status is also durable.

The claim is intentionally **not** part of the business transaction: it must
survive the business transaction's rollback (a 500 that rolls back the domain
work still needs its idempotency record marked failed so a retry can proceed).

## Failure matrix (worth memorizing)

| Failure point | Transaction state | Client sees | Recovery |
| --- | --- | --- | --- |
| Validation (422) | transaction never started | 422 | fix input |
| Service rule (422/403/404) | open tx rolls back on session close | error | retry after fix |
| DB error mid-composition | rollback | 500 (logged) | idempotent retry ok if key used |
| Crash after `commit()`, before side effects | committed | 200 eventually? | WS/webhooks lost for that event (no outbox) |
| Broker down during webhook enqueue | committed + deliveries pending | 200 | cleanup task re-enqueues |
| Handler 5xx with idempotency key | claim marked `failed` | 500 | same key may be retried |

⚠️ The "crash between commit and side effects" row is the honest gap of any
non-outbox design. A transactional outbox (write events to a table in the same
transaction, publish from a relay) closes it. TeamFlow's webhook rows *are* a
partial outbox; WS events are fire-and-forget by nature. See
`architecture/07-design-decisions.md`.

## Django/DRF comparison 🔵

| Django | TeamFlow |
| --- | --- |
| `ATOMIC_REQUESTS=True` (whole request in one tx) | explicit service-level commits |
| `with transaction.atomic():` | the service function *is* the atomic block |
| `transaction.on_commit(callback)` | commit first, then side effects (or `dispatch_webhooks`' two-phase) |
| `select_for_update()` | `with_for_update()` in `IdempotencyRepository.complete` |

`ATOMIC_REQUESTS` is the big difference: Django can wrap the entire request
automatically. TeamFlow cannot — commits happen at deliberate points because
side effects and idempotency claims require *leaving* the transaction. This is
the clearest example of why "services own transactions" is not just layering
dogma in async FastAPI.

## Common mistakes

1. **Committing inside a loop** (`for webhook: repo.add(); commit()`) — partial
   state on failure and N round trips.
2. **Publishing to Redis/Celery before commit** — consumers act on phantom
   data.
3. **Making the idempotency claim part of the business transaction** — the
   claim then disappears on rollback, and concurrent duplicates race.
4. **Opening a second session "to avoid transaction issues"** — two sessions
   mean two transactions; atomicity is gone. TeamFlow has exactly one session
   per request plus explicit short-lived sessions in middleware/workers.
5. **Forgetting that a session closure rolls back**: an uncommitted change
   silently disappears rather than erroring.

## Cheat sheet

```python
async with AsyncSessionLocal() as db:           # one unit of work
    repo.add(x)                                  # flush
    audit.log(db, ...)                           # flush
    await db.commit()                            # durability
# then: publish events, enqueue jobs, invalidate caches
```

## Review questions

1. Why does `create_organization` flush before creating the membership?
2. What exactly is committed before `celery_app.send_task` is called in
   `dispatch_webhooks`, and what failure does that ordering survive?
3. Why must the idempotency claim's commit be separate from the handler's
   transaction?
4. Where is the one place in TeamFlow where a crash between commit and side
   effects loses an event, and what pattern would fix it?
