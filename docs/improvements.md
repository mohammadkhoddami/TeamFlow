# TeamFlow — Competitive Analysis & Improvement Plan

> Comparing TeamFlow against **Jira** (Atlassian) and **Mizito** (میزیتو), with a
> prioritized feature list to close the gap and win.
>
> Research date: **October 2026**. Competitor capabilities change frequently —
> verify before making roadmap commitments.

## 1. Scope & method

- **TeamFlow baseline** was inventoried directly from this repository
  (models, routers, services, workers, frontend, MCP server, migrations). Only
  features with code evidence are listed as present; everything else is marked
  as a gap.
- **Jira** was assessed from Atlassian's own feature/release pages and 2026
  reviews (Gartner, Capterra, Software Advice, Atlassian Community).
- **Mizito** was assessed from mizito.ir, help.mizito.ir, its pricing page, app
  store listings, and a public reverse-engineering project for its API.

## 2. Executive summary

TeamFlow today is a **focused, well-engineered multi-tenant kanban + hierarchy
tool**: it does project/task basics with unusually strong foundations (auth,
tenancy, idempotency, webhooks, realtime, admin) plus a first-party agent
interface (MCP). It is *not* an agile planning suite.

- **vs Jira** — TeamFlow wins on simplicity, self-hosting, security engineering
  and cost; it loses on the entire agile layer (sprints, backlog, story points,
  reports, workflow engine, custom fields, dependencies, time tracking,
  releases), on enterprise identity (SSO/SAML/SCIM, 2FA, API tokens), and on
  ecosystem (integrations, importers, marketplace).
- **vs Mizito** — TeamFlow is the stronger *engineering/dev* product: API-first,
  documented REST + OpenAPI, webhooks, MCP, realtime, strict hierarchy
  integrity. Mizito is the stronger *business/collaboration* product: built-in
  chat/social network, Gantt, Persian calendar, recurring tasks, CRM,
  correspondence, notes, mobile apps, and a free tier.

**Strategy:** don't clone Jira feature-for-feature. Match Jira on the P0 agile
table stakes, then win on the axes where TeamFlow is already ahead — speed,
simplicity, self-hosting, realtime, security, and agent-native automation.

## 3. TeamFlow today (verified inventory)

| Area | What exists |
| --- | --- |
| Auth & security | Email+password (OTP-verified registration), passwordless email OTP, Google OIDC (PKCE + JWKS), rotating refresh tokens with reuse detection & family revocation, logout-all, single-use reset tokens, rate limiting, audit trail |
| Tenancy & RBAC | Organizations, memberships (owner/admin/manager/member), invitations, tenant-scoped rows, IDOR-safe 404 responses |
| Projects | CRUD, active/archived status, pagination, org-wide visibility |
| Tasks | Fixed flow `todo → in_progress → in_review → done`, priorities, due date, single assignee, watchers, labels, Markdown description |
| Hierarchy | `epic > story > task` with strict level validation, cycle prevention, tree endpoint with per-node progress roll-up |
| Collaboration | Flat Markdown comments, email-based `@mentions`, labels, watchers, in-app notifications, daily due-soon reminders |
| Realtime | WebSockets over Redis pub/sub (multi-worker safe) for tasks/comments/notifications |
| Files | Attachments via S3/MinIO presigned URLs, allowlist, size caps, cleanup |
| Dashboards | Org counts: projects/tasks by status, overdue, unassigned, per-member |
| Automation | Outbound HMAC-signed webhooks with durable delivery/retries; Celery Beat jobs (email, cleanup, cache warm, reminders) |
| Admin | sqladmin panel, cursor-free CRUD, CSV export, audit redaction, self-lockout guards |
| API/platform | ~75 REST endpoints, OpenAPI/Swagger, idempotency keys, request IDs, health probes, seed script |
| Frontend | React SPA: kanban (drag & drop), tree view, task drawer, Markdown editor, tasks table with filters, notifications, org/member/label/webhook/audit/dashboard pages |
| Agent integration | First-party MCP server: 18 tools, 3 resources, 2 prompts (board, tasks, tree, move, comment, dashboard) |

### Verified gaps (not in the codebase)

Sprints/backlog, story points/estimates, burndown/velocity/CFD reports, Gantt /
timeline / calendar / roadmap / milestones / releases, custom fields, custom
workflows/statuses, WIP limits, swimlanes, multiple boards, dependencies/task
links, time tracking/worklogs, human-readable keys (`PRJ-123`), multiple
assignees, start dates, checklists, recurring tasks, templates, bulk ops,
clone/duplicate, move between projects, archive/restore, saved filters, global
full-text search, comment threads, reactions, rich text/tables/images, mention
autocomplete, activity feed, presence, email notification preferences/digests,
push notifications, importers, data export API, SSO/SAML/SCIM, 2FA/TOTP, API
keys/PATs/service accounts, per-project permissions/custom roles, automation
rule builder, third-party integrations (Slack/GitHub/Teams/etc.), billing/quota,
mobile app/PWA, dark mode, i18n/RTL.

## 4. TeamFlow vs Jira

### 4.1 Where TeamFlow is better

| # | Advantage | Why it matters vs Jira |
| --- | --- | --- |
| 1 | **Simplicity & time-to-value** | Jira's learning curve and admin burden are its most cited weaknesses; TeamFlow's fixed workflow works out of the box with no scheme/screen/field configuration. |
| 2 | **Self-hostable, no per-seat pricing** | Jira's own tiers keep moving features up and raising costs (reviewers report costs roughly quadrupling to reach features they previously had); TeamFlow ships as Docker Compose with no user caps. |
| 3 | **No configuration bloat ceiling** | Jira enforces hard limits (700 fields / 150 work types per space since March 2026; more limits rolling out from September 2026). TeamFlow has no such ceilings. |
| 4 | **Security engineering depth** | Refresh-token reuse detection with family revocation, pickle-free single-use OAuth state/PKCE, HMAC-hashed OTP with attempt budgets, idempotency keys with race-safe claims, tenant isolation returning 404. Equivalent behavior in Jira requires Enterprise and/or Marketplace apps. |
| 5 | **Realtime architecture** | Every worker can publish and fan out via Redis pub/sub; Jira's realtime is board-refresh oriented and historically lagging at scale. |
| 6 | **Durable outbound webhooks** | Persisted deliveries, HMAC timestamp signatures, delivery IDs for receiver dedupe, retry/backoff with transient-vs-permanent classification. |
| 7 | **Clean, documented API + OpenAPI** | A single coherent REST surface with idempotency headers; Jira's API is broad but versioned across Cloud/DC with capability differences. |
| 8 | **First-party MCP + admin panel** | TeamFlow was agent-native before Jira's 2026 agent push and ships an ops UI with audit redaction without extra licensing. |
| 9 | **Open data path** | PostgreSQL schema owned by you; nothing trapped in a vendor configuration model. |

### 4.2 Where TeamFlow is worse

| # | Disadvantage | Jira capability TeamFlow lacks |
| --- | --- | --- |
| 1 | **No agile planning** | Backlog, sprints, sprint goals, velocity, capacity planning, epic links, release/version management |
| 2 | **No estimation** | Story points, original/remaining estimates, time tracking/worklogs |
| 3 | **No workflow engine** | Custom statuses, transitions, conditions, validators, per-project schemes, WIP limits, swimlanes, multiple boards |
| 4 | **Fixed data model** | Custom fields, custom issue types, components, priorities per project, security levels |
| 5 | **Reporting is counts only** | Burndown, velocity, cumulative flow, control chart, cycle/lead time, sprint report, custom dashboards/gadgets, JQL and natural-language views |
| 6 | **No dependencies/links** | Blocks / is blocked by, relates to, duplicates, clones, parent-child at scale |
| 7 | **No automation builder** | Visual if-this-then-that rules with triggers/conditions/actions (Jira: 300–5,000 runs/month by plan) |
| 8 | **No ecosystem** | Slack, GitHub, GitLab, Bitbucket, Teams, Confluence, Figma, Gmail integrations; Marketplace apps |
| 9 | **No enterprise identity** | SSO/SAML, SCIM provisioning, 2FA/TOTP, API keys/service accounts, granular permission schemes, audit-export/compliance tooling |
| 10 | **No import/export or migration path** | Jira/Trello/Asana/CSV importers, workspace export APIs (TeamFlow only exports CSV from the admin panel) |
| 11 | **Search is weak** | `ILIKE` on title/description only; no global search, no query language, no saved filters |
| 12 | **Collaboration depth** | Threaded comments, reactions, rich text (tables/images), mention autocomplete, activity feed, email digests/preferences, mobile push |
| 13 | **No mobile/offline or i18n** | Jira ships iOS/Android apps and broad localization; TeamFlow is English-only responsive web |
| 14 | **Scale & trust signal** | 100,000+ organizations, security certifications, 24/7 support vs a young self-hosted project |

## 5. TeamFlow vs Mizito

Mizito is an Iranian, cloud-only project management + enterprise social network
(office.mizito.ir), strong in collaboration, correspondence, CRM and Persian
localization. Its board can be customized and it offers Gantt, calendar,
recurring tasks, approvers and mobile apps; task discussion is essentially chat.

### 5.1 Where TeamFlow is better

| # | Advantage | Why it matters |
| --- | --- | --- |
| 1 | **Developer/API-first** | Documented REST + OpenAPI, webhooks with HMAC signatures, idempotency, webhooks for automation. Mizito has no public API; the community `mizito-bridge` project had to reverse-engineer its SPA bundle. |
| 2 | **Agent-native** | First-party MCP server exposing board/task/tree operations. Mizito's MCP exists only as a third-party reverse-engineered bridge. |
| 3 | **Realtime correctness** | Multi-worker-safe WebSockets with Redis fan-out vs. chat-oriented realtime. |
| 4 | **Hierarchy integrity** | Enforced epic > story > task levels with cycle prevention and progress roll-ups — a bug class Mizito-style flat structures don't address. |
| 5 | **Self-hosting / data ownership** | Docker Compose deployment, S3-compatible storage, PostgreSQL you control. Mizito is SaaS-only, hosted in and aimed at Iran. |
| 6 | **Automation & interop** | Webhooks, recurring jobs, idempotent API; Mizito has no comparable outbound automation surface. |
| 7 | **Multi-tenant isolation** | Organization-scoped 404s, audited RBAC, invitation flow vs. workspace switching without a public permission model. |

### 5.2 Where TeamFlow is worse

| # | Disadvantage | Mizito capability TeamFlow lacks |
| --- | --- | --- |
| 1 | **No built-in chat** | Channels, groups, DMs, voice messages, push-to-talk, online meetings, message pinning/search, convert-message-to-task |
| 2 | **No Gantt or calendar** | Gantt chart, Persian (Jalali) calendar, timeline views |
| 3 | **No recurring tasks / templates** | Recurring tasks, task templates, task approval/approver flow |
| 4 | **No checklists / multi-assignee** | Checklists, one or many assignees, responsible person |
| 5 | **No CRM or correspondence** | Customer files, sales opportunities, financial tracking, internal letters with paraph/refer/numbering/archive |
| 6 | **No notes module** | Personal/group notes with attachments and labels |
| 7 | **No rich monitoring charts** | Weighted project progress, per-user/workgroup charts, team strength analysis |
| 8 | **No mobile apps & no Persian/RTL** | Android/iOS apps, RTL UI, Jalali dates, Persian-first onboarding, free tier (5 users / 150 MB) |
| 9 | **Attachment UX** | No project-wide attachment gallery/filter or print-ready task reports; TeamFlow downloads files only |
| 10 | **No meeting/minutes tooling** | Meeting minutes, secretariat processes |

**Takeaway:** if the target market is Iranian SMBs, Mizito sets the localization
bar (Persian, RTL, Jalali, mobile) and the collaboration bar (chat, letters,
CRM). TeamFlow can only compete there after i18n/RTL + mobile/PWA. For
engineering teams anywhere else, TeamFlow's API/realtime/agent story is already
superior.

## 6. Feature list to beat Jira

Priorities: **P0** = needed to be taken seriously by agile dev teams;
**P1** = competitive differentiation / retention; **P2** = enterprise and
long-term moat.

### P0 — Agile table stakes

| # | Feature | What to build | Success criterion |
| --- | --- | --- | --- |
| 1 | **Sprints & backlog** | Iteration entity per project (name, goal, start/end, state), backlog ordering, drag items into sprints, sprint start/complete with carry-over | Scrum team can plan and run a 2-week sprint without a spreadsheet |
| 2 | **Story points & estimates** | Configurable estimation field (points or hours), per-task estimate, remaining/actual | Backlog and board show points; reports use them |
| 3 | **Velocity & capacity** | Points completed per sprint, member capacity/availability per sprint | Capacity view answers "who is overloaded?" |
| 4 | **Agile reports** | Burndown, velocity, cumulative flow, cycle/lead time, sprint report | Reports available per sprint and project, exportable |
| 5 | **Custom workflows & board columns** | Per-project status sets with transition rules (keep a sensible default = current 4 columns), multiple boards, WIP limits, swimlanes | Teams can model their process without forking the code |
| 6 | **Custom fields** | Typed fields (text/number/date/select/multi-select/user) scoped per project, shown on task + filterable | No schema migration needed to track a new attribute |
| 7 | **Issue keys** | Human-readable `PROJECTKEY-123` identifiers alongside UUIDs | Tasks are referenceable in chat/commits/docs |
| 8 | **Task links & dependencies** | Blocks / is blocked by / relates to / duplicates, with a dependency graph surfaced on the board and tree | Blocked work is visible and reportable |
| 9 | **Saved filters + query language** | A query language (TeamQL) over the task fields, saved/shared filters, quick filters on board | Power users can slice work precisely and reuse views |
| 10 | **Global full-text search** | PostgreSQL `tsvector` (or Meilisearch) across tasks/comments/projects; keyboard shortcut | Sub-second search from anywhere |
| 11 | **Bulk operations** | Multi-select: move, assign, label, priority, status, delete; clone/duplicate; move task between projects; archive/restore (soft delete) | Cleaning up 50 tasks takes seconds |
| 12 | **Email notification preferences** | Per-user subscription matrix (assigned/mentioned/comments/due) + digest cadence + unsubscribe | Users control inbox volume; fewer "Jira spam" complaints |
| 13 | **Importers & export** | Jira CSV/JSON, Trello, Asana, generic CSV import; full workspace export (JSON + attachments) | A team can migrate in under an hour, and can always leave |

### P1 — Differentiation & retention

| # | Feature | What to build | Success criterion |
| --- | --- | --- | --- |
| 14 | **Automation rule builder** | Trigger (create/update/transition/schedule) + conditions + actions (assign, transition, comment, notify, webhook); templates for common rules; execution log | Non-engineers automate recurring coordination |
| 15 | **Time tracking** | Worklogs per user/task, original vs remaining estimate, timesheet view, weekly totals | Teams can bill and forecast |
| 16 | **Releases & roadmap** | Versions/releases with dates and scope, timeline/roadmap view grouping tasks by parent | Stakeholders see delivery plan, not a task list |
| 17 | **Calendar view** | Month/week view by due date, drag to reschedule | Basic scheduling without leaving the tool |
| 18 | **Templates** | Project templates (statuses, labels, sample hierarchy) and task templates; standard templates for Scrum/Kanban/bug triage | New project ready in one click |
| 19 | **Recurring tasks** | RRULE-based recurrence with next-occurrence generation | Standups/maintenance no longer recreated manually |
| 20 | **Multiple assignees & checklists** | Assignee lists with roles (assignee/approver), checklist items with progress | Models real coordination better than Jira's single assignee |
| 21 | **Collaboration upgrades** | Threaded comments, emoji reactions, activity feed per task/project, mention autocomplete with user picker | Discussion stays in the task instead of chat/email |
| 22 | **Rich content** | Tables, images (provider-grade), inline attachments, code blocks in editor; keep Markdown source | Docs-quality descriptions |
| 23 | **Third-party integrations** | GitHub/GitLab/Bitbucket (branch/commit/PR links + auto-transition), Slack/Teams notifications, Google Calendar | Work syncs with where developers already are |
| 24 | **API tokens & OAuth apps** | Personal access tokens, scoped service accounts, OAuth app registration, usage/rate-limit views | Automations and CI don't need a human password (today the MCP server logs in with email+password) |
| 25 | **Notification center upgrade** | Grouping by task/project, mute, mark all read (exists), plus per-project mutes | Inbox stays usable at scale |

### P2 — Enterprise & moat

| # | Feature | What to build | Success criterion |
| --- | --- | --- | --- |
| 26 | **SSO & provisioning** | SAML/OIDC enterprise SSO, SCIM user/group provisioning, domain capture (Google sign-in exists as consumer-grade only) | Enterprise IT approves deployment |
| 27 | **MFA** | TOTP + recovery codes; enforce per org; session/device list with revocation | Satisfies security questionnaires |
| 28 | **Granular permissions** | Per-project visibility (private/team/org), custom roles, project-level membership, guest collaborators | Sensitive projects can be restricted without separate orgs |
| 29 | **Audit & compliance** | Audit log retention policy, export API, tamper-evident hashing; data residency notes; SOC 2 readiness documentation | Passes procurement review |
| 30 | **Dashboard builder** | Configurable widgets (charts, filtered task lists, burndown) with sharing | Leadership builds its own views |
| 31 | **Goals / OKRs** | Objectives with key results linked to epics/projects and progress roll-up | Work is tied to outcomes (Jira is pushing this too) |
| 32 | **Forms / request intake** | Public/embedded forms that create typed tasks with required fields and routing | Partner teams submit requests the right way |
| 33 | **AI-native features** | Standup digest, meeting/thread summarization, duplicate detection, natural-language query and task creation, smart assignment; extend MCP to cover every new entity (automation, sprints, reports) | Measurably less coordination overhead; MCP stays best-in-class |
| 34 | **Mobile & PWA** | Responsive PWA with install/offline read, push notifications; native apps later | Phones get notifications; field teams can update tasks |
| 35 | **i18n, RTL & Jalali** | Framework i18n, Persian + RTL layout, Jalali calendar option | Competitive against Mizito in Iran/MENA |
| 36 | **Dark mode & theming** | System/light/dark, org accent color | Cheap, highly requested |
| 37 | **Performance & scale proof** | Cursor pagination, caching, query budgets, load-test targets documented with the 1M-row seed; frontend test coverage | 10k tasks/board stays under 1s |
| 38 | **Marketplace / extensibility** | Public plugin API + webhook event catalog (fix `member.joined` which is advertised but never dispatched), app directory | Ecosystem effects begin |

### Quick wins (days, high impact)

1. **Dark mode** (frontend only).
2. **Fix the dead `member.joined` webhook** and emit `task.completed`
   notifications (the constant exists but is never emitted).
3. **Human-readable issue keys** — high perceived value, contained migration.
4. **Mention autocomplete** — currently `@mentions` are plain email strings with
   no editor affordance.
5. **Email preferences toggle for the existing `task_assigned` template** — it
   is defined but never enqueued.
6. **Saved filters** for the existing tasks table.

## 7. Positioning: how TeamFlow beats Jira

Feature parity is necessary but not sufficient. The winning wedge:

1. **Speed as a feature.** Publish benchmarks (board load, search, API latency)
   against Jira's documented slowdowns at scale and make "fast" part of the
   product story.
2. **Self-host + data ownership.** Teams leaving Jira Data Center or hit by
   Cloud price/limit changes need a migration path; ship the Jira importer and
   an "exit guarantee" export early.
3. **Developer experience first.** OpenAPI, idempotency, webhooks and
   best-in-class MCP agent support — be the board coding agents prefer to
   operate.
4. **Radical simplicity with escape hatches.** Default to the current 4-column
   flow; expose custom workflows/custom fields only when a team asks, so
   TeamFlow never becomes "bloated Jira".
5. **Honest pricing.** Predictable self-host license or flat cloud pricing; no
   feature moved behind a higher tier mid-contract.
6. **Imports, not lock-in.** One-click import from Jira/Trello/Asana plus
   continuous export builds trust and lowers switching cost.

## 8. Suggested sequencing

| Phase | Theme | Includes |
| --- | --- | --- |
| Phase 1 (0–3 mo) | Agile MVP + quick wins | Sprints/backlog, story points, issue keys, saved filters, global search, dark mode, email prefs, bulk ops, `member.joined` fix |
| Phase 2 (3–6 mo) | Planning depth | Custom workflows/boards, custom fields, task links/dependencies, agile reports, time tracking, templates, importers/export |
| Phase 3 (6–12 mo) | Collaboration & ecosystem | Threads/reactions/activity, rich content, notifications upgrade, Git/Slack/Teams integrations, API tokens, automation builder, releases/roadmap/calendar |
| Phase 4 (12 mo+) | Enterprise & moat | SSO/SCIM, MFA, granular permissions, audit/compliance, dashboard builder, goals, forms, AI features, mobile/PWA, i18n/RTL |

## 9. Sources

- TeamFlow: this repository (`app/`, `frontend/`, `mcp_server/`, `README.md`).
- Jira: Atlassian feature, agile, and seasonal release pages (Spring/Summer
  2026); Atlassian support "Data limits and guardrails" (Aug 2026);
  Gartner Peer Insights, Capterra and Software Advice reviews (2026);
  Atlassian Community articles on instance bloat, API/app usage, and 2026
  pricing/feature-tier changes.
- Mizito: mizito.ir home and pricing pages; help.mizito.ir; Google Play
  listing (v2.0.3); `mohsp-99/mizito-bridge` reverse-engineering notes for the
  API/auth reality (office.mizito.ir, `/capi`, token-keyed task comments, no
  documented public API).
