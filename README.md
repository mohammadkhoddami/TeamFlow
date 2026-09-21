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
an epic > story > task hierarchy (board and tree views, parent/subtask
navigation, progress roll-ups), comments, attachments, labels, notifications,
members/invitations, webhooks, audit logs and the dashboard.

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

## MCP server (agent integration)

`mcp_server/` is a standalone [Model Context Protocol](https://modelcontextprotocol.io)
server that turns TeamFlow into a project board any MCP-capable coding agent can
use - read the board, create and move cards, assign work, comment. It is a pure
API client with no database access, so the same package works against localhost
or the deployed instance.

Tools include `get_board` (kanban columns with accurate counts), `list_tasks`,
`get_task`, `create_task`, `update_task`, `move_task`, `delete_task`, `my_work`,
`add_comment`, `list_members`, `list_labels`, `create_label` and
`get_dashboard`. See `mcp_server/README.md` for the full list, argument
conventions and troubleshooting.

### Add it to opencode

Install the package once (Python 3.10+):

```bash
cd mcp_server
uv tool install .              # provides the `teamflow-mcp` command
uv run teamflow-mcp --check    # verify credentials end to end
```

Register the server **once, globally**, in `~/.config/opencode/opencode.jsonc`.
`cwd` is `"."`, which OpenCode resolves to the current workspace root, so the
server reads *that project's* `.env`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "teamflow": {
      "type": "local",
      "command": ["teamflow-mcp"],
      "cwd": ".",
      "enabled": true
    }
  }
}
```

Every project keeps its own identity, and no credentials appear in the config
file. Values layer per key, in increasing precedence: shared defaults at
`~/.config/teamflow/.env`, then the project's `.env`, then real environment
variables.

### Per-project credentials

Set up the shared defaults once per machine - the API URL, no identity:

```bash
mkdir -p ~/.config/teamflow
printf 'TEAMFLOW_API_URL=https://arsene.ir/flow\n' > ~/.config/teamflow/.env
```

Then each project declares only its own account in its `.env` (which must be
gitignored), for example `C:/repos/Arsen/.env`:

```env
TEAMFLOW_EMAIL=arsen@example.com
TEAMFLOW_PASSWORD=secret
TEAMFLOW_ORG=arsen
```

and `C:/repos/AiIdentity/.env`:

```env
TEAMFLOW_EMAIL=other@example.com
TEAMFLOW_PASSWORD=other-secret
TEAMFLOW_ORG=other-org
```

Give `TEAMFLOW_API_URL` the base URL only (`https://arsene.ir/flow`) - `/api/v1`
is appended automatically. `TEAMFLOW_ORG` is only needed when the account
belongs to more than one organization. The project file is found as
`<cwd>/.env`, falling back to the nearest ancestor `.env` up to the git root
that actually defines `TEAMFLOW_*` keys, so a project's unrelated keys
(`DATABASE_URL`, `SECRET_KEY`, ...) are ignored. `TEAMFLOW_ENV_FILE` pins an
explicit path.

Verify from inside a project - the account is masked and secrets are never
printed:

```bash
cd /path/to/the/project
uv run --project /path/to/TeamFlow/mcp_server teamflow-mcp --check
# Working dir: /path/to/the/project
#   project env: /path/to/the/project/.env
#   shared env : /home/you/.config/teamflow/.env
#   default org: arsen
# API        : https://arsene.ir/flow/api/v1
# User       : a***n@example.com (...)
# Orgs       : arsen [owner], other-org [member]
# OK: credentials work, the MCP server can log in.
```

If the API runs on `localhost` on a machine with a system proxy, add
`TEAMFLOW_TRUST_ENV=false` to the project's `.env`.

To run straight from a checkout instead of installing, replace `command` with:

```jsonc
"command": ["uv", "run", "--project", "/path/to/TeamFlow/mcp_server", "teamflow-mcp"]
```

Use `--project`, not `--directory`: `--directory` makes uv `chdir` into the MCP
server's folder first, so the workspace stops being the current directory and the
project's `.env` would never be found.

Restart opencode and the tools appear prefixed with the server name -
`teamflow_get_board`, `teamflow_create_task`, and so on. Then ask in plain
language:

```text
Use the teamflow tools: show me the board for "Payments API", then move the
checkout bug to in_review and assign it to alice@example.com.
```

### Teammates on the deployed instance

Every teammate uses their **own** TeamFlow account - never share one login, since
attribution, audit logs, comments and notifications all key off the account:

1. Register at `https://arsene.ir/flow/register` (password >= 10 characters).
2. An owner or admin invites them from `/org/<slug>/members`, choosing a role.
3. They accept the invitation at `https://arsene.ir/flow/invitations`.
4. They install the package and reuse the config above with their own
   `TEAMFLOW_EMAIL` / `TEAMFLOW_PASSWORD`.

Tenant isolation applies: an agent can only see the organizations its account
belongs to. To distribute the package, share the built wheel (`uv build` inside
`mcp_server/`, then `uv tool install ./teamflow_mcp-0.1.0-py3-none-any.whl`),
clone the repo, or publish to an index - `mcp_server/README.md` documents each
option, Docker included.

Note that login is rate limited to 5 attempts/minute/IP; the MCP server logs in
once per session and then rotates its refresh token, so normal use never hits
the limit.
