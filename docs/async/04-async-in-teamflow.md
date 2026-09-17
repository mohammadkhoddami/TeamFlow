# Async 04 — Async in TeamFlow: Every Decision in One Place

This is the audit lesson: every async choice in the codebase, its
justification, and the failure it prevents. Use it as a checklist when
reviewing new code.

## The choices

### 1. Engine and sessions — fully async

```python
# app/core/db.py
engine = create_async_engine(settings.database_url, **_engine_kwargs)   # asyncpg
AsyncSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession,
                                       expire_on_commit=False, autoflush=False)
```

- Prevents: thread-per-request DB wait; `MissingGreenlet` from expired
  attributes post-commit.
- Trade-off: relationships must be eagerly loaded (`database/03`).

### 2. One session per request via a yield dependency

```python
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
```

- Prevents: connection leaks, cross-request session sharing (asyncpg sessions
  are not task-safe).

### 3. Redis — async client, process-wide

```python
_client = Redis.from_url(settings.redis_url, decode_responses=True, ...)
```

- Used for: refresh-token store, rate limits, WS publish, dashboard cache.
- Failure handling: rate limiting fails **open**, cache reads fall back to the
  DB, WS publish logs and continues (`infrastructure/01-redis.md`).

### 4. MinIO — sync SDK, split treatment

| Operation | Treatment |
| --- | --- |
| `presign_put` / `presign_get` | inline (pure CPU/HMAC) |
| `stat` / `remove` / `bucket_exists` | `run_in_threadpool` |
| `ensure_bucket` (lifespan) | threadpool, failures swallowed |

### 5. Celery enqueue — threadpool at call sites

```python
await run_in_threadpool(celery_app.send_task, "teamflow.deliver_webhook", [str(delivery.id)])
await run_in_threadpool(celery_app.send_task, "teamflow.send_email", [...])
```

- Prevents: kombu's sync Redis write blocking the loop on every invite/webhook.
- Note the ordering guarantee: enqueue happens **after** the DB commit
  (`database/06`).

### 6. Celery workers — sync by design

```python
# app/core/db_sync.py
sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True, ...)
@contextmanager
def session_scope() -> Session: ...
```

- Prevents: nested event loops in tasks; loop-per-task overhead.
- Cost: workers query models directly (async repositories can't run there) —
  accepted and localized (`app/workers/tasks.py`).

### 7. WebSockets — async end to end

- Endpoint: async handler, async sends.
- Listener: `asyncio.create_task` in lifespan, reconnects every 2s on Redis
  failure, cancelled on shutdown.
- Manager: an `asyncio.Lock` serializes connect/disconnect mutations.

### 8. HTTPX — one client per worker process

```python
# app/workers/celery_app.py
@worker_process_init.connect
def init_worker(**kwargs):
    global http_client
    http_client = httpx.Client(timeout=settings.webhook_timeout_seconds,
                               trust_env=settings.webhook_httpx_trust_env,
                               limits=httpx.Limits(max_connections=20,
                                                   max_keepalive_connections=10))
```

- Sync `httpx.Client` in workers; **no HTTP client in the API** because no API
  path makes outbound HTTP calls. If one ever does, it must be an
  `httpx.AsyncClient` created in lifespan — not per request.
- `trust_env` is configurable for a very real reason: a host-level proxy
  intercepted localhost webhook calls during development (502s), fixed by
  `WEBHOOK_HTTPX_TRUST_ENV=false`.

### 9. Background tasks in-process (Dashboard cache invalidation, WS publish)

Both are Redis ops (microseconds, awaited inline) — "background" in effect but
not in mechanics. No `BackgroundTasks` anywhere (`fastapi/11`).

### 10. Tests — loop-aware setup

- `NullPool` engine in testing (multiple loops: TestClient portal + pytest
  session loop).
- HTTP tests use httpx `ASGITransport` (no lifespan → no listener).
- WS tests use `TestClient` (runs lifespan) plus sync psycopg truncation
  because sync tests don't run async fixtures.

## Failures this discipline prevents (the "what if" table)

| If TeamFlow had... | Failure |
| --- | --- |
| sync psycopg in API | loop blocked per query; throughput collapses |
| `requests` for webhooks in API | loop blocked per delivery (fixed: workers only, httpx) |
| inline `celery_app.send_task` | loop blocked per invite/webhook ~ms each, under load it snowballs |
| async ORM lazy loading relied upon | `MissingGreenlet` at serialization (fixed: eager strategies) |
| one session shared across requests | transaction bleed, asyncpg task-safety errors |
| `asyncio.run` in services | `RuntimeError: no running event loop`/nested-loop crashes |

## Django/DRF comparison 🔵

The equivalent Django codebase would be sync top to bottom (threads absorb
waits), with Celery identical and WebSockets via Channels. TeamFlow's async is
not "better" absolutely — it is the choice that lets one worker hold thousands
of idle connections (WS) and cheaply wait on DB/Redis, at the price of the
discipline audited above.

## Review questions

1. Why does the API have no `httpx` client at all, while workers have exactly
   one?
2. What two test-driven constraints shaped `NullPool` and the `trust_env`
   setting?
3. Which async decisions would you revisit first under (a) high CPU load, (b)
   very high auth traffic, (c) WebSocket fan-out growth?
4. State the ordering rule that ties async side effects to transactions in one
   sentence.
