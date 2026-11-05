# TeamFlow — Major Business Context

> What the product does, for whom, and the exact business rules the code
> enforces. Derived from the implementation (`app/`, `frontend/`, `mcp_server/`)
> as of October 2026. When the code and this document disagree, the code wins.

## 1. What TeamFlow is

TeamFlow is a **multi-tenant project management and collaboration platform**
organized around kanban boards, a strict work-item hierarchy, and realtime
team communication. It is delivered as:

- a **REST API** (FastAPI) that owns all business rules and data,
- a **React SPA** for humans (board, tree, tasks, members, dashboard),
- a **server-rendered admin panel** for operators/superusers,
- an **MCP server** that lets coding agents drive the board as a normal user.

The core promise: teams create an organization ("workspace"), add projects,
break work down into `epic > story > task`, move cards through a fixed
four-column flow, discuss work with Markdown comments, and integrate with
external systems through signed webhooks. The platform is self-hostable and
multi-tenant: one deployment serves many isolated organizations.

### Primary personas

| Persona | Needs |
| --- | --- |
| Organization owner | Create/manage the workspace, members, roles, webhooks; delete org |
| Admin | Manage members, webhooks, projects, audit; everything a manager can do |
| Manager | Manage projects, labels, invitations; work on tasks |
| Member | Create/edit/move/assign tasks, comment, attach files, watch tasks |
| Superuser (operator) | Inspect and repair every table via the admin panel |
| Coding agent | Read the board, create/move/assign/comment via MCP tools |

## 2. Domain model

```text
Organization (tenant root)
 ├── Membership (user + role: owner/admin/manager/member)
 ├── Invitation (email-keyed, role, pending/accepted/declined/revoked)
 ├── Project (active/archived, owner)
 │    └── Task (status, priority, type, due date, assignee, creator, parent)
 │         ├── TaskLabelLink  → Label (org-scoped, name + color)
 │         ├── TaskWatcherLink → User
 │         ├── Comment (Markdown body, author)
 │         └── Attachment (metadata; bytes live in S3/MinIO)
 ├── Webhook → WebhookDelivery (persisted delivery attempts)
 ├── Notification (per-user inbox)
 ├── AuditLog (immutable action trail)
 └── IdempotencyKey (write-request replay store)
```

Every tenant-owned row carries `organization_id`. Tasks additionally carry
`project_id`. Foreign keys are `ON DELETE CASCADE` from org/project down, so
deleting an organization or project is a single database statement. A task's
`parent_id` uses `ON DELETE SET NULL`, so deleting a parent promotes its
children to top-level rather than deleting them.

## 3. Tenancy and identity

### 3.1 Tenant isolation (the central rule)

- An **Organization is the tenant root**. All access resolves through a
  membership: `(organization, membership)` is computed server-side from the
  authenticated user, never trusted from the client.
- Unknown resource IDs and **resources in other tenants both return 404**, not
  403. An outsider cannot even confirm that an organization slug, project, task,
  comment, label, attachment, or notification exists.
- Slug-addressed org routes require the slug + an active membership. UUID-addressed
  routes (`/tasks/{id}`, `/projects/{id}`, etc.) first load the row and then
  resolve the caller's membership in the row's organization. This closes IDOR
  (insecure direct object reference) probing.
- Deactivated memberships (`is_active = false`) are treated exactly like
  non-members: 404.

### 3.2 Roles

Ranks are ordered `member (1) < manager (2) < admin (3) < owner (4)`.
Role is **per organization**; a user's global flags (`is_superuser`) do not
grant in-org permissions.

| Action | member | manager | admin | owner |
| --- | --- | --- | --- | --- |
| View projects/tasks/members | yes | yes | yes | yes |
| Create/edit/move tasks, comment, attach, watch | yes | yes | yes | yes |
| Delete a task | only if creator | yes | yes | yes |
| Create/update/delete projects | no | yes | yes | yes |
| Create/update/delete labels | no | yes | yes | yes |
| Create/revoke invitations | no | yes | yes (may invite admins) | yes |
| Directly add an existing user as member | no | no | yes | yes |
| Change member roles | no | outrank target + new role | same | same |
| Remove members | self-leave only | outrank target | same | same |
| Update organization | no | no | yes | yes |
| Delete organization | no | no | no | yes |
| Manage webhooks (admin/owner) | no | no | yes | yes |
| View audit log | no | no | yes | yes |

Additional guardrails:

- The **owner cannot be removed, demoted, or re-roled**, and ownership transfer
  is not supported. Change/remove of any member requires the actor to strictly
  outrank both the target's current role and the role being granted.
- No one can change their own role via the role endpoint.

## 4. Authentication and sessions

All credential types converge on the same token lifecycle.

### 4.1 Token model

- **Access token**: stateless JWT, default TTL 30 minutes, sent as
  `Authorization: Bearer <token>`. Not revocable individually by design;
  it expires within its short TTL.
- **Refresh token**: JWT with a `jti` that is **stateful in Redis** (TTL 14
  days). Every refresh **rotates** the token: the old `jti` is revoked and a new
  one is whitelisted.
- **Reuse detection**: presenting a `jti` that is no longer whitelisted revokes
  the user's **entire refresh-token family** (log out everywhere on suspected
  theft). Logout revokes exactly the presented token; `logout-all` sweeps all.
- Passwords are bcrypt-hashed; CPU-bound hashing runs off the event loop.
  Minimum password length is 10 characters (max 128).
- Accounts created without a password (email OTP or Google) receive a random
  unusable hash and can set a real password later via the reset flow.

### 4.2 Sign-in and sign-up options

| Flow | Behavior |
| --- | --- |
| **Register** | `POST /auth/register` requires the 6-digit `code` emailed by `POST /auth/otp/request`; without a valid, unredeemed code the account is not created. Codes are single-use and the attempt budget is capped. |
| **Password login** | Form-encoded (OAuth2 password flow) so Swagger's Authorize button works. Per-email and per-IP rate limits are checked before password hashing. Failures are audited and return a deliberately vague "Incorrect email or password". |
| **Passwordless email OTP** | `POST /auth/otp/request` emails a 6-digit code; `POST /auth/otp/verify` exchanges it for tokens. The first successful verification creates the account. Codes are HMAC-peppered (not plain-hashed) at rest, expire in 10 minutes, burn after 5 wrong attempts, and are single-use. |
| **Google sign-in** | Authorization code + PKCE. `state` and verifier are stored in Redis and are single-use; the OIDC ID token is verified against Google's JWKS; email must be present and verified. The stable Google `sub` wins over email when linking, so an email change cannot silently rebind an account. The browser receives a 120-second **single-use hand-off code** that the SPA exchanges for tokens — tokens never appear in a redirect URL. |
| **Password reset** | `POST /auth/forgot-password` always returns the same success response (no user enumeration) and emails a link if the account exists. Tokens are single-use (`GETDEL`), SHA-256-hashed at rest, valid 30 minutes; a successful reset revokes all refresh tokens. |

### 4.3 Native session behavior (SPA/MCP)

- The SPA stores tokens in `localStorage`, bootstraps via `GET /auth/me`, and on
  any 401 performs a single-flight `POST /auth/refresh` then retries the request
  once. Failed refresh clears tokens and emits a global session-expired event.
- The MCP server logs in once, rotates its refresh token automatically, and
  re-authenticates if revoked.

### 4.4 Rate limiting

Redis-backed sliding-window limits (fail-open if Redis is down):

| Scope | Default limit |
| --- | --- |
| Login | 5/min per **IP** and 5/min per **email** |
| Register | 3/hour per IP |
| Password reset (request + reset) | 3/hour per IP |
| OTP request | 5/hour per email **and** 20/hour per IP (NAT-friendly) |
| OTP verify | 5/min per IP |
| OAuth start | 5/min per IP |

## 5. Workspaces, members, and invitations

### 5.1 Organizations

- Creating an org atomically creates the creator as `owner` membership (one
  transaction), and audits `organization.created`.
- Slug uniqueness is enforced; orgs can be deactivated (`is_active`) and renamed
  by admins. Only the owner can delete one.
- Any member can list the organizations they belong to, with their role.

### 5.2 Invitations

- Invitations are **email-keyed**: the row stores the target email (lowercased)
  and the role; only a logged-in user with that exact email can accept.
- Managers+ can invite; only admins may invite other admins; nobody can invite
  an owner. A pending invitation per email per org is unique; inviting an
  existing member conflicts.
- If the invited email already has an account, an in-app notification is created
  in the same transaction. In all cases an invitation email is queued via Celery.
- Accepting creates the membership, marks the invitation `accepted`, audits, and
  notifies; declining marks it `declined`; managers+ can `revoke` a pending
  invitation. Accepting a stale invite for a deactivated org fails.
- A user views their own pending invitations across all workspaces.

## 6. Projects

- A project belongs to exactly one organization, has `active` or `archived`
  status and an owner (the creator).
- Create/update/delete require **manager or above**; members can still see and
  work in every project of their org (there is no private-project concept).
- Listing supports status filtering and pagination; archived projects are hidden
  by default.
- Project deletion cascades to all its tasks (and their comments, attachments,
  label links, watcher links via the task FKs).

## 7. Tasks: the core work item

### 7.1 Fields

`title` (1–255), Markdown `description` (≤20k), `status`, `priority`
(`low|medium|high|urgent`, default medium), `type` (`epic|story|task`, default
task), `due_date`, `assignee` (single user), `created_by`, `parent`, labels
(≤20), watchers, `completed_at`.

### 7.2 Status lifecycle — fixed, step-wise, mostly reversible

```text
todo ⇄ in_progress ⇄ in_review ⇄ done
                 ↑__________________|   (done reopens to in_progress)
```

- Allowed transitions: `todo → in_progress`; `in_progress → todo | in_review`;
  `in_review → in_progress | done`; `done → in_progress`.
- Any other move is rejected with 422. A same-to-same move is a no-op.
- There is **no back-step from in_review to todo and no jump from todo to done**
  — the workflow must be walked one column at a time (agents must call move
  twice for todo → done).
- Moving to `done` stamps `completed_at`; leaving `done` clears it. Reopening is
  the supported mechanism for a wrongly completed task.
- The frontend drag-and-drop only checks "different column"; the legal
  transition set is enforced by the API and surfaced as a toast on rejection.
- `POST /tasks/{id}/move` is the explicit transition endpoint; `PATCH /tasks/{id}`
  accepts `status` through the same validation.

### 7.3 Hierarchy — `epic > story > task`

- Each type has a depth level: epic = 0, story = 1, task = 2.
- A parent must (a) belong to the **same project**, (b) be at a **strictly
  higher level**, and (c) not be the task itself or any of its descendants.
- Consequences: a story may nest under an epic; a task may nest directly under
  an epic or under a story; an epic can never have a parent; a story cannot be
  parented by a task. Because parents must be strictly higher, **cycles are
  structurally impossible** (plus a defensive walk-up check reports a cycle if
  data somehow contains one).
- Changing a task's `type` re-validates both ends: the new type must still be
  lower-level than its parent and higher-level than all existing children.
- Deleting a parent **does not delete children** (`ON DELETE SET NULL`); they
  become top-level tasks.
- The tree endpoint returns the whole project as nested nodes. Each node
  reports **direct** child counts (`child_count`, `done_child_count`) used for
  progress bars; responses and the UI show `done/total` progress.
- A project fetch is bounded and grouped in memory; depth is bounded by the type
  rules. Tasks whose parent is outside the fetched set appear as roots.

### 7.4 Assignment and watchers

- The assignee must be an **active member of the task's organization**; setting
  an outsider is rejected.
- The **creator and assignee automatically watch** a new task. Any assignment
  change (reassignment) adds the new assignee to watchers.
- Any member who can see the task may watch/unwatch themselves via
  `POST|DELETE /tasks/{id}/watchers/me`.
- Watchers (and the assignee) receive comment notifications; watchers receive
  the daily due-soon reminder.

### 7.5 Permissions on tasks

- **Any member may create, edit, move, assign, label, comment, attach, and
  watch** tasks — the platform is collaboration-first.
- Only managers+ **or the task's creator** may delete a task. Deletion audits the
  title, removes the row (children survive), publishes a realtime `task.deleted`
  event, and invalidates the dashboard cache.

### 7.6 Listing, filtering, search

`GET /organizations/{slug}/tasks` supports: project, assignee (`unassigned`),
label, one or more statuses/priorities/types, parent or roots-only, free-text
search on title/description (ILIKE, ≤100 chars), due-before/after, overdue-only,
sort whitelist (`created_at`, `updated_at`, `title`, `priority`, `status`,
`due_date`, `type`; prefix `-` for descending, unknown fields fall back to
newest), and offset pagination (default 50, max 100 per page).

## 8. Labels

- Org-scoped tags with a name (unique per org) and a hex color.
- Manager+ manages labels; any member can attach up to 20 labels to a task.
- Labels are validated to belong to the task's organization before linking.
- `PATCH` with `label_ids` **replaces the entire set** (empty list clears all).

## 9. Comments and mentions

- Flat (non-threaded) Markdown comments on a task, authored by a member.
- **Mentions are plain email addresses in the body** (regex-extracted), not a
  UI picker. A mention notifies the matched existing user.
- Notification fan-out: explicit mentioned users get `mention`; watchers +
  assignee get `comment_created`, minus the actor and anyone already mentioned.
- Editing/deleting a comment is allowed for its author or manager+.
- Deleting a comment is audited; creating one publishes a realtime
  `comment.created` event and dispatches the `comment.created` webhook.

## 10. Attachments

Metadata lives in PostgreSQL; file bytes go **directly to S3/MinIO** — the API
never proxies file content.

Flow:

1. Client declares filename, content type, and size →
   `POST /tasks/{id}/attachments` validates and creates a `pending` row, and
   returns a **short-lived presigned PUT URL** (default 15 min).
2. Client uploads the bytes straight to object storage.
3. Client calls `POST /attachments/{id}/confirm`; the server performs a HEAD on
   the object and flips the row to `available` (or `failed` if the object is
   missing). Confirming an already-available attachment is idempotent.
4. Downloads: `POST /attachments/{id}/download-url` returns a presigned GET URL,
   and only for `available` attachments.

| Rule | Value |
| --- | --- |
| Max size | 10 MB |
| Content types | allowlist (images, text/CSV/Markdown, PDF, JSON, ZIP, MS Office) |
| Storage key | server-generated: `orgs/{org}/tasks/{task}/<uuid>.<ext>` — no client path control |
| Filename | sanitized to basename, unsafe chars replaced, extension length-capped |
| Pending cleanup | objects/rows older than 24h are removed by the cleanup job |
| Delete | removes the storage object and the row; audited |

Any member with task access can upload, confirm, download, and delete
attachments (authorization is tenant-scoped, not role-gated).

## 11. Notifications

Persisted, per-user inbox entries (never email by default). Types actually
emitted by the system:

| Type | Trigger | Recipient |
| --- | --- | --- |
| `task_assigned` | Task created with an assignee, or assignee changed | Assignee (not the actor) |
| `comment_created` | New comment | Watchers + assignee (minus actor/mentions) |
| `mention` | `@email` found in a comment | Mentioned registered user (not the actor) |
| `invitation` | Invitation created for an existing account | Invitee |
| `member_joined` | Invitation accepted | The joining user ("You joined …") |
| `task_due_soon` | Daily Celery beat job | Watchers of tasks due within 24h, not done |

- Users list their notifications (optionally unread-only, paginated), fetch an
  unread count, mark one read, or mark all read. Other users' notification IDs
  return 404.
- New notifications are also pushed in realtime to the user's WebSocket room.
- Note: `task_completed` exists as a notification constant but is never emitted;
  the `task_assigned` email template exists but is never enqueued (in-app only).

## 12. Realtime collaboration (WebSockets)

- Endpoint: `GET /ws/projects/{project_id}?token=<access JWT>`. The project must
  exist and the user must be an active member; otherwise the socket closes with
  4401 (bad token) or 4404 (not found/no access).
- On connect, the client joins two rooms: the project room and a personal user
  room (for notifications).
- Publishing goes through **Redis pub/sub** (`teamflow:ws`); one listener per
  API worker fans messages out to its local sockets. Any worker (or the Celery
  workers) can publish, which makes the design multi-worker-safe.
- Client messages: only `{"type":"ping"}` → `pong`; anything else gets an error
  frame. Malformed JSON never crashes the socket.
- Board events emitted: `task.created`, `task.updated`, `task.deleted`,
  `comment.created` (project room) and `notification` (user room). The SPA
  treats any `task.*`/`comment.*` event as a change signal and invalidates the
  relevant React Query caches instead of applying patches.
- The SPA pings every 25s, reconnects with exponential backoff
  (1s → 30s cap), and treats 4401 as a session expiry; 4404 as fatal.

## 13. Webhooks (outbound integration)

- Managed by **admin/owner** only, per organization. Each webhook has a URL, an
  event subscription list, an active flag, and an auto-generated signing secret
  (shown once at creation, never rendered again).
- Supported event names: `task.created`, `task.updated`, `task.completed`,
  `comment.created`, `member.joined` (**advertised; not currently dispatched**).
- Delivery pipeline: when a business event occurs, one **persisted
  `WebhookDelivery` row per matching active webhook** is committed, then a
  Celery task is enqueued on the `webhooks` queue. Rows are durable before
  enqueue, so a broker outage leaves them `pending` for the sweeper.
- Request shape: JSON envelope `{id, event, organization_id, created_at, data}`
  with headers:
  - `X-TeamFlow-Event`
  - `X-TeamFlow-Delivery` (delivery UUID, for receiver-side dedupe)
  - `X-TeamFlow-Timestamp`
  - `X-TeamFlow-Signature` = HMAC-SHA256 over `{timestamp}.{raw_body}`, keyed by
    the webhook secret.
- Retry policy: up to 5 attempts with exponential backoff
  `min(5·2^attempt, 300)` seconds. `2xx` succeeds; `4xx` (except `408`/`429`) is
  **permanent failure** and is not retried; transport errors and `5xx`/`408`/`429`
  are retried. Attempts, HTTP status, last error, and delivered-at are persisted.
- An already-successful delivery short-circuits, so duplicate enqueues never
  double-deliver. A disabled/deleted webhook fails pending deliveries.
- The cleanup job re-enqueues deliveries stranded `pending` for 10+ minutes
  (broker outage recovery).

## 14. Background jobs (Celery + Beat)

Queues: `default`, `emails`, `webhooks` (independently scalable).

| Job | Schedule | Behavior |
| --- | --- | --- |
| `send_email` | on demand | Console (dev) or SMTP; 3 retries, exponential backoff + jitter. Templates: `password_reset`, `otp_code`, `organization_invite` (plus an unused `task_assigned`). |
| `deliver_webhook` | on demand | See §13; synchronous psycopg sessions in workers (no async loop). |
| `cleanup_expired_data` | every 6h | Purges idempotency keys past TTL (24h), deletes stale `pending` attachments (24h+) and their objects, re-enqueues stranded webhook deliveries. |
| `warm_dashboard_caches` | hourly | Precomputes dashboard stats for every active org into Redis. |
| `notify_due_tasks` | daily | Creates `task_due_soon` notifications for watchers of non-done tasks due within 24h. |

## 15. Dashboard and reporting

Organization-level counts computed entirely in SQL (no task rows loaded into
Python): total/active projects, total/completed/overdue/unassigned tasks,
tasks by status, active members, and open tasks per member (top 20).

- Overdue = `due_date < now` and status ≠ done; unassigned = no assignee and not
  done.
- Results are cached in Redis for 60 seconds and **explicitly invalidated** by
  task/project mutations (TTL is a safety net only); the hourly warm job keeps
  first views fast.
- This is counts-only reporting — there are no burndown/velocity/time-tracking
  reports in the product.

## 16. Write safety: idempotency

Clients may send an `Idempotency-Key` header (8–128 chars, `A-Za-z0-9_.-`) on
`POST`/`PATCH`/`DELETE`:

- The first request **claims** the key with an atomic INSERT (unique constraint
  is the race arbiter) and proceeds.
- A concurrent duplicate while the first is in flight (younger than 30s) gets
  **409** with `Retry-After: 1`.
- A completed request is **replayed** with the stored status/body for up to 24h,
  marked `Idempotency-Replayed: true`.
- Reusing the same key with a **different request body** returns 422.
- `5xx` responses mark the record `failed`, so the client may safely retry with
  the same key.
- Identity is the JWT subject, falling back to client IP for anonymous requests.
  Expired records are purged by the cleanup job.

## 17. Audit trail

Every important action is appended to `audit_logs` **inside the caller's
transaction** (action and audit row commit atomically). Recorded fields: actor,
organization, action, target type/id, IP, and small sanitized metadata.
Passwords, tokens, and secrets are never recorded.

Audited action families: auth (register, login, failed login, OTP requested/
failed, OTP login, Google linked/login, password reset requested/done),
organization/member/invitation changes, project/task CRUD, task assignment,
comments, attachments, webhooks, and all admin-panel operations (including admin
login/logout/failures). Readable by admin/owner via the API and the admin panel;
admin-panel writes are captured by a dedicated audit backend with redaction.

## 18. Admin panel (operations)

A sqladmin panel mounted at `/admin`, session-cookie authenticated and
**superuser-only** (API registration never grants the flag; the first superuser
is bootstrapped by a script).

- Live dashboard: user/org/project/task counts, status breakdown, overdue tasks,
  recent users/orgs/tasks, recent audit activity.
- CRUD for every table with search, filters, sorting, pagination, CSV export;
  read-only views for audit logs, webhook deliveries, and idempotency keys.
- User form edits passwords write-only (bcrypt-hashed server-side, never
  audited); webhook secrets are never rendered back.
- Guards: admins cannot deactivate/demote/delete themselves; the last superuser
  cannot be deleted.
- More restrictive session auth than the API: same-site signed cookie, `Secure`
  in production, timing-equalized failures, per-(IP,email) login rate limit.

## 19. Agent integration (MCP)

`mcp_server/` is a standalone MCP server that is a **pure REST API client** (no
database access), so it works against localhost or the deployed instance. It
runs over stdio (agent-spawned) or streamable HTTP (the always-on `mcp` container
in the VPS stack, exposed at `/flow/mcp`). In HTTP mode each caller sends their
own personal access token, which is forwarded to the API per request; the API
still enforces every authorization and tenancy rule above. Tools: `whoami`, `list_organizations`, `list_projects`,
`get_board`, `list_tasks`, `get_task`, `get_task_tree`, `create_task`,
`update_task`, `move_task`, `delete_task`, `my_work`, `add_comment`,
`list_comments`, `list_members`, `list_labels`, `create_label`, `get_dashboard`;
resources `teamflow://me`, org dashboard, project board; prompts `daily_standup`
and `board_triage`.

Credentials are resolved **per project** (shared `~/.config/teamflow/.env`
defaults + project `.env` + process env), so one agent config serves many
repositories with different identities and no secrets in the config file.

## 20. Frontend (React SPA)

Vite + TypeScript + Tailwind + TanStack Query. Covered routes: login,
OTP login, register (code-verified), forgot/reset password, OAuth callback,
organizations list/create, invitations inbox, org dashboard, projects grid,
project page (kanban + hierarchy tree), cross-project tasks table, members,
labels, webhooks, audit, notifications, settings, 404.

Notable behavior:

- **Board**: four fixed columns with counts; native drag-and-drop calling the
  move endpoint (illegal moves are rejected by the API and toasted); a
  "Subtasks" toggle filters to top-level-only; container cards and tree nodes
  show `done/total` progress; card badges show type, priority, up to 3 labels,
  parent breadcrumb, assignee, and overdue due dates.
- **Hierarchy view**: collapsible epic > story > task tree with per-node
  progress and inline child creation.
- **Task drawer**: inline edits for all fields; status dropdown limited to legal
  transitions; parent breadcrumb; subtask list; watcher avatars and
  watch/unwatch; label picker; delete gated to managers+ or the creator;
  attachments and a Markdown comment editor with Write/Preview and a toolbar.
- **Tasks table**: debounced search, faceted filters (project, type, priority,
  multi-status, assignee, overdue, top-level), sort, pagination.
- **Role-aware UI**: Webhooks/Audit nav hidden unless admin/owner; project,
  label, and invite actions hidden unless manager+. UI gates are convenience
  only — the API re-enforces every rule.
- **Notification bell** polls every 30s; notifications are user-scoped across
  workspaces and labeled when they belong to another workspace.

## 21. Cross-cutting engineering guarantees

- **Layering**: routers handle HTTP; services own business rules,
  authorization, audit, and transactions; repositories own all SQL. Transaction
  boundaries are in services.
- **No data leakage**: API responses use Pydantic schemas, never table models;
  `hashed_password`, webhook secrets, and storage keys never leave the server.
- **Observability**: request IDs on every request, structured access logs
  (optional JSON), `/api/v1/health/live` and `/health/ready` (DB + Redis).
- **Failure isolation**: realtime publish, webhook dispatch, and dashboard cache
  failures are logged, never allowed to fail the business operation; rate
  limiting fails open so a Redis outage cannot brick auth.
- **Deployment**: Docker Compose (API, worker, beat, Postgres 16, Redis, nginx,
  optional MinIO); CI builds/publishes images and runs Alembic migrations before
  rollout. A seeding script can load ~1M realistic rows for load testing.

## 22. Explicit non-goals / known gaps

To describe the product exactly, these are **not** in the current business
scope (verified absent):

- No sprints/backlog, story points, estimates, velocity/burndown reports,
  Gantt/calendar/roadmap, milestones/releases, or time tracking.
- No custom workflows, statuses, fields, or multiple boards; the four-status
  flow is fixed.
- No task dependencies/links, subtask checklists, multiple assignees, recurring
  tasks, task templates, bulk operations, or clone/duplicate.
- No human-readable issue keys (tasks are UUID-addressed), no global full-text
  search (ILIKE on title/description only), no saved filters.
- No comment threads/reactions/rich text beyond Markdown, no mention
  autocomplete (mentions are typed emails).
- No SSO/SAML/SCIM, MFA, API keys/personal access tokens (agents use
  email+password), custom roles, or per-project permissions — project-scoped
  membership is planned as module M6 (§24).
- No billing/quota, mobile apps, push notifications, i18n/RTL, or dark mode.
- Implementation quirks: the `member.joined` webhook and `task.completed`
  notification are declared but never emitted; the `task_assigned` email
  template is defined but never enqueued; `task.completed` webhooks fire from
  the update path (including the move endpoint, which delegates to update).

## 23. End-to-end examples

**Creating and completing work**

1. Manager creates a project; members see it in the org list.
2. A member creates an epic, then a story with `parent_id = epic`, then a task
   under the story. Each creation validates the hierarchy and assignment.
3. The creator and assignee auto-watch; the assignee is notified in-app.
4. The assignee moves the task `todo → in_progress`; comments notify watchers;
   a teammate is mentioned by email.
5. The assignee moves it to `in_review`; a reviewer moves it to `done`.
   `completed_at` is stamped, `task.completed` is dispatched to webhooks, the
   board updates over WebSockets, and the dashboard cache is invalidated.
6. If completed by mistake, it reopens to `in_progress`.

**Inviting a teammate**

1. A manager invites `alice@example.com` as `member`; the invite email is queued.
2. If Alice already has an account she also gets an in-app invitation.
3. Alice accepts; she becomes a member, the invitation is marked accepted, the
   action is audited, and her own "joined" notification is created.
4. Alice now sees only the organizations she belongs to; probing any other org,
   project, or task ID returns 404.

**Uploading a file**

1. A member requests an upload intent for `design.pdf` (≤10 MB, allowed type).
2. The server returns a 15-minute presigned PUT URL and creates a `pending` row.
3. The client uploads directly to MinIO/S3.
4. Confirmation HEADs the object and flips the row to `available`; the attachment
   is now downloadable via a short-lived presigned GET URL.
5. A pending row whose object never arrived is cleaned up after 24 hours.

## 24. Module M6 — project-scoped access, workspace activity log, AI work breakdown

> Status: **planned / not implemented**. Nothing in this section exists in the
> codebase today; it is the specification for the M6 module. When it ships, the
> affected sections above (access resolution in §3, members in §5, realtime in
> §12, audit in §17, non-goals in §22) must be updated to match.

### 24.1 Add people to a project, not the whole workspace

Goal: let a workspace owner/admin bring a collaborator into **one project**
without granting visibility into every other project in the workspace.

- Add a **project membership** entity (`project_members`: `project_id`,
  `user_id`, `role`, `added_by_id`, timestamps) alongside the workspace
  (organization) membership. A user can be in a project without being a
  workspace member, and a workspace member can be in only some projects.
- Two ways to add a person: pick an existing workspace member, or invite an
  email. Invitations gain a **scope** (`workspace` or `project`); accepting a
  project invitation creates the project membership only.
- Project roles (working names):
  - `project_lead` — manages the project's details, members, and labels for
    that project.
  - `project_member` — creates/edits/moves tasks, comments, attaches, watches.
  These are scoped to the project and **never** grant workspace-level powers.
- Access resolution change: a project/task is visible when the caller is a
  workspace manager+ (current behavior for their org) **or** a member of that
  specific project. Non-members still receive **404**, preserving the IDOR rule
  (§3.1).
- Workspace-level actions stay reserved to workspace roles exactly as in §3.2
  (workspace invites/roles, webhooks, audit, org settings, member management)
  and are never unlocked by a project role.
- Visibility ripple: a project-only member sees only their project in project
  lists, task queries, dashboard counts, search, and realtime rooms. Removal
  revokes task/board visibility immediately; their comments/attachments remain
  attributed to them.
- Implementation touchpoints: extend the `(organization, membership)` resolver
  in `app/api/deps.py` with a project-membership check; extend invitations and
  audit; project-member notifications/mentions continue to work.
- Open decisions: whether `project_lead` may create projects or invite
  workspace members; whether the workspace dashboard counts project-only
  members; how seat/quota (if introduced) counts them; and what happens to a
  project membership when the owning workspace membership is removed.

### 24.2 Workspace activity log

Goal: a chronological, human-readable feed of what happened in the workspace,
visible to its members — today's `audit_logs` are admin/owner-only (§17).

- Built from the existing audit trail (`audit_logs`) plus realtime project
  events, filtered by the caller's visibility: workspace members see
  workspace-level activity; project-only members see activity in their projects
  only.
- Each entry shows actor, action, human summary, target (project/task/member/
  label), timestamp, and a link to the affected item.
- Filterable by project, actor, action family, and date; paginated; newest
  first.
- Delivered live over the existing WebSocket fan-out (a new `activity` event
  alongside the events in §12) and persisted for history.
- Distinct from the audit log on purpose: the **activity log is a
  collaboration feature** (readable, summarized, in-product); the **audit log
  remains the compliance-grade, immutable, admin-only record** with the IP and
  sanitized metadata.
- Retention follows the audit-log retention policy; entries are append-only.

### 24.3 AI work breakdown from a simple description

Goal: a user describes a project or a piece of work in plain language and the
system drafts the structure — milestones, epics, stories, and tasks — for
review. This is the "context intake" flow.

- Entry points: during project creation ("describe the project") and a
  "Generate work from description" action on an existing project.
- Input context: goal, scope, deadline, team, constraints, links, and
  optionally the project's existing tasks. A per-project **context summary**
  ("what is this project about?") is stored, editable, and reused for later
  generations and agent (MCP) calls.
- Processing: a server-side LLM call (API key from configuration; no
  client-side keys) turns the description into a **proposal**, not committed
  data — a structured outline of milestones/epics/stories/tasks with suggested
  priority, due hints, and dependencies noted as text.
- Milestones: if the milestone concept is not modeled as its own entity, the
  proposal maps top-level milestones onto epics (or introduces a milestone
  entity as part of this module); either way the generated shape must respect
  the existing `epic > story > task` level rules from §7.3.
- Review is mandatory: the response is a preview tree the user can edit,
  rename, deselect, and reorder. Rows are created only on explicit
  confirmation, through the **same service-layer validation as manual
  creation** (hierarchy levels, active-member assignees, label ownership,
  tenant checks).
- Idempotency: the confirm call accepts an `Idempotency-Key` (existing
  middleware, §16) so a double-click cannot create the plan twice.
- Provenance: generated rows are flagged (`created_by_ai`, source request id);
  the generation and confirmation are audited, appear in the activity log
  (§24.2), and publish realtime events like any other creation.
- Guardrails: model output is schema-validated before display; unknown users,
  labels, or projects are rejected; the feature is permission-gated (workspace
  manager+ or project lead); token/usage limits and a kill switch are
  configuration; prompts include only data the caller is allowed to see.
- Example: "We are building a payments API with checkout, refunds, and a
  admin dashboard; launch in 6 weeks with two backend engineers" produces a
  draft epic per milestone, stories under each, and granular tasks — all
  editable before anything is saved.

### 24.4 M6 end-to-end example

1. A workspace owner invites `contractor@example.com` to the **Payments API
   project only** as `project_member`; the invite email is queued and the
   workspace is unaffected.
2. The contractor accepts, sees only that project, and creates/edit tasks in it.
3. A manager enters a short project description and asks for a draft plan; the
   AI proposes milestones/epics/stories/tasks, the manager edits and confirms,
   and the rows are created with `created_by_ai` provenance.
4. Every action lands in the workspace activity log and (for the contractor)
   in the project's realtime feed; the admin-only audit log still records the
   full compliance trail.
