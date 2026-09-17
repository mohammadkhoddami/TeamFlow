# Production 04 — ASGI Workers

## Concept

The API runs on an ASGI server. In production TeamFlow uses **gunicorn as the
process manager with uvicorn's ASGI worker class** — gunicorn restarts and
drains processes; uvicorn runs the async loop.

## The command (image CMD)

```bash
gunicorn app.main:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers 2 \
  --bind 0.0.0.0:8000 \
  --timeout 60 \
  --graceful-timeout 30 \
  --access-logfile - \
  --error-logfile -
```

| Flag | Production meaning |
| --- | --- |
| `app.main:app` | the module-level app from `create_app()` |
| `UvicornWorker` | one asyncio loop per worker process |
| `--workers 2` | two processes; restarts isolate crashes |
| `--timeout 60` | a worker stuck >60s is killed and replaced (watch for loops blocked by sync code) |
| `--graceful-timeout 30` | on SIGTERM, finish in-flight requests up to 30s (pairs with compose `stop_grace_period: 40s`) |
| log flags | stdout/stderr; the platform collects them |

Development uses plain `uvicorn --reload` (single process, auto-reload) —
restart semantics and process management aren't needed there.

## What "one worker" contains

```
gunicorn master
├── worker 1 (UvicornWorker)   ← uvicorn loop
│   ├── FastAPI app (lifespan ran once: Redis listener started)
│   ├── SQLAlchemy engine (pool 10+10)
│   ├── Redis client
│   └── ConnectionManager (its own sockets)
└── worker 2 (UvicornWorker)   ← identical, separate memory
```

Consequences that show up in production:

| Resource | Multiplier | Notes |
| --- | --- | --- |
| DB connections | workers × (pool_size + max_overflow) | 2 × 20 = 40 for the API |
| Redis connections | per client (+1 pubsub per listener) | tiny |
| WS listeners | one per worker | by design (`infrastructure/06`) |
| In-memory caches | **none in this codebase** | shared state lives in Redis/DB |

The last row is the architectural payoff: because there is no in-process
business state, adding workers is boring.

## Sync vs async workers (a decision point)

| Option | When |
| --- | --- |
| `UvicornWorker` (chosen) | async I/O dominant — this app (DB/Redis waits) |
| `gthread`/`sync` | CPU-bound endpoints where the thread pool model wins |
| `uvicorn --workers N` directly | acceptable; no gunicorn process manager (less graceful-restart machinery) |

TeamFlow chose gunicorn because deploy-time signal handling (SIGTERM → graceful
drain → lifespan shutdown) is the part uvicorn leaves to you.

## Worker concurrency math for capacity planning

```
API:      2 workers × 20 max conns        = 40
Worker:   4 concurrency × (5 + 5) sync    = 40  (celery --concurrency 4)
Beat:     sync, negligible
Total worst case ≈ 80 connections
```

Postgres default `max_connections = 100`. The prod compose as written is close
to the limit — the lesson is to *always do this arithmetic*, then either add
PgBouncer, raise `max_connections`, or trim pools. Documented here so a reviewer
sees the reasoning, not a magic number.

## Graceful shutdown path

```
SIGTERM → gunicorn master → workers stop accepting
        → in-flight requests finish (≤30s)
        → lifespan teardown: listener.cancel() → redis close → engine.dispose()
        → process exits; compose waits ≤40s
```

Cross-check with `fastapi/10-lifespan.md`: the teardown order there is what
makes the drain clean.

## Django/DRF comparison 🔵

| Django | TeamFlow |
| --- | --- |
| `gunicorn myproject.wsgi --workers N` | `gunicorn app.main:app -k uvicorn.workers.UvicornWorker --workers N` |
| threads per worker (`gthread`) | async loop per worker |
| `--max-requests` recycling (common for leaks) | not configured; lifespan disposal makes leaks less likely, add if needed |
| Channels/daphne for WS | same workers serve WS |

If you know `gunicorn + WSGI`, the only new idea is *what a worker is*: not a
thread serving one request, but an event loop serving many.

## Production perspective

- **Worker count heuristics**: start at ~2× vCPU for CPU-light async apps; tune
  from metrics, not dogma.
- **`--timeout` is not a request SLA** — it is a stuck-worker killer. A worker
  killed mid-request rolls back its transaction and the client retries.
- **Deploys**: rolling restarts + graceful timeouts + stateless workers =
  zero-dropped requests (WebSocket clients reconnect; missed events are the
  documented realtime trade-off).

## Common mistakes

1. **Mixing sync workers with async code** (`gthread` + asyncpg) — coroutine
   warnings and stalls; use the matching worker class.
2. **Forgetting the connection multiplication** when adding workers.
3. **No graceful timeout** — deploys drop in-flight requests.
4. **Running `--reload` in production** — no graceful restarts, memory growth.
5. **Assuming one worker.** Any design with in-process state (TeamFlow's WS
   manager is per-process and intentionally so) must be reasoned about per
   worker.

## Review questions

1. Give the full list of resources that multiply when you raise `--workers`
   from 2 to 4 in TeamFlow.
2. Why does TeamFlow need gunicorn at all, given uvicorn can serve directly?
3. What happens to an in-flight request when a worker hits `--timeout`?
4. Recompute the worst-case Postgres connections if Celery concurrency rises to
   8 — what would you do?
