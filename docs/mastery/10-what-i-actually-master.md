# Mastery 10 — What You Actually Mastered (Honest Status)

The rule for this document: **a file existing is not mastery.** "Practiced"
means the concept is implemented, exercised by tests or verification, and
reviewable in the code. "Studied" means it appears in the course but is not
deeply exercised by this project. "Not fully covered" means TeamFlow does not
adequately teach it — you would need another project (or real production) to
master it.

## ✅ Practiced — implemented, tested, verifiable

| Concept | Evidence in this repo |
| --- | --- |
| FastAPI routing, params, response models | 46 paths; `fastapi/02–04`; API tests pin shapes |
| Pydantic validation (constraints, Literal, validators) | schemas + 422 assertions |
| Dependency injection incl. factories and overrides | `app/api/deps.py`; fake-storage override |
| Middleware (pure ASGI: request id/logging, idempotency) | `app/core/middleware.py`, `idempotency.py` |
| Exception taxonomy + handlers | `app/core/exceptions.py`; status-code tests |
| Lifespan (resources + background listener) | `app/main.py`; WS tests run it |
| WebSockets end-to-end | live-verified 2-user fan-out; `test_websockets.py` |
| SQLModel models, mixins, constraints, indexes | `app/models/*`; migration verification |
| Relationships with eager strategies | `joined`/`selectin`; N+1 analysis |
| Async-safe M2M writes + refetch | `_set_task_labels`, `refetch_task` |
| Filtering/sorting/pagination (injection-proof) | `TaskFilters`, `SORT_COLUMNS`, clamped limits |
| Transactions (service-owned, side-effect ordering) | `create_organization`, `dispatch_webhooks` |
| Multi-tenancy / IDOR prevention | `*Access` deps; IDOR matrix tests |
| RBAC rank rules | rank matrix tests (every rule) |
| bcrypt + pinned bcrypt version | unit tests; auth flow |
| JWT with rotation + reuse detection | refresh-replay test burns the family |
| Single-use reset tokens | GETDEL store; reset flow test |
| Sliding-window rate limiting (fail-open) | rate-limit tests incl. Redis-down |
| Redis: 4 uses with degradation modes | token store, limits, cache, pub/sub |
| Redis pub/sub fan-out across workers | architecture + WS tests (in-process) |
| Celery tasks with retries/backoff/idempotency | worker tests (success/retry/permanent/duplicate) |
| Celery Beat scheduled jobs | cleanup/warm/reminder tasks; beat config |
| Webhooks (durable rows, HMAC, classification, sweeper) | worker tests with a real receiver |
| Presigned S3 uploads with validation | attachment tests; live MinIO verified |
| Idempotency middleware (claim-before-handler) | replay/conflict/scoping tests |
| Audit logging in-transaction | audit route + assertions |
| Dashboard aggregation without row loading | `compute_stats`; dashboard tests |
| Caching with explicit invalidation + TTL | cache tests; documented gaps |
| Structured logging with request/user/org context | middleware + filter |
| Health/readiness split | health tests |
| Alembic migrations (up/down/up verified) | scratch-DB cycle |
| Docker dev + prod (non-root, healthchecks, graceful stop) | compose validation; Dockerfile |
| Test strategy (unit/integration/worker split, real infra) | 69 tests, all passing |

## 📖 Studied — understood from the course, lightly exercised

| Topic | Why it's "studied" not "practiced" |
| --- | --- |
| Nginx production behavior | config shipped + validated, never run under real TLS/LB traffic |
| gunicorn/uvicorn multi-worker behavior | 2-worker prod command exists; all verification ran single-process |
| Redis Cluster/Sentinel | single-node Redis only |
| Zero-downtime migration patterns | single initial migration; add/backfill/constrain flow described, not performed |
| Rolling deploys & drain behavior | graceful settings present; no orchestrator to observe them |
| Postgres EXPLAIN analysis | indexes designed and justified, but no query-plan runs recorded |
| `pg_trgm`/full-text search | documented upgrade path, not implemented |
| Keyset pagination | documented upgrade path, not implemented |
| Prometheus metrics / tracing | absent from the project entirely (see below) |
| Multi-region/clock-skew JWT leeway | noted, not configured |

## ❌ Not fully covered — TeamFlow does not teach these adequately

| Gap | What's missing | Where you'd learn it |
| --- | --- | --- |
| **Metrics & tracing** | no `/metrics`, no OpenTelemetry; only logs + health | a project with Prometheus/Grafana + OTel |
| **Deploy orchestration** | no k8s manifests, no CI/CD pipeline, no IaC | k8s/Helm or ECS + GitHub Actions exercises |
| **Database migrations at scale** | one migration; no concurrent index builds, no data backfills | a live system with traffic during migrations |
| **RLS / DB-enforced tenancy** | app-enforced only (recommended hardening listed) | Postgres RLS + session variables |
| **File scanning / magic bytes** | declared-types allow-list only; gaps documented | AV scanning / upload proxying |
| **SSRF defenses** | gap documented, no CIDR blocking implemented | egress-proxy patterns |
| **OAuth2/OIDC provider integration** | password flow only; no external IdP, no refresh-token DPOP/mTLS | authlib/external IdP integration |
| **Cookie/session + CSRF patterns** | intentionally absent (token API) | a server-rendered app with sessions |
| **Load/performance testing** | no k6/Artillery; capacity math is theoretical | load tests against the real stack |
| **Chaos/failure injection** | failure modes reasoned about; not experimentally induced | chaos tooling / game days |
| **Celery result usage & chords/groups** | single tasks only; result backend barely used | workflow-heavy Celery projects |
| **BackgroundTasks** | deliberately unused (Celery instead) — you have not written one | a small in-process job |
| **Server-sent events / streaming responses** | not used anywhere | SSE/StreamingResponse exercise |
| **`populate_existing`-style ORM subtleties beyond the one case** | one instance exercised | larger ORM surfaces |
| **React/UI integration** | no frontend exists to prove the API ergonomics | build a real client |

## The honest summary

You can now: read this codebase and explain every architectural decision; review
agent-generated FastAPI code against the checklist; design a similar
multi-tenant async API with workers, realtime, storage, and webhooks.

You cannot yet claim from *this project alone*: production traffic experience,
observability beyond logs, orchestrator-level deployment, or the security
hardening items listed as gaps (S1–S8 in `production/07`). Those need either
implementation here or a more operationally complete project.

## Your next moves (pick three)

1. Fix the eight findings in `production/07` and add regression tests (S1 is
   one line + one test).
2. Add `/metrics` (prometheus-fastapi-instrumentator) + a Grafana dashboard for
   the existing log signals.
3. Write the k6 load test for the task list and record EXPLAIN plans for the
   five `tasks` queries.
4. Implement RLS in a scratch migration and verify a "forgotten filter" is
   caught by the database.
5. Build a minimal SPA (login, task board, WS updates) to feel the API as a
   client.

## How to self-assess honestly

For any item in the ✅ list, you should be able to:

1. explain it in three sentences to another Django developer,
2. point to the file,
3. name one failure mode it prevents,
4. state its main trade-off.

If you cannot do all four without looking, it belongs in 📖, not ✅.
