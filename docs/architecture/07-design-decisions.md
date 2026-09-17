# Architecture 07 — Design Decisions

Every decision below follows the same template:

```
Decision → Problem → Alternatives → Why TeamFlow chose this → Trade-offs → When to choose differently
```

---

## 1. SQLModel over plain SQLAlchemy

- **Problem**: two model languages (SQLAlchemy for DB, Pydantic for API) drift.
- **Alternatives**: SQLAlchemy + separate Pydantic schemas; Django ORM (not available); raw SQL.
- **Chosen**: SQLModel — one class family, Pydantic-native, SQLAlchemy underneath.
- **Trade-offs**: SQLModel's relationship ergonomics are the weakest part (link models must be defined before use, `Optional["User"]` quirks — `database/03`); some SQLAlchemy escape hatches need `sa_column`.
- **Choose differently**: complex ORM features (polymorphic inheritance, advanced loader options) push toward plain SQLAlchemy 2.0 declarative. TeamFlow uses `sa_column`/`sa_relationship_kwargs` exactly to stay near the metal.

## 2. Async API + async DB, sync workers

- **Problem**: thread-per-request (WSGI) caps concurrency; DB waits dominate API latency.
- **Alternatives**: sync FastAPI (threadpool); async API + sync DB (defeats the purpose); async Celery workers.
- **Chosen**: async endpoints, async engine/`asyncpg`, sync `psycopg` in Celery via `session_scope`.
- **Trade-offs**: async correctness discipline is mandatory (`MissingGreenlet`, blocking calls); workers cannot reuse async repositories.
- **Choose differently**: CPU-bound APIs gain little from async; use sync + multiple processes.

## 3. Repository + service layers (vs fat routes)

- **Problem**: rule/query/HTTP entanglement; untestable without HTTP.
- **Alternatives**: DRF-style fat viewsets; model methods (Django-active-record); service-only (no repositories).
- **Chosen**: thin routers → services (rules, transactions) → repositories (SQL only).
- **Trade-offs**: more files; occasional pass-throughs; two documented router exceptions.
- **Choose differently**: tiny CRUD-only services can skip repositories, but TeamFlow keeps one query-audit folder deliberately.

## 4. Stateless access JWT + stateful refresh in Redis

- **Problem**: stateless auth cannot log out; fully stateful auth taxes every request.
- **Alternatives**: session cookies (stateful); long-lived access tokens; DB-backed refresh whitelist.
- **Chosen**: 30-min access JWT (no storage read), 14-day refresh with JTI whitelist in Redis + rotation + reuse detection.
- **Trade-offs**: logout lag ≤ access TTL; a Redis flush logs everyone out (fail-closed); parallel refreshes must be serialized by clients.
- **Choose differently**: high-security apps need per-request revocation (token version counter in Redis on every request) — rejected here for hot-path cost.

## 5. UUIDv4 primary keys

- **Problem**: integer ids are enumerable and require a DB round trip.
- **Alternatives**: bigserial; UUIDv7; ULID.
- **Chosen**: UUIDv4 generated client-side.
- **Trade-offs**: index locality on very hot inserts; 16-byte keys.
- **Choose differently**: high-write tables → UUIDv7 (time-ordered, non-enumerable — the modern default).

## 6. Shared-schema multi-tenancy with `organization_id`

- **Problem**: tenant isolation must be enforced somewhere; per-tenant DBs are ops-heavy.
- **Alternatives**: DB/schema per tenant; Postgres RLS.
- **Chosen**: shared tables, org-filtered queries, server-resolved membership, 404 doctrine.
- **Trade-offs**: one forgotten filter = data leak; no per-tenant rate limiting.
- **Choose differently**: add RLS as a database-level backstop (recommended hardening, `production/07`).

## 7. Idempotency middleware (DB claim) instead of per-route logic

- **Problem**: retried writes duplicate resources; client-side dedupe is unreliable.
- **Alternatives**: no idempotency; per-route checks; Redis-only storage.
- **Chosen**: ASGI middleware, `Idempotency-Key` header, DB unique-constraint claim, response replay; Redis not used (durability required).
- **Trade-offs**: one DB write for keyed writes; response bodies stored ≤1MB; needs TTL cleanup (Celery Beat).
- **Choose differently**: Redis-only idempotency is fine for short windows (risk: loss on flush).

## 8. Celery + Redis broker for background work; no BackgroundTasks

- **Problem**: email/webhooks must survive failures and deploys; retries required.
- **Alternatives**: BackgroundTasks; in-process queues; Kafka.
- **Chosen**: Celery with task queues (`default/emails/webhooks`), beat schedule, DB-tracked deliveries.
- **Trade-offs**: broker dependency; more moving processes; sync workers can't reuse async repos.
- **Choose differently**: event streaming (Kafka) for high-volume pipelines; BackgroundTasks for fire-and-forget metrics.

## 9. WebSockets via Redis pub/sub (not sticky sessions, not channels lib)

- **Problem**: in-process connection registries break with N workers.
- **Alternatives**: sticky load balancing (single worker per client); Django Channels-style abstraction; SSE.
- **Chosen**: one Redis channel; per-worker listener → local manager; rooms inside payloads.
- **Trade-offs**: every worker parses every event (filtering is free at this scale); no delivery guarantee (fire-and-forget).
- **Choose differently**: per-room channels or a dedicated realtime service at high fan-out.

## 10. Presigned S3 URLs (no proxying of bytes)

- **Problem**: streaming files through API workers wastes workers and memory.
- **Alternatives**: multipart upload through FastAPI; direct-to-disk.
- **Chosen**: metadata row + presigned PUT; confirm via `stat`; presigned GET for downloads; MinIO locally.
- **Trade-offs**: client must do two calls (intent + confirm); orphaned objects need cleanup; `stat` touches storage.
- **Choose differently**: proxy uploads when you must scan bytes (AV) server-side — then accept the throughput cost.

## 11. Webhooks: DB row per delivery, HMAC-signed, Celery-delivered

- **Problem**: outbound HTTP is unreliable; silent drops are unacceptable.
- **Alternatives**: inline delivery (blocks requests); fire-and-forget task (no history).
- **Chosen**: durable delivery rows (pre-commit), Celery retries with backoff, `X-TeamFlow-Signature`, receiver-side dedupe via `X-TeamFlow-Delivery`.
- **Trade-offs**: at-least-once delivery; receiver must dedupe; sweeper needed for stranded rows.
- **Choose differently**: formal transactional outbox relay for exactly-once-ish semantics.

## 12. Modular monolith

- **Problem**: microservices solve organizational scaling, not code organization.
- **Alternatives**: microservices; shared-everything monolith without module boundaries.
- **Chosen**: one deployable, strict folder-level modules, clean seams (services/repos) for future extraction.
- **Trade-offs**: one blast radius; one dependency image; noisy-neighbor risk inside a process.
- **Choose differently**: when teams > ~5 streams of change or a module needs independent scaling (workers/WS are the realistic first splits).

## 13. Offset pagination, `ILIKE` search, in-Python webhook matching

- **Problem**: not every query needs the optimal structure at current scale.
- **Alternatives**: keyset pagination, `pg_trgm`/full-text, `jsonb @>`.
- **Chosen**: simplest correct forms, each with a documented upgrade path.
- **Trade-offs**: deep pages slow; search index-less; O(webhooks-per-org) matching.
- **Choose differently**: at 10⁶ tasks / 10³ webhooks per org, execute the upgrades in `database/09-database-performance.md`.

## 14. Ad-hoc JWT helpers instead of a library abstraction

- **Problem**: learning/auditing auth requires visible claims and checks.
- **Alternatives**: `python-jose`, `authlib`, `simplejwt`-style wrappers.
- **Chosen**: ~40 lines in `app/core/security.py` on `pyjwt`.
- **Trade-offs**: we own correctness (algorithm pinning, type checks — and a documented gap in `get_current_user`).
- **Choose differently**: multi-issuer/OIDC flows — use a vetted library.

---

## Cross-cutting theme

Every decision trades **simplicity now** for a **documented upgrade path**, and
every trade-off is written next to the code or in these docs. That is the
review standard this project tries to teach: not "optimal", but *chosen with
eyes open*.

## Review questions

1. Pick three decisions and name the failure each one's alternative would have
   caused in this codebase specifically.
2. Which decisions are *scale-triggered* upgrades rather than architectural
   mistakes?
3. Which decision would you reverse first if this were a payments product
   instead of a task tracker, and why?
4. Where is the "one forgotten filter = leak" risk concentrated, and what is
   the cheapest structural mitigation?
