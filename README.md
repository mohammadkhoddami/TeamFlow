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
| Admin panel        | sqladmin (server-rendered CRUD + dashboard, superuser session auth) |
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
- `app/admin/` - sqladmin views, superuser session auth, dashboard, audit backend
- `migrations/` - Alembic (async env)

## Quick start (development)

```bash
cp .env.example .env          # adjust secrets
uv sync                       # install dependencies
docker compose up -d db redis
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
# attachments/S3 locally: docker compose --profile minio up -d
# optional background workers:
uv run celery -A app.workers.celery_app:celery_app worker -l info -Q default,emails,webhooks
uv run celery -A app.workers.celery_app:celery_app beat -l info
```

API docs: http://localhost:8000/docs (login via `POST /api/v1/auth/login`,
form-encoded, then use the returned access token as Bearer).

Admin panel: http://localhost:8000/admin (server-rendered, session-cookie
auth). Only active **superusers** can sign in; see [Admin panel](#admin-panel).

Run the full stack in Docker: `docker compose up -d --build` (db, redis, api,
worker, beat, nginx; add `--profile minio` for local S3). One compose file,
production-shaped by default.

### Mock data

Load realistic, fully wired mock data (users, orgs, projects, labels, tasks,
comments, watchers, attachments, notifications, audit logs, webhooks) with
PostgreSQL COPY:

```bash
docker compose exec api uv run python scripts/seed_mock_data.py            # ~1M rows, ~3 min
docker compose exec api uv run python scripts/seed_mock_data.py --preset extreme
docker compose exec api uv run python scripts/seed_mock_data.py --reset    # truncate first
```

All generated users share the password `Password123!` (override with
`--password`); the script prints a sample login email at the end.

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

## Admin panel

A server-rendered operations UI (sqladmin, mounted at `/admin`) manages every
table without a separate frontend build:

- **Dashboard** (`/admin`): live counts (users/orgs/projects/tasks), task status
  breakdown, overdue tasks, recent users/organizations/tasks and audit activity.
- **CRUD** for users, organizations, memberships, invitations, projects, tasks,
  labels, comments, attachments, notifications and webhooks - with search,
  filters, sorting, pagination and CSV export.
- **Password management**: the user form has a write-only password field; the
  raw value is bcrypt-hashed server-side and never stored in the audit trail.
- **Guards**: admins cannot deactivate/demote/delete their own account and the
  last superuser cannot be deleted; webhook signing secrets are never rendered
  back and are auto-generated when omitted.
- **Audit trail**: every admin create/update/delete is appended to
  `audit_logs` (`actor`, target, IP, sanitized changes); logins/failures and
  logouts are audited too. Phishing-resistant by design: same-site session
  cookie, `Secure` in production, bcrypt timing equalized on unknown emails,
  login rate-limited per (IP, email).
- **Read-only views**: audit logs, webhook deliveries and idempotency keys.

```text
/admin            dashboard
/admin/user/list  any model list (identity = model slug, e.g. task -> /admin/task/list)
```

Access is session-based, not JWT: navigate to `/admin`, log in with a
superuser's email + password. Configure via `ADMIN_ENABLED`, `ADMIN_BASE_URL`,
`ADMIN_TITLE`, `ADMIN_SESSION_MAX_AGE_SECONDS` (see `.env.example`); the
session cookie is signed with a key derived from `SECRET_KEY`.

Bootstrap the first superuser (API registration never grants the flag):

```bash
uv run python scripts/create_superuser.py --email admin@example.com --password 'change-me-please'
# inside containers:
# docker compose exec api uv run python scripts/create_superuser.py \
#   --email admin@example.com --password 'change-me-please'
```

After that, promote/demote users from the admin panel itself.

## Tests

Functional API/security/worker tests require the dev services (postgres, redis):

```bash
docker compose up -d db redis
uv run pytest tests -q
```

Test suite covers: auth flows (rotation, reuse detection, logout), RBAC and
tenant isolation (IDOR -> 404), task transitions/query filters, idempotency
replay, attachments (fake storage), webhook signing + retries + idempotency,
rate limiting, notifications, audit trail, dashboard aggregation, WebSockets,
and the admin panel (superuser-only login, CRUD, audit redaction, guards).

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
docker compose up -d --build
uv run alembic upgrade head   # run migrations as an explicit deploy step
```

Set `POSTGRES_USER/PASSWORD/DB`, `SECRET_KEY`, `CORS_ORIGINS`, `S3_*`,
`EMAIL_*` in the environment (see `.env.example`). Nginx terminates traffic and
proxies WebSocket upgrades (`deploy/nginx.conf`).
