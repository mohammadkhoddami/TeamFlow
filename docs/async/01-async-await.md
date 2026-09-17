# Async 01 — async/await

## Concept

`async def` defines a coroutine. `await` suspends the current coroutine at an
I/O point and hands control back to the event loop, which can run other tasks.
Async does **not** mean "runs in parallel"; it means "doesn't waste a thread
while waiting".

```python
async def handler():
    user = await db.get(User, uid)        # suspend here; loop runs other requests
    return user
```

## Why it exists

WSGI servers (Django) dedicate a thread to each request. A request waiting
300ms on Postgres occupies a thread; 200 concurrent slow requests exhaust a
thread pool. Async servers multiplex thousands of waiting requests onto one
thread by suspending at awaits.

## The rules that matter (the rest is syntax)

1. **You can only `await` inside `async def`.** No exceptions.
2. **An `async def` that never awaits runs synchronously** — it just looks
   async. It blocks the loop while executing.
3. **A blocking call inside `async def` blocks *every* request** on that worker.
   This is the cardinal sin (`async/03-blocking-vs-nonblocking.md`).
4. **Concurrency needs explicit scheduling** — `await` is sequential waiting;
   `asyncio.gather`/`create_task` runs things concurrently.
5. **Libraries must match the mode**: async DB driver (`asyncpg`), async Redis,
   async HTTP (`httpx.AsyncClient`). Sync libraries (`psycopg`, `minio`,
   `celery` producers) need threadpool offloading.

## TeamFlow's async surface

| Component | Mode | Where |
| --- | --- | --- |
| HTTP handlers | async | `app/api/routes/*.py` |
| DB engine/sessions | async (`asyncpg`) | `app/core/db.py` |
| Redis client | async | `app/core/redis.py` |
| MinIO SDK | **sync**, used two ways | presign = pure CPU inline; `stat`/`remove` = `run_in_threadpool` (`app/services/integrations/storage.py`) |
| Celery producer (`send_task`) | **sync**, wrapped | `run_in_threadpool` in `app/services/events.py`, `invitations.py`, `auth.py` |
| Celery workers | sync by design | `app/workers/tasks.py` + `app/core/db_sync.py` |
| Password hashing (bcrypt) | sync CPU, inline, accepted | `app/services/auth.py` |
| WebSocket endpoint | async | `app/websocket/router.py` |
| WS Redis listener | async background task | `run_redis_listener` |

## Worked example: the same handler in both worlds

```python
# async — releases the loop during the DB wait
user = await UserRepository(db).get_by_email(email)
```

The sync equivalent inside an async handler would be:

```python
user = repo.get_by_email_sync(email)   # ❌ blocks every request on this worker
```

TeamFlow never does the second. When it must call sync code, it offloads:

```python
# app/services/events.py
await run_in_threadpool(celery_app.send_task, "teamflow.deliver_webhook", [str(delivery.id)])
```

`run_in_threadpool` runs the blocking call on a worker thread and resumes the
coroutine when done — the event loop stays free.

## `asyncio.gather` in TeamFlow

`app/services/events.py` publishes and notifies sequentially (a few ms each);
the parallel pattern exists in the WS listener only indirectly. Where TeamFlow
*does* need concurrency it uses task creation, e.g. the lifespan:

```python
listener = asyncio.create_task(run_redis_listener(stop), name="ws-redis-listener")
```

A long-running background coroutine, cancelled at shutdown — the canonical
`create_task` use.

## Django/DRF comparison 🔵

| Django | FastAPI |
| --- | --- |
| `def view()` runs in a thread (WSGI) | `async def` runs on the loop; sync `def` runs in a threadpool automatically |
| Django 4 `async def` views (ASGI) | native, ecosystem-wide async |
| `async_to_sync` / `sync_to_async` bridges | `run_in_threadpool` for sync calls |
| ORM is sync (thread-sensitive) | async engine end-to-end (`asyncpg`) |
| Celery tasks sync (same) | Celery tasks sync (same) |

Django hides sync/async mixing behind `sync_to_async`; FastAPI makes you choose
explicitly. The payoff: no thread-per-request ceiling; the cost: you must know
which of your dependencies are blocking.

## Production perspective

- One blocked event loop stalls *all* requests on that worker — latency spikes
  are the symptom, and they are hard to attribute without tracing.
- Offloading to threadpools moves the ceiling from "loop blocked" to "thread
  pool exhausted" — still a ceiling; size it deliberately.
- `bcrypt` (~100ms) is the one accepted inline block: auth endpoints are rate
  limited and login is infrequent per user (`auth/02`).

## Common mistakes

1. Calling a sync library (requests, psycopg, time.sleep) inside a handler.
2. `await` on a non-awaitable or forgetting `await` on a coroutine (silent
   "coroutine was never awaited" warnings, or `'coroutine' object has no
   attribute`).
3. Assuming `async def` runs concurrently with itself across requests —
   concurrency happens *at awaits*, not inside CPU sections.
4. Using `asyncio.run()` inside a running loop — e.g. in services; workers use
   it safely because no loop runs there (`app/workers/tasks.py` email SMTP
   path).
5. Sharing one session/client across tasks concurrently — asyncpg sessions are
   not task-safe; one per request is the rule.

## Cheat sheet

```
await          → suspend point (I/O)
run_in_threadpool(fn, ...) → run blocking code off the loop
asyncio.create_task(coro)  → fire-and-hold background coroutine
never: time.sleep, sync DB/HTTP, blocking SDK calls inline
```

## Review questions

1. Why does an `async def` handler that calls `time.sleep(1)` delay other
   requests, while `await asyncio.sleep(1)` does not?
2. Where does TeamFlow use `run_in_threadpool` and why in each case?
3. Why are Celery worker tasks sync, and what does that imply about reusing
   repositories there?
4. Which inline blocking call does TeamFlow accept, and under what
   justification?
