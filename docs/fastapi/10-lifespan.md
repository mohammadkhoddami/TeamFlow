# FastAPI 10 — Lifespan (Startup/Shutdown)

## Concept

`lifespan` is an async context manager passed to `FastAPI(...)`. Code before
`yield` runs once when the server process starts; code after `yield` runs on
graceful shutdown. It replaces the deprecated `@app.on_event("startup")` /
`"shutdown"` pair.

## Why it exists

Long-lived resources must be created **once per process**, not per request or
per import:

- DB engine / connection pool
- Redis client
- background tasks owned by the process (TeamFlow's WS Redis listener)
- dev-time bootstrap (ensure S3 bucket)

Doing this at import time breaks tools that import the module (Alembic, tests,
`celery` autodiscovery) and cannot be cleaned up. Lifespan has a clear owner and
a clear teardown.

## TeamFlow implementation

`app/main.py`:

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    stop = asyncio.Event()
    listener = asyncio.create_task(run_redis_listener(stop), name="ws-redis-listener")

    if settings.environment != "testing":
        await StorageClient.from_settings().ensure_bucket()

    yield

    stop.set()
    listener.cancel()
    try:
        await listener
    except asyncio.CancelledError:
        pass
    await close_redis_client()
    await engine.dispose()
```

### Startup, item by item

1. **`setup_logging()`** — configure handlers/formatters per process. Doing it
   here means `uvicorn`'s own loggers inherit the configuration.
2. **WS Redis listener** — a background task started per process. It subscribes
   to `teamflow:ws` and forwards events to sockets connected to *this* worker.
   This is the piece that makes WebSockets multi-worker safe
   (`infrastructure/06-websocket-scaling.md`).
3. **`ensure_bucket()`** — dev convenience so a bare `uvicorn` run works
   without the `minio-setup` compose job. Skipped in testing (no MinIO needed;
   attachment tests use a fake storage dependency). Failures are logged and
   swallowed inside the method — storage must not prevent the API from booting.

### Shutdown, item by item

Shutdown order is deliberate:

```python
stop.set()              # signal the listener loop
listener.cancel()       # interrupt the redis pubsub await
await listener          # reap the task (CancelledError handled)
await close_redis_client()   # now safe: listener no longer uses it
await engine.dispose()       # close DB connections last
```

Reverse dependency order: the listener uses Redis, so it dies before Redis. The
DB engine is owned by nobody else. Skipping `engine.dispose()` leaves pooled
connections for the OS to reap — noisy in logs and ungraceful in container
stops.

## What lifespan is *not*

- **Not a place for per-request state.** Request sessions come from the
  `get_db` yield dependency (`fastapi/06-dependency-injection.md`).
- **Not a guarantee in tests.** httpx's `ASGITransport` does **not** run
  lifespan. TeamFlow's HTTP tests deliberately rely on this: no Redis listener,
  no bucket check, no engine disposal. WebSocket tests use
  `fastapi.testclient.TestClient`, whose context manager *does* run lifespan —
  which is why the WS tests work at all
  (`tests/integration/test_websockets.py`).
- **Not a scheduler.** Periodic jobs are Celery Beat
  (`infrastructure/05-celery-beat.md`), not `asyncio.sleep` loops — those die
  with the process and don't survive deploys.

## Django/DRF comparison 🔵

| Django | FastAPI |
| --- | --- |
| `AppConfig.ready()` | lifespan startup |
| `@receiver(request_started)` for per-request | dependencies |
| No standard shutdown hook (atexit at best) | lifespan teardown (graceful) |
| `django.setup()` implicit on import | never — explicit factory + lifespan |

Django has no first-class shutdown signal; FastAPI's is a real part of the
request-serving contract (gunicorn sends SIGTERM, uvicorn drains requests, then
lifespan teardown runs).

## Production perspective

- One lifespan per **worker process**. `gunicorn -w 2` → two listeners, two
  engines. Connection pools multiply: `workers × (pool_size + max_overflow)`.
  TeamFlow's pool is 10+10 by default (`app/core/db.py`) — 2 workers → up to 40
  Postgres connections; size Pg/PgBouncer accordingly.
- Graceful shutdown with in-flight requests: uvicorn finishes current requests
  before teardown; the compose file gives containers a stop grace period
  (`docker-compose.prod.yml`: `stop_grace_period: 40s`).
- The listener's reconnect loop (`run_redis_listener` catches exceptions and
  retries every 2s) means a Redis restart degrades realtime but does not kill
  the API.

## Common mistakes

1. **Creating the engine as a module global *and* using lifespan to "connect"**
   — TeamFlow creates the engine at import (cheap, lazy connections) and only
   disposes it in lifespan. Connecting eagerly in startup hides connection
   errors until traffic arrives; with lazy pooling the first request needs the
   DB anyway, and `/health/ready` reports it.
2. **Assuming lifespan runs in tests.** If your test calls a WS-dependent
   feature via ASGITransport, nothing is subscribed. Use `TestClient` or drive
   the listener manually.
3. **Putting a periodic loop in lifespan.** It runs once per process → N times
   with N workers. Use Celery Beat.
4. **Forgetting teardown**, then wondering why `--reload` leaks Redis
   connections.

## Cheat sheet

```python
@asynccontextmanager
async def lifespan(app):
    resource = await create()     # once per process
    app.state.resource = resource
    yield
    await resource.close()        # on graceful shutdown
```

## Review questions

1. Why does the WS listener live in lifespan rather than in a dependency?
2. Why do HTTP integration tests not need Redis running for the *listener*,
   while WS tests do need the app's lifespan?
3. What breaks if `engine.dispose()` is removed?
4. Why is Celery Beat a better home for "every hour, warm the dashboard cache"
   than a loop in lifespan?
