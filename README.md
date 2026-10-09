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

Sign-in options beyond email+password:

- **Registration requires email verification**: `POST /api/v1/auth/register`
  takes the emailed `code` alongside `email`/`password`/`full_name`. The SPA
  register page requests the code first (`POST /api/v1/auth/otp/request`) and
  only creates the account once the code is redeemed; codes are single-use.
- **Email OTP** (passwordless): `POST /api/v1/auth/otp/request` emails a
  6-digit code (SMTP backend), `POST /api/v1/auth/otp/verify` exchanges it for
  a token pair. Codes are single-use, hashed (HMAC) at rest, expire in 10
  minutes, and burn after 5 wrong attempts. First verification creates the
  account. The SPA route is `/login/otp`.
- **Google sign-in**: `GET /api/v1/auth/google/start` redirects to Google
  (authorization code + PKCE); the callback verifies the OIDC ID token against
  Google's JWKS, finds/creates the user by `google_id`/email, and hands the SPA
  a single-use exchange code (`POST /api/v1/auth/oauth/exchange`). Set
  `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` and register
  `{API_BASE}/api/v1/auth/google/callback` as an authorized redirect URI in the
  Google Cloud console (`GOOGLE_REDIRECT_URI` overrides the derived value).

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
navigation, progress roll-ups), Markdown task descriptions and comments with a
Write/Preview editor, attachments, labels, notifications, members/invitations,
webhooks, audit logs and the dashboard.

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
M3 adds threaded comments/reactions/activity, notification mutes, the
automation engine (conditions, actions, schedule runs, failure logging),
API tokens/service accounts/OAuth grants, releases/roadmap/calendar,
VCS + chat + calendar integrations, and cursor-pagination + query-budget
tests (`tests/integration/test_m3_*.py`). M4 adds MFA (TOTP + recovery),
OIDC SSO + SCIM provisioning, custom roles/permissions with private project
visibility, audit export + retention, goals/OKR roll-ups, dashboards, public
intake forms, the heuristic AI breakdown, plugins and push subscriptions
(`tests/integration/test_m4_*.py`). The frontend has Vitest coverage for the
Markdown (tables/images), i18n and theming layers (`npm test`).

## Agile features (M1)

Phase 1 of the competitive plan is implemented on top of the existing board:

- **Issue keys** — every project gets a `PROJECTKEY` (derived from its name,
  editable) and tasks receive atomic, sequential keys (`TEAM-123`) shown on
  cards, drawers, the tasks table, emails and the MCP server.
- **Sprints & backlog** — project-scoped sprints (name, goal, dates, state),
  one active sprint per project, start/complete with carry-over to a chosen
  sprint or back to the backlog, a backlog view with manual ordering, and a
  sprint filter on the board. Endpoints under `/projects/{id}/sprints` and
  `/sprints/{id}`.
- **Estimates** — per-task `estimate`/`remaining`/`actual` values with a
  per-project estimation unit (points/hours/none); sprint totals aggregate
  points for reports.
- **TeamQL + saved filters** — `GET /organizations/{slug}/tasks/query?q=...`
  parses a small query language (`status in (todo, in_progress) AND priority =
  high AND assignee = me ORDER BY due`); filters can be saved/shared per org
  (`/organizations/{slug}/saved-filters`) and reused from the tasks page.
- **Global full-text search** — `GET /organizations/{slug}/search?q=...`
  searches tasks, comments and projects through PostgreSQL expression GIN
  indexes (`websearch_to_tsquery`); bound to Ctrl/Cmd+K in the UI.
- **Bulk operations** — `POST /organizations/{slug}/tasks/bulk` supports
  update, move, clone, delete, archive/restore and move-to-project for up to
  200 tasks, with per-task failure reporting. Archive is a soft delete.
- **Email preferences & digests** — per-user subscription matrix
  (assigned/mentioned/comments/due), immediate/daily/weekly/off cadence,
  token-based unsubscribe, and `task_assigned`/`mention`/`comment_created`/
  `task_completed` emails actually enqueued. A daily Celery job sends digests.
- **Quick wins** — dark mode (system/light/dark), mention autocomplete in the
  Markdown editor, the advertised `member.joined` webhook is now dispatched,
  and `NotificationType.TASK_COMPLETED` is emitted to watchers.

## Planning depth (M2)

Phase 2 adds Jira-class planning while keeping the simple default:

- **Custom workflows & boards** — per-project statuses with categories,
  transition rules (which statuses may move to/from which), WIP limits
  (optional enforcement) and multiple saved boards with TeamQL filters,
  hidden issue types/status columns and swimlanes (assignee/priority/label).
  The classic four-column flow stays the default until a project saves its own
  workflow; board views can hide epics/stories or statuses like Done without
  touching the underlying tasks.
  `GET/PUT /projects/{id}/workflow`, `/projects/{id}/boards`, `/organizations/{slug}/boards/{id}`.
- **Custom fields** — typed fields (text/number/date/select/multi-select/user/
  checkbox) per project, stored as JSON values; filterable through TeamQL
  (`cf_<key> = value`). `/projects/{id}/custom-fields`.
- **Task links & dependencies** — blocks / is blocked by / relates to /
  duplicates / clones with cycle prevention and a derived `is_blocked` flag
  (`?blocked=true` filter). `/tasks/{id}/links`.
- **Agile reports** — burndown, velocity, cumulative flow (status-history
  aware), cycle/lead time (avg/P50/P85, CSV export) and sprint reports.
  `/projects/{id}/reports/*`, `/sprints/{id}/report`.
- **Velocity & capacity** — per-sprint member capacity with overload
  detection. `GET/PUT /sprints/{id}/capacity`.
- **Time tracking** — worklogs per task/user, `actual_estimate` kept in sync
  with logged hours, and an org timesheet with weekly totals.
  `/tasks/{id}/worklogs`, `/organizations/{slug}/timesheet`.
- **Templates** — built-in Scrum/Kanban/Bug-triage presets, save any project
  as a template (workflow, labels, fields, boards, hierarchy) and task
  templates with checklists. `/organizations/{slug}/project-templates`,
  `/task-templates/{id}/apply`.
- **Recurring tasks** — RFC 5545 RRULEs; completing a task (or the daily
  sweep) spawns the next occurrence idempotently.
- **Multiple assignees & checklists** — role-bearing assignees
  (assignee/approver) plus checklist items with progress.
- **Import & export** — Jira/Asana/generic CSV and Trello JSON importers
  (dry-run supported) and a full workspace JSON export (optionally with
  attachment URLs) plus per-project CSV. `POST /organizations/{slug}/imports`,
  `GET /organizations/{slug}/export`.

## Collaboration & ecosystem (M3)

Phase 3 makes TeamFlow a collaboration hub and opens it to the ecosystem:

- **Automation rules** — visual if-this-then-that rules: triggers (task
  created/updated, status changed, comment created, schedule), conditions and
  actions (assign, transition, comment, notify, webhook, add label, set
  priority). Starter templates and a per-rule execution log.
  `/organizations/{slug}/automations`, `.../templates`, `.../executions`;
  schedule triggers run hourly via Celery beat.
- **Releases & roadmap** — dated releases with scope progress plus a roadmap
  timeline grouping work by epic. `/projects/{id}/releases`,
  `/projects/{id}/roadmap`; `Task.release_id` scopes a task to a release.
- **Calendar** — month/week view of due dates with drag-to-reschedule
  (`GET /organizations/{slug}/calendar`, reschedule via `PATCH /tasks/{id}`).
- **Threaded comments, reactions & activity feed** — replies
  (`Comment.parent_id/root_id`), emoji reactions (curated set) and per-task/
  project activity feeds. `/tasks/{id}/comments`, `/comments/{id}/reactions`,
  `/tasks/{id}/activity`, `/projects/{id}/activity`.
- **Rich content** — the Markdown editor/renderer now supports GFM tables,
  images (including inline attachments via `attachment://<uuid>`) and keeps
  the Markdown source as the single representation.
- **Notification center upgrade** — notifications carry task/project pointers
  for grouping, plus per-project mutes checked at fan-out time.
  `/notifications/mutes`.
- **Integrations** — GitHub/GitLab/Bitbucket webhooks link commits/PRs by issue
  key and can auto-transition tasks; Slack/Teams receive event messages via an
  incoming webhook; Google Calendar subscribes to a tokenized ICS feed.
  `/organizations/{slug}/integrations`, public receivers
  `POST /integrations/{provider}/{id}`, `GET /integrations/google-calendar/{id}/feed.ics`.
- **API tokens, service accounts & OAuth apps** — personal access tokens
  (`tf_...`), scoped service accounts (hidden from rosters) and OAuth2
  client-credentials apps (`POST /oauth/token`), each with usage and optional
  per-minute rate limits. The MCP server accepts `TEAMFLOW_TOKEN`.
  `/organizations/{slug}/api-tokens`, `.../service-accounts`, `.../oauth-apps`.
- **Performance & scale proof** — cursor (keyset) pagination on
  `GET /organizations/{slug}/tasks/cursor`, query budgets enforced by tests,
  a k6 load-test script and documented targets in `docs/performance.md`.

## Enterprise & moat (M4)

Phase 4 makes TeamFlow enterprise-ready and opens the ecosystem:

- **SSO & provisioning** — generic OIDC enterprise SSO per workspace
  (discovery, PKCE, JWKS-verified ID tokens, auto-provisioning with a default
  role) and SCIM 2.0 user provisioning (`/api/v1/scim/v2/Users` +
  ServiceProviderConfig/Schemas) with per-org bearer tokens.
  `GET /auth/sso/{slug}/config|start|callback`, `GET/PUT
  /organizations/{slug}/sso`, `GET/POST/DELETE /organizations/{slug}/scim-tokens`.
- **MFA** — TOTP (RFC 6238, stdlib) with one-time recovery codes and a
  two-phase login challenge; enrollment/enable/disable endpoints and
  session revocation via logout-all.
  `GET /auth/mfa`, `POST /auth/mfa/setup|enable|disable|verify`.
- **Granular permissions** — custom roles (permission catalog:
  tasks.delete/tasks.manage/projects.manage/members.manage/org.manage/
  audit.view/integrations.manage), membership-bound custom roles, private
  projects with project-level membership (viewer/member/manager) and
  concealment (404) for non-members. `GET/POST /organizations/{slug}/roles`,
  `GET/POST/PATCH/DELETE /projects/{id}/members`.
- **Audit & compliance** — configurable per-org audit retention with a
  cleanup job, tamper-evident export (sha256 hash chain) as CSV or JSON, and
  compliance notes. `GET /organizations/{slug}/audit-logs/export`.
- **Dashboard builder** — configurable org/project dashboards with widget
  types (stats, status mix, per-member load, overdue list, activity) and a
  server-rendered data endpoint. `/organizations/{slug}/dashboards/*`.
- **Goals / OKRs** — objectives with due dates and statuses linked to
  epics/tasks with automatic progress roll-up. `/organizations/{slug}/goals`.
- **Forms / request intake** — public or private forms per project with typed
  fields and required-field validation; submissions create real tasks.
  `/projects/{id}/forms`, public `GET/POST /forms/{slug}`.
- **AI-native features (heuristic, no external provider)** — natural-language
  work breakdown that proposes an epic/story/task tree from a description and
  materializes it with hierarchy rules. `POST
  /organizations/{slug}/ai/breakdown` and `.../apply`.
- **Mobile & PWA** — installable manifest + service worker (offline app
  shell, push/notificationclick handlers) and web-push subscription
  management; `pywebpush` optional behind VAPID settings.
  `/notifications/push/*`.
- **i18n, RTL & Jalali** — full English/Persian UI across every page and
  component (modular dictionaries under `frontend/src/lib/locales`, guarded by
  key/placeholder parity tests), an in-app language switcher (header, auth and
  public forms), automatic RTL layout for `fa`, and locale-aware relative
  times plus Jalali dates via `Intl`; the locale persists per user
  (`PATCH /auth/me`) and follows the account onto new devices.
- **Theming** — org accent color applied live to the design tokens plus
  workspace-level audit retention settings (dark mode shipped in M1).
- **Plugin API & directory** — first-party directory with one-click install,
  per-plugin signing secrets, event subscriptions and HMAC webhook delivery
  via Celery. `/organizations/{slug}/plugins`, `.../plugins/directory`.
- **Expanded MCP coverage** — the MCP server now exposes 26 tools including
  sprints, releases, roadmap, calendar, automations, goals, forms and
  dashboards, and accepts `TEAMFLOW_TOKEN`.

## Key behaviors

- **Tenant isolation**: every tenant row carries `organization_id`; org-scoped
  access resolves membership server-side and returns 404 (not 403) for
  non-members so resource IDs cannot be probed across tenants.
- **Auth**: stateless short-lived access JWTs + stateful refresh tokens in
  Redis (rotation + reuse detection revokes the whole token family); password
  reset tokens are single-use and hashed at rest. Email OTP codes are
  HMAC-hashed with a wrong-attempt budget, and Google OAuth state/PKCE values
  plus the SPA hand-off code are single-use Redis keys; the ID token signature
  is verified against Google's JWKS. Logout revokes refresh tokens; access
  tokens expire within their short TTL by design. Accounts created via OTP or
  Google hold a random password hash until the user sets one via reset.
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

Two ways to run the production stack:

**Self-built** (`docker-compose.yml`): builds the API image locally and runs
db/redis/api/worker/beat behind the bundled nginx
(`docker compose up -d --build`, then `uv run alembic upgrade head`). Configure
`POSTGRES_*`, `SECRET_KEY`, `CORS_ORIGINS`, `S3_*`, `EMAIL_*` via the
environment (see `.env.example`).

**VPS via CI/CD** (`docker-compose.server.yml` → deployed as
`docker-compose.yml`): every push to `main` builds and publishes two GHCR
images — `ghcr.io/arsene-ir/teamflow` (API/worker/beat) and
`ghcr.io/arsene-ir/teamflow-web` (SPA + nginx) — then deploys them to
`mkhoddami-vps`. The server directory keeps exactly one file:

```text
/var/www/teamflow/docker-compose.yml
```

Everything else is handled by CI and Docker: images are pulled, migrations run
before rollout, the host nginx snippet (`deploy/nginx-flow.conf`) is installed
with a config test and automatic rollback, and the directory is pruned to the
compose file. The SPA is served at `https://arsene.ir/flow/`; the host nginx
routes `/flow/api`, `/flow/ws`, `/flow/admin` and `/teamflow-attachments`
directly to the API/MinIO containers.

Required repository settings (Settings → Secrets and variables → Actions):

| Kind | Name | Purpose |
| --- | --- | --- |
| secret | `MKHODDAMI_VPS_SSH_KEY` (or `DEPLOY_SSH_KEY`) | private key for the VPS |
| secret | `POSTGRES_PASSWORD` | must match the existing database volume |
| secret | `SECRET_KEY` | JWT signing key |
| secret | `S3_ACCESS_KEY`, `S3_SECRET_KEY` | MinIO/S3 credentials |
| variable | `DEPLOY_ENABLED=true` | enables the deploy job |
| variable | `MKHODDAMI_VPS_HOST` / `_USER` / `_PORT` | optional; default to `DEPLOY_HOST` / `DEPLOY_USER` / `DEPLOY_PORT` (`5.10.248.185` / `root` / `22`) |

`docker-compose.server.yml` interpolates everything from the deploy environment
— there is no `.env` on the server. The deploy script also runs
`alembic upgrade head`, so migrations are not a manual step on this path.

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

Agents and CI can skip passwords entirely with a personal access token
(created under **API access** in the web UI, M3 #24):

```env
TEAMFLOW_TOKEN=tf_...
TEAMFLOW_ORG=arsen
```

With `TEAMFLOW_TOKEN` the MCP server never calls `/auth/login`; the token's
scopes, expiry and rate limit apply. Email+password remains the fallback.

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

1. Register at `https://arsene.ir/flow/register` (password >= 10 characters;
   the form emails a 6-digit code that must be entered to finish).
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
