# Architecture 06 — Transactions (as an architectural concern)

> Mechanics live in `database/06-transactions.md`. This lesson is the
> architectural view: *who is allowed to decide transaction boundaries, and why
> that decision cannot live in routers or repositories.*

## Concept

A transaction boundary is a **business decision**: "these facts become true
together". That sentence is a rule, and rules live in services. Therefore:
**only services commit.**

## The three-layer contract

| Layer | May it open a transaction? | May it commit? |
| --- | --- | --- |
| Router | no (session arrives open; it must not care) | no |
| Dependency (`get_db`) | owns the *session lifetime* | no (closes; uncommitted work rolls back) |
| Service | implicitly, via the session | **yes — exactly once per unit of work** |
| Repository | no (uses the service's session) | no (flush only) |
| Middleware | opens its **own** sessions for the idempotency claim | yes, deliberately separate |
| Worker task | opens its own sync session (`session_scope`) | yes, per task |

## Why routers can't commit

Consider the alternative: router does `db.commit()`. Then:

- A service that performs two writes cannot be atomic — the router's commit
  covers an unknown amount of work.
- Reusing the service from invitation acceptance or a Celery task (no HTTP)
  loses the commit entirely — silent data loss.
- Audit rows written by the service might land in a *different* transaction
  than the change, producing a lying trail.

TeamFlow's tests exercise services through HTTP *and* workers call them through
sessions — the service-owned boundary is what makes both paths correct.

## Why dependencies don't commit

`get_db` is a yield dependency:

```python
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
```

Its contract: provide a session, close it after the response. On close
(no commit), the transaction rolls back — a deliberate safety net. If a handler
raises *after* a service committed once, the earlier commit stands (expected:
the service completed its unit of work). There is no magic request-wide
transaction, unlike Django's `ATOMIC_REQUESTS=True`, and that is a conscious
choice: side effects (WS, Celery, Redis) must happen *after* commit, which an
outer request transaction would make impossible to time correctly.

## The deliberate exception: middleware owns its own transaction

`app/core/idempotency.py`:

```python
async def _claim(self, key, path, method, identity, request_hash):
    try:
        async with AsyncSessionLocal() as db:          # its own short-lived session
            db.add(IdempotencyKey(...))
            await db.commit()                           # durable claim BEFORE the route runs
            return _Claim(action="proceed")
    except IntegrityError:
        return await self._handle_conflict(key, request_hash)
```

An architectural rule earns exceptions only with a stated reason: the claim
must be visible to concurrent duplicates on other workers *before* the handler
runs, and it must survive the handler's rollback. Both properties force a
separate transaction.

## Cross-process transactions do not exist

The webhook flow spans "commit domain change → enqueue Celery task". There is
no transaction across Postgres and Redis. TeamFlow's design acknowledges this
with compensating actions instead of pretending atomicity:

```
1. commit business change          (Postgres)
2. commit delivery rows            (Postgres — durable intent)
3. enqueue Celery task             (Redis, best-effort)
4. cleanup task re-enqueues stale pending deliveries every 6h
```

Step 4 is the compensating action. Without it, step 3 failures would silently
drop webhooks; with it, the system converges. (Formalizing this pattern is the
transactional outbox — see `architecture/07-design-decisions.md`.)

## Reading a service as a transaction plan

When reviewing a new service function, annotate it:

```python
async def create_X(...):
    ...validations...           # no writes yet
    x = await repo.add(x)       # INSERT (flush)
    ...more writes (links, audit, notifications)...
    await db.commit()           # ← the ONE boundary
    ...side effects (events, jobs, cache)...
```

Red flags in review:

- two `commit()` calls in one function without a documented reason;
- a commit *inside a loop*;
- side effects before the commit;
- a repository that commits;
- a route with a commit.

## Django/DRF comparison 🔵

| Django | TeamFlow |
| --- | --- |
| `ATOMIC_REQUESTS=True` (request-wide tx) | no — service-scoped commits |
| `with transaction.atomic():` in a service | the service function is the atomic block |
| `transaction.on_commit(...)` | "commit first, then side effects" ordering |
| Database + Celery dual-write problems | same; mitigated by durable rows + sweeper |
| `select_for_update` | only in `IdempotencyRepository.complete` |

The key architectural difference: Django encourages *deferred* side effects via
`on_commit`; async FastAPI has no request-scoped transaction to hook, so
TeamFlow encodes the same ordering explicitly. The result reads more
imperatively but is identical in effect.

## Production perspective

- **Long transactions are the enemy**: service boundaries are small (a handful
  of statements), so row locks are held for milliseconds — important for the
  `UPDATE`s inside `mark_all_read` and idempotency completion.
- **Failed commits surface as 500s** (the `SQLAlchemyError` handler) with the
  request id logged; the session closes and rolls back on the way out.
- **Crash between step 1 and step 2** (webhook flow) is the residual gap —
  documented, with the outbox as the formal fix.

## Common mistakes

1. **`ATOMIC_REQUESTS` habits**: assuming the whole request is atomic. It is
   not; each service call is its own unit of work.
2. **Committing "just to be safe" in a repository** — destroys composition.
3. **Sending WS events inside the transaction**: clients could act on data that
   rolls back.
4. **Holding a session open across an external call** (SMTP, HTTP) — locks held
   during network latency. TeamFlow's external calls happen after commit and in
   workers.
5. **Using two sessions "for safety"** — two transactions, no atomicity.

## Cheat sheet

```
session:  get_db (request) | AsyncSessionLocal (middleware/worker)
commit:   service, once | worker task, once | idempotency claim, deliberately separate
flush:    repositories only
never:    commit in routers/repositories; side effects before commit
```

## Review questions

1. Why is a request-scoped transaction (Django `ATOMIC_REQUESTS` style) a bad
   fit for TeamFlow's side effects?
2. Justify the middleware's separate transaction using two concrete failure
   scenarios.
3. Trace the webhook dual-write and name the compensating action for each
   failure point.
4. A service needs to call an external HTTP API between two writes. Where do
   you put it, and what do you accept as a consequence?
