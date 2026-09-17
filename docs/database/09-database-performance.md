# Database 09 — Database Performance

## Concept

Performance work starts from **measured bottlenecks**, not intuition. This
lesson catalogues TeamFlow's deliberate performance decisions, the bottleneck
each one addresses, and the honest limits of the current design.

## Connection pooling and lifecycle

```python
# app/core/db.py
_engine_kwargs: dict = {"echo": settings.debug, "pool_pre_ping": True}
if settings.environment == "testing":
    _engine_kwargs["poolclass"] = NullPool
else:
    _engine_kwargs["pool_size"] = settings.db_pool_size      # 10
    _engine_kwargs["max_overflow"] = settings.db_max_overflow # 10

engine: AsyncEngine = create_async_engine(settings.database_url, **_engine_kwargs)
```

- **Pooling** avoids a TCP+auth round trip per request. Defaults: 10 warm + 10
  overflow per process.
- **`pool_pre_ping=True`** costs a tiny round trip but transparently replaces
  connections killed by network blips/PG restarts.
- **`NullPool` in tests** because pooled asyncpg connections are bound to an
  event loop, and tests run across several loops (TestClient portals +
  pytest-asyncio) — a documented, real bug fix, not a hack.

Bottleneck addressed: connection setup latency. Capacity math:
`workers × (pool_size + max_overflow) ≤ max_connections`. Two API workers + one
Celery worker (sync pool 5+5) ≈ 50 connections; Postgres default 100 leaves
headroom.

## Session lifecycle

One session per request (`get_db` yield dependency), closed in the dependency's
`async with`. Sessions hold a connection only while a transaction is open;
between statements the connection returns to the pool (SQLAlchemy behavior with
`autobegin`). Net effect: a request that does three quick queries doesn't pin a
connection while you serialize the response.

## Query shapes (the real optimization)

| Endpoint | Queries | Rows loaded |
| --- | --- | --- |
| task list (limit 20) | 4 (page + count + 2 selectin) | 20 tasks + their labels/watchers |
| task detail | 1 (all eager joins/selectins) | 1 task |
| dashboard | 5 aggregates (`GROUP BY`, `FILTER`, `COUNT`) | **zero task rows** |
| notifications page | 2 (page + count) | 20 notifications |
| audit page | 2 | 50 rows |

The dashboard is the showcase: total/completed/overdue/unassigned/status-counts/
per-member — six numbers, five queries, zero rows in Python
(`app/services/dashboard.py`). Doing it the naive way (`select(Task)` then
`len([t for t in tasks if ...])`) loads the whole org's tasks per dashboard hit.

## Pagination as a performance control

`limit` caps at 100 at the API and is clamped again in the repository
(`database/05-pagination-filtering-sorting.md`). This bounds: rows fetched,
rows serialized, selectin IN-list sizes, and response bytes. One parameter,
four cost centers.

## Caching (read-path relief)

`app/services/cache.py` + `app/services/dashboard.py`:

- dashboard stats cached 60s in Redis, keyed `teamflow:cache:dashboard:{org_id}`;
- **explicit invalidation** on task/project/member mutations
  (`cache.invalidate_dashboard(org_id)`) — the TTL is only a safety net;
- cache failure degrades to direct computation (never an error).

Bottleneck addressed: repeated dashboard polling (a dashboard page polls
status counts; five aggregates × every viewer adds up). Trade-off: up to 60s
staleness if an invalidation is lost; acceptable for stats.

## Indexes and the counted cost

`database/07-indexes-and-constraints.md` maps every index to a query. The
performance discipline: indexes exist for observed patterns; each one taxes
writes. If task writes ever slow down, the first review step is listing which
of the five `tasks` indexes are actually used by production traffic.

## Async I/O (the systemic win)

Every DB call is `await`ed on the async engine; while a request waits for
Postgres, the worker's event loop serves other requests. This is the largest
throughput lever in the whole system — and the easiest to destroy: one blocking
call (sync HTTP, `time.sleep`, sync bcrypt in a hot path, a sync DB call) stalls
every request on that worker. TeamFlow's rules:

- DB: async engine everywhere in the API.
- Redis: async client.
- MinIO: blocking SDK, but only *presigned URL computation* (pure CPU, no
  network) touches requests; `stat`/`remove` run in threadpools
  (`app/services/integrations/storage.py`).
- Celery enqueue: `run_in_threadpool(celery_app.send_task, ...)`.
- bcrypt: blocking (~100ms at cost 12) but only on auth endpoints and rate
  limited — accepted, documented (`async/03-blocking-vs-nonblocking.md`).

## Known limits and their upgrade paths (honest list)

| Limit | When it hurts | Upgrade |
| --- | --- | --- |
| `OFFSET` pagination | deep pages (>10k rows) | keyset pagination (`WHERE (created_at, id) < (?, ?)`) |
| `ILIKE '%term%'` search | large task tables | `pg_trgm` + GIN index, or full-text `tsvector` |
| Random UUIDv4 PKs | very hot inserts (index locality) | UUIDv7 / ULID |
| Dashboard cache 60s TTL | stats freshness requirements | shorter TTL or `LISTEN/NOTIFY`-driven invalidation |
| Webhook event matching in Python | thousands of webhooks per org | `jsonb` containment query / join table |
| Single DB | read-heavy scale-out | read replicas + read-only session routing |
| Per-request session with multiple queries | chatty endpoints | explicit batching (e.g., load all selectins upfront — already the strategy) |

## What TeamFlow deliberately does NOT optimize

- **No query result caching for task lists.** They change constantly; the cache
  would be invalidated more than it would hit.
- **No materialized views.** Dashboard aggregates over a few thousand rows are
  milliseconds; a matview adds refresh complexity.
- **No `SELECT ... FOR UPDATE` on business rows.** The only row locks are the
  idempotency claim, where contention is per-key and rare. Business operations
  use optimistic semantics (lost update on tasks is possible under concurrent
  edits — accepted for a task tracker; the audit log records the last writer).

## Review questions

1. Why does the dashboard load zero task rows, and which SQL features make that
   possible?
2. What capacity math must hold between `db_pool_size`, worker counts, and
   Postgres `max_connections`?
3. Pick one item from the "known limits" table and describe the exact workload
   that would force the upgrade.
4. Which single blocking call in a hot endpoint would hurt throughput most, and
   where in TeamFlow are blocking calls allowed on purpose?
