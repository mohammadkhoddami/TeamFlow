# TeamFlow

Multi-tenant project management and collaboration API built with FastAPI,
SQLModel, PostgreSQL, Redis, Celery, and MinIO.

## Stack

| Concern            | Choice                                                        |
| ------------------ | ------------------------------------------------------------- |
| API                | FastAPI (async), Pydantic v2 schemas                          |
| ORM                | SQLModel (async SQLAlchemy underneath)                        |
| DB                 | PostgreSQL 16 + Alembic migrations                            |
| Cache / rate limit | Redis (refresh-token store, sliding-window limits, dashboard cache) |
| Background jobs    | Celery + Celery Beat (Redis broker), sync psycopg sessions    |
| Realtime           | WebSockets with Redis pub/sub fan-out (multi-worker safe)     |
| Object storage     | S3-compatible (MinIO in dev), presigned PUT/GET URLs          |
| HTTP client        | HTTPX (shared per worker process via lifespan/worker signal)  |

## Architecture

```text
Client -> FastAPI -> Router -> Dependencies -> Service -> Repository -> SQLModel -> PostgreSQL
                          \-> Redis / Celery / WebSocket / MinIO / external HTTP
```

- `app/api/` - routers (HTTP only) + `deps.py` (auth, tenant context, storage)
- `app/services/` - business rules, authorization, audit, events
- `app/repositories/` - every SQL query; services own transaction boundaries
- `app/models/` - SQLModel tables (tenant FK cascade, indexes)
- `app/schemas/` - request/response models (never leak DB fields)
- `app/core/` - config, db, logging, exceptions, middleware, idempotency
- `app/websocket/` - connection manager + Redis listener + WS endpoint
- `app/workers/` - Celery app + tasks (email, webhooks, cleanup, stats)
- `migrations/` - Alembic (async env)

## Quick start (development)

```bash
cp .env.example .env          # adjust secrets
uv sync                       # install dependencies
docker compose up -d db redis minio minio-setup
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
# optional background workers:
uv run celery -A app.workers.celery_app:celery_app worker -l info -Q default,emails,webhooks
uv run celery -A app.workers.celery_app:celery_app beat -l info
```

API docs: http://localhost:8000/docs (login via `POST /api/v1/auth/login`,
form-encoded, then use the returned access token as Bearer).

Run everything in Docker: `docker compose up` (api, worker, beat, db, redis, minio).

### Frontend (development)

A React SPA lives in `frontend/` (Vite + TypeScript + Tailwind + TanStack
Query). It covers auth, workspaces, projects, a realtime kanban board, tasks,
comments, attachments, labels, notifications, members/invitations, webhooks,
audit logs and the dashboard.

```bash
cd frontend
npm install
npm run dev            # http://localhost:3000 (matches default CORS_ORIGINS)
```

See `frontend/README.md` for details.

## Tests

Functional API/security/worker tests require the dev services (postgres, redis):

```bash
docker compose up -d db redis
uv run pytest tests -q
```

Test suite covers: auth flows (rotation, reuse detection, logout), RBAC and
tenant isolation (IDOR -> 404), task transitions/query filters, idempotency
replay, attachments (fake storage), webhook signing + retries + idempotency,
rate limiting, notifications, audit trail, dashboard aggregation, WebSockets.

## Key behaviors

- **Tenant isolation**: every tenant row carries `organization_id`; org-scoped
  access resolves membership server-side and returns 404 (not 403) for
  non-members so resource IDs cannot be probed across tenants.
- **Auth**: stateless short-lived access JWTs + stateful refresh tokens in
  Redis (rotation + reuse detection revokes the whole token family); password
  reset tokens are single-use and hashed at rest. Logout revokes refresh
  tokens; access tokens expire within their short TTL by design.
- **Idempotency**: `Idempotency-Key` header on POST/PATCH/DELETE; the claim is
  an INSERT with a unique key (race-safe), replay returns the stored response
  with `Idempotency-Replayed: true`, 409 while in flight, 422 on body mismatch.
- **Webhooks**: HMAC-SHA256 over `{timestamp}.{body}` (`X-TeamFlow-Signature`),
  delivery rows track attempts/responses, retries with backoff, 4xx
  (except 408/429) is permanent; receivers dedupe on `X-TeamFlow-Delivery`.
- **Realtime**: `/ws/projects/{id}?token=<access JWT>`; events flow through
  Redis pub/sub so any worker can publish and every worker fans out locally.
- **Files**: metadata in Postgres, bytes go directly to S3/MinIO via
  presigned URLs; server-generated keys, content-type allowlist, size cap.
- **Observability**: request IDs + structured access logs (JSON optional),
  `/api/v1/health/live` and `/api/v1/health/ready` (checks DB + Redis).

## Production

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Set `POSTGRES_USER/PASSWORD/DB`, `SECRET_KEY`, `CORS_ORIGINS`, `S3_*`,
`EMAIL_*` in the environment (see `.env.example`). Nginx terminates traffic and
proxies WebSocket upgrades (`deploy/nginx.conf`).
