# 01 — Project Overview

## What TeamFlow is

TeamFlow is a **multi-tenant project management and collaboration API** — think a
simplified Linear (projects/tasks), plus Slack-ish notifications, plus GitHub-ish
webhooks. It is a **modular monolith**: one FastAPI application, one database,
one Redis, one Celery worker pool.

The point of the project (from your perspective) is not the product. It is that
every piece of the FastAPI ecosystem is present and wired together the way a
production system would wire it:

```
FastAPI  ─┬─ PostgreSQL   (SQLModel + Alembic)
          ├─ Redis        (token store, rate limits, WS pub/sub, dashboard cache)
          ├─ Celery       (email, webhooks, cleanup, scheduled jobs)
          ├─ WebSockets   (project realtime, multi-worker via Redis)
          ├─ MinIO/S3     (presigned file uploads)
          └─ HTTPX        (webhook delivery, connection-pooled)
```

## Domain model (16 tables)

```
User ──< Membership >── Organization ──< Project ──< Task ──< Comment
                 │                        │             │
                 ├──< Invitation          └──< Label    ├──< Attachment
                 ├──< Webhook ──< WebhookDelivery        ├──< TaskLabelLink (M2M)
                 └──< AuditLog                           └──< TaskWatcherLink (M2M)
Notification (per user)          IdempotencyKey (per request)
```

Mapped to files in `app/models/`:

| Table | File | Notes |
| --- | --- | --- |
| `users` | `app/models/user.py` | email unique, bcrypt hash, soft flags |
| `organizations` | `app/models/organization.py` | tenant root, slug unique |
| `memberships` | `app/models/organization.py` | user↔org + per-org role |
| `invitations` | `app/models/organization.py` | email-keyed, status machine |
| `projects` | `app/models/project.py` | belongs to org |
| `tasks` | `app/models/task.py` | status/priority, assignee, due date |
| `task_labels` / `task_watchers` | `app/models/task.py` | M2M link tables |
| `labels` | `app/models/label.py` | unique per org |
| `comments` | `app/models/comment.py` | @mentions supported |
| `attachments` | `app/models/attachment.py` | metadata only, bytes in S3 |
| `notifications` | `app/models/notification.py` | per-user inbox |
| `webhooks` / `webhook_deliveries` | `app/models/webhook.py` | HMAC-signed delivery |
| `audit_logs` | `app/models/audit.py` | immutable business trail |
| `idempotency_keys` | `app/models/idempotency.py` | request replay store |

## Product surfaces (what you can actually do over HTTP)

- **Auth** (`app/api/routes/auth.py`): register, login (OAuth2 form), refresh with
  rotation, logout, logout-all, profile, forgot/reset password.
- **Organizations** (`organizations.py`, `invitations.py`): CRUD, role changes,
  membership removal, invitations (create/list/accept/decline/revoke).
- **Projects** (`projects.py`): CRUD, archive, list per org.
- **Tasks** (`tasks.py`): CRUD, explicit status-transition endpoint, watchers,
  filtered/sorted/paginated listing (`?status=&priority=&search=&sort=-created_at&page/limit`).
- **Labels** (`labels.py`): org-scoped CRUD + attach/detach on tasks.
- **Comments** (`comments.py`): CRUD, mentions produce notifications.
- **Attachments** (`attachments.py`): upload intent (presigned PUT), confirm,
  download URL (presigned GET), delete.
- **Notifications** (`notifications.py`): inbox, unread count, mark read/all.
- **Webhooks** (`webhooks.py`): CRUD, delivery history.
- **Audit** (`audit.py`) + **Dashboard** (`dashboard.py`): admin trail, org stats.
- **Realtime** (`app/websocket/router.py`): `/ws/projects/{id}` events.
- **Ops** (`health.py`): `/health/live`, `/health/ready` (checks DB + Redis).

## How the non-obvious parts work

| Concern | Implementation | File |
| --- | --- | --- |
| Tenant isolation | every query filtered by `organization_id` from *server-side* membership | `app/api/deps.py`, services |
| Auth tokens | stateless access JWT + stateful refresh JTI whitelist in Redis | `app/services/auth.py`, `token_store.py` |
| Idempotency | ASGI middleware, DB claim row before the handler runs | `app/core/idempotency.py` |
| Task transitions | whitelist map, illegal moves → 422 | `app/services/tasks.py` |
| Webhook delivery | DB row per delivery → Celery task → signed HTTPX POST | `app/services/events.py`, `app/workers/tasks.py` |
| Realtime fan-out | publish to Redis channel; each worker forwards to its sockets | `app/websocket/manager.py`, `router.py` |
| Rate limiting | Redis sorted-set sliding window, fail-open | `app/core/rate_limit.py` |
| Dashboard | SQL aggregation + 60s Redis cache with explicit invalidation | `app/services/dashboard.py`, `cache.py` |

## Deliberate non-features (be honest about scope)

TeamFlow does **not** have:

- `BackgroundTasks` — asynchronous work goes to Celery instead
  (see `fastapi/11-background-tasks.md` for why that is the right call here).
- Cookie/session auth, CSRF — it is a token API consumed by SPAs/mobile.
- Server-side multipart uploads — bytes go directly to S3 via presigned URLs.
- Microservices, event sourcing, message buses — a modular monolith is the
  deliberate choice (see `architecture/07-design-decisions.md`).

## Review questions

1. Why is `Organization` called the "tenant root"?
2. Which table would you query to answer "can user X see task Y" and why?
3. Why are bytes not stored in Postgres for attachments?
4. Which parts of the system would keep working if Redis died? Which would not?
