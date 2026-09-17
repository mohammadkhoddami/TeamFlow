# Mastery 07 — Mastery Map

Every major concept → where it lives → why it exists. Use this to navigate the
codebase from a concept, not a file name.

## FastAPI

| Concept | TeamFlow implementation | File | Why it exists |
| --- | --- | --- | --- |
| App factory | `create_app()` | `app/main.py` | explicit wiring; testable construction |
| Lifespan | startup/shutdown context manager | `app/main.py` | once-per-process resources (engine, Redis, WS listener) |
| Routing | 14 router files, 46 paths | `app/api/routes/*.py` | HTTP surface per feature |
| Router aggregation | `api_router.include_router(...)` | `app/api/router.py` | single include point |
| Path/query/body | typed params + `Query(ge/le)` + schemas | `app/api/routes/tasks.py` | validated contract in the signature |
| Response models | every route declares one | `app/schemas/*.py` | allow-list against leaks |
| Pydantic validation | `EmailStr`, `Literal`, `Field`, `field_validator` | `app/schemas/auth.py`, `label.py` | reject bad input before logic |
| Dependency injection | `DB`, `CurrentUser`, `TaskAccess` | `app/api/deps.py` | context + tenant gate |
| Dependency factories | `ip_rate_limiter(scope, max, window)` | `app/core/rate_limit.py` | parameterized guards |
| Dependency overrides | `app.dependency_overrides[get_storage]` | `tests/integration/test_attachments.py` | replace infrastructure in tests |
| Middleware (pure ASGI) | request id + access log | `app/core/middleware.py` | per-request correlation |
| Middleware order | CORS → Idempotency → RequestContext | `app/main.py` | last-added-is-outermost semantics |
| Exception handlers | `AppError` tree + 422/DB/500 handlers | `app/core/exceptions.py` | domain → HTTP mapping, sanitized 500s |
| WebSockets | project channel, rooms, ping/pong | `app/websocket/router.py`, `manager.py` | realtime collaboration |
| OpenAPI | titles, tags, summaries, OAuth2 wiring | `app/main.py`, routes | living documentation at `/docs` |
| Custom middleware (stateful) | idempotency claim + replay | `app/core/idempotency.py` | exactly-once-ish writes |
| BackgroundTasks | **not used** — Celery instead | `app/workers/tasks.py` | durability + retries |

## SQLModel / Database

| Concept | TeamFlow implementation | File | Why it exists |
| --- | --- | --- | --- |
| Table models | 16 tables | `app/models/*.py` | persistence shape |
| Mixins | `UUIDMixin`, `TimeStampedMixin` | `app/models/base.py` | consistent PKs/timestamps |
| Meta schemas | create/update/read per resource | `app/schemas/*.py` | wire contract ≠ DB shape |
| FKs + cascades | `ondelete="CASCADE"/"SET NULL"` | models | DB-enforced lifecycle |
| Unique constraints | idempotency key, memberships, labels... | models | correctness invariants |
| Indexes | tenant-first composites | `app/models/task.py` | indexed hot queries |
| Relationships | eager-only, one-directional | `app/models/task.py` | async safety |
| Link models (M2M) | `TaskLabelLink`, `TaskWatcherLink` | `app/models/task.py` | explicit link-table writes |
| Sessions | one per request, `expire_on_commit=False` | `app/core/db.py` | async-safe unit of work |
| Queries | `select()`, `func.count`, `group_by`, `FILTER` | `app/repositories/task.py`, `app/services/dashboard.py` | SQL in one layer; aggregates in DB |
| Filtering/sorting | `TaskFilters` + `SORT_COLUMNS` | `app/repositories/task.py` | validated, injection-proof |
| Pagination | `Page[T]`, offset/limit, clamped | `app/schemas/common.py`, route + repo | bounded cost |
| Transactions | service-owned single commit | `app/services/organizations.py` | atomic multi-table writes |
| N+1 avoidance | joined/selectin + refetch | `app/services/tasks.py` (`refetch_task`) | O(1) queries per page |
| Writes without lazy loads | link-table insert/delete | `app/services/tasks.py` | `MissingGreenlet` prevention |
| Migrations | initial schema, async env | `migrations/`, `alembic.ini` | versioned schema |

## Auth & Tenancy

| Concept | TeamFlow implementation | File | Why it exists |
| --- | --- | --- | --- |
| Password hashing | bcrypt via passlib (pinned) | `app/core/security.py` | credential safety |
| JWT issue/verify | HS256, algorithm pinned, `sub/type/exp/jti` | `app/core/security.py` | stateless identity |
| Access token | 30-min, `CurrentUser` dependency | `app/api/deps.py` | per-request identity |
| Refresh rotation | Redis JTI whitelist, reuse detection | `app/services/auth.py`, `token_store.py` | theft containment |
| Logout / logout-all | JTI delete / pattern revoke | `app/services/auth.py` | session control |
| Password reset | single-use hashed tokens (GETDEL) | `app/services/auth.py`, `token_store.py` | safe recovery |
| Rate limiting | sliding window ZSET, IP + email | `app/core/rate_limit.py` | abuse control |
| RBAC | rank map (member<manager<admin<owner) | `app/services/organizations.py` | hierarchical authority |
| Tenant gate | `OrgMembership` / `*Access` deps (404) | `app/api/deps.py` | IDOR containment |
| Role rules | outrank-target-and-role, owner immutable | `app/services/organizations.py` | no peer creation |
| Audit trail | `audit.log` in-transaction | `app/services/audit.py` | forensic history |

## Architecture

| Concept | TeamFlow implementation | File | Why it exists |
| --- | --- | --- | --- |
| Layered path | router → deps → service → repo | whole `app/` tree | single home per concern |
| Routers thin | delegate + serialize | `app/api/routes/*.py` | testability |
| Services | rules, authz, one commit | `app/services/*.py` | business logic |
| Repositories | SQL, flush only | `app/repositories/*.py` | query audit + composition |
| Transaction boundaries | service-owned | `database/06` | atomicity |
| Modular monolith | folders as modules | `app/` | scale without distributed tax |
| Observability | contextvar request id, access log | `app/core/logging.py`, `middleware.py` | "which request did this?" |

## Async

| Concept | TeamFlow implementation | File | Why it exists |
| --- | --- | --- | --- |
| Async endpoints | all routes | `app/api/routes/*.py` | concurrency on waits |
| Async DB | asyncpg engine | `app/core/db.py` | non-blocking queries |
| Async Redis | redis.asyncio client | `app/core/redis.py` | non-blocking cache/limits/pubsub |
| Threadpool offload | `run_in_threadpool` | `events.py`, `storage.py` | sync libs without stalling |
| Sync workers | `session_scope` | `app/core/db_sync.py` | Celery needs no loop |
| Blocking acceptance | bcrypt inline | `app/services/auth.py` | rate-limited, documented |

## Infrastructure

| Concept | TeamFlow implementation | File | Why it exists |
| --- | --- | --- | --- |
| Redis shared state | 4 uses with degradation modes | `app/core/redis.py` + services | multi-worker coordination |
| Caching | dashboard stats + invalidation | `app/services/cache.py`, `dashboard.py` | absorb polling |
| Rate limiting | ZSET sliding window | `app/core/rate_limit.py` | abuse control |
| Celery tasks | email, webhook, cleanup, stats, reminders | `app/workers/tasks.py` | durable async work |
| Celery beat | 3 scheduled jobs | `app/workers/celery_app.py` | periodic work, single process |
| Shared HTTP client | worker-process httpx | `app/workers/celery_app.py` | connection reuse |
| WebSocket scaling | publish → Redis → listener → rooms | `app/services/events.py`, `app/websocket/*` | N workers, no sticky sessions |
| Object storage | presigned PUT/GET, private bucket | `app/services/integrations/storage.py` | stateless API, no proxying |
| Webhooks | durable rows, HMAC, retries, tracking | `app/services/events.py`, `webhooks.py`, worker task | reliable outbound events |
| Idempotency | claim-first middleware, replay | `app/core/idempotency.py` | safe retries |

## Testing & Production

| Concept | TeamFlow implementation | File | Why it exists |
| --- | --- | --- | --- |
| Test strategy | unit / integration / workers split | `tests/` | test where semantics live |
| Test infra | dedicated DB + Redis DB 15, truncation | `tests/conftest.py` | isolation |
| API factories | register→login→create via API | `tests/utils.py` | real paths in setup |
| Security tests | IDOR, RBAC, tokens, rate limits | `tests/integration/*` | negative-space coverage |
| Worker tests | direct task invocation + real receiver | `tests/workers/*` | retries/signatures for real |
| WS tests | TestClient (lifespan) + real Redis | `tests/integration/test_websockets.py` | pub/sub path |
| Docker | multi-stage, non-root, healthcheck | `Dockerfile` | small, safe image |
| Compose dev/prod | health-gated deps, env guards | `docker-compose*.yml` | reproducible environments |
| Configuration | typed `Settings`, `.env.example` | `app/core/config.py` | 12-factor |
| ASGI workers | gunicorn + UvicornWorker, graceful stop | `Dockerfile`, `production/04` | process management |
| Nginx | proxy + WS upgrade + body cap | `deploy/nginx.conf` | edge concerns |
| Health/readiness | `/health/live`, `/health/ready` | `app/api/routes/health.py` | probes done right |
| Logging | JSON option, request/user/org context | `app/core/logging.py` | correlated operations |
| Security review | findings + fixes | `production/07` | honest posture |
| Deployment | migrate → start → verify runbook | `production/08` | repeatable releases |

## Review questions

1. Pick five rows and locate the code from memory before checking.
2. Which concept appears in *three* layers (hint: tenant isolation)? List its
   three homes.
3. Which row has no code because the answer is "we chose not to"?
