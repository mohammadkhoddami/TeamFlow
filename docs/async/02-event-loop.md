# Async 02 — The Event Loop

## Concept

The event loop is a single-threaded scheduler: it runs one task until that task
awaits, then runs another. Blocking code holds the loop; awaiting code yields
it. Everything async in a process shares this one thread of execution.

## Why it matters

"FastAPI is async" only buys concurrency if every request's waiting time is
spent *awaiting*. The loop is a shared resource — one long CPU section or
blocking call starves every other request in that worker process.

```
One uvicorn worker (one process):

loop:  [req A: parse] → await db(A) → [req B: parse] → await redis(B) →
       [req A resumed: serialize] → ...
```

## Where TeamFlow's loop spends time

| Activity | Mode | Loop impact |
| --- | --- | --- |
| JSON validation | CPU, fast | negligible |
| DB queries | awaited (`asyncpg`) | yields |
| Redis ops | awaited | yields |
| MinIO presign | CPU (HMAC), fast | negligible |
| MinIO `stat`/`remove` | threadpool | yields |
| Celery `send_task` | threadpool | yields |
| bcrypt hash/verify | **CPU ~100ms inline** | blocks that long per auth request |
| WebSocket sends | awaited | yields |

Only one entry blocks, deliberately, on rate-limited auth routes. Everything
else either awaits or offloads.

## The loop in each TeamFlow process type

| Process | Loop? | What runs on it |
| --- | --- | --- |
| API worker (uvicorn/gunicorn) | yes | requests, WS listener task, WS connections |
| Celery worker | no | sync tasks (its own thread pool) |
| Celery beat | no | scheduler |
| Tests (pytest-asyncio) | yes, session-scoped | all async fixtures/tests |

That table explains several design choices:

- The websocket listener is an `asyncio.create_task` in the API process
  (lifespan) — it shares the loop with requests, which is fine because it only
  parses JSON and forwards to sockets.
- Workers can't reuse async repositories; they use sync sessions
  (`app/core/db_sync.py`) because there is no loop to run coroutines on.
- Tests must be careful: TestClient runs the app on a **portal loop** in a
  thread, while ASGITransport/tests may run on the pytest-asyncio loop. Sharing
  one engine across loops caused the `NullPool` fix in `app/core/db.py`.

## What the loop is *not*

- **Not multiple threads.** `--workers 2` = two processes, two loops, two
  interpreters. Sharing state (the WS manager) across them requires
  Redis (`infrastructure/06-websocket-scaling.md`).
- **Not a scheduler for periodic work.** Sleeping loops die with the process and
  multiply per worker — Celery Beat owns schedules (`infrastructure/05`).
- **Not a place for long CPU work.** bcrypt is the boundary case, sized and
  rate-limited.

## Diagnosing a blocked loop (reviewer's mental model)

Symptoms:

- latency spikes across *unrelated* endpoints in the same worker;
- `/health/ready` timeouts while simple queries stay fast (ready does a DB
  round trip — if it hangs, the loop or pool is stuck);
- WS events arriving late in bursts.

Causes, in order of likelihood for a codebase like TeamFlow: a sync library
call added to a handler; a `time.sleep`; a huge serialization loop; DB pool
exhaustion (awaited but starving: all connections held by long transactions).

## Multi-worker arithmetic

```
uvicorn --workers N:
  N event loops, N DB engines (pool each), N Redis clients, N WS listeners
total DB connections ≤ N × (db_pool_size + db_max_overflow)
```

TeamFlow defaults: 10 + 10 ⇒ 2 API workers + 1 worker (5+5) ≈ 50 connections.
The loop count is per process — never assume one listener.

## Django/DRF comparison 🔵

| WSGI (Django) | ASGI (FastAPI) |
| --- | --- |
| thread per request (block waits are isolated) | loop per process (block waits starve others) |
| 200 threads ≈ 200 concurrent slow requests | 1 process ≈ thousands of waiting requests, **if** all waits are awaits |
| `sync_to_async` bridges ASGI apps into Django | `run_in_threadpool` for the reverse |
| Gunicorn sync workers | uvicorn/gunicorn+uvicorn workers |

The mental flip: in Django, blocking is *safe but expensive* (threads); in
FastAPI, blocking is *cheap to write but catastrophic* (loop starvation). Code
review must therefore treat any new sync call in a handler as a defect unless
justified.

## Review questions

1. Why does one process with `--workers 1` still serve concurrent requests,
   and what is the one condition?
2. Where does bcrypt run, and what makes that acceptable?
3. Why can't the WS connection registry live in a module global shared "by the
   process"? (Two reasons: workers, loops.)
4. A colleague adds `requests.get(...)` to a webhook trigger "for a quick
   test". What exactly degrades, and how would you detect it?
