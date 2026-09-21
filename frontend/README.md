# TeamFlow Frontend

React 19 + TypeScript + Vite single-page app for the TeamFlow API.

| Concern      | Choice                                    |
| ------------ | ----------------------------------------- |
| Build        | Vite 8                                    |
| UI           | React 19, Tailwind CSS v4                 |
| Routing      | React Router v7                           |
| Server state | TanStack Query v5                         |
| Icons        | lucide-react                              |
| Realtime     | Native WebSocket (`/ws/projects/{id}`)    |

## Features

- Auth: register, login, forgot/reset password, refresh-token rotation
  (`lib/api.ts` retries a request once after rotating tokens), logout-all.
- Workspaces: list/create/rename/delete, role-aware UI
  (member / manager / admin / owner mirror the backend rules).
- Projects: list, create, archive, delete.
- Tasks: kanban board with drag & drop (status transitions enforced by the
  API), org-wide filtered list (search, type, status, priority, assignee,
  overdue, sort, pagination), full task detail drawer with comments,
  attachments (presigned S3/MinIO upload/download), labels and watchers.
- Hierarchy: GitHub-Projects-style epic > story > task nesting. Create
  work items of each type, pick a parent (a child may nest under any higher
  level), switch the project between board and tree views, and track
  progress via child counters and progress bars.
- Markdown: task descriptions and comments use a Jira-style editor with a
  Write/Preview toggle, formatting toolbar (bold, italic, code, links,
  headings, lists, quotes, code blocks) and keyboard shortcuts; rendered
  output is React elements only (no raw HTML).
- Realtime: project sockets with reconnect/backoff; board and open task
  refresh on `task.*` / `comment.*` events.
- Notifications: bell with unread badge (polled), inbox page, mark read/all.
- Members & invitations: invite/accept/decline, role changes, direct add.
- Labels, webhooks (secret shown once + delivery log) and audit trail
  (admin+ pages).
- Dashboard: SQL-aggregated stats rendered as cards and bars.

## Getting started

```bash
cd frontend
npm install
cp .env.example .env   # optional; defaults match the dev backend
npm run dev            # http://localhost:3000
```

The dev server runs on port **3000**, which matches the backend defaults
(`CORS_ORIGINS=["http://localhost:3000"]`, `FRONTEND_BASE_URL`). If you use a
different port, update `CORS_ORIGINS` in the backend `.env`.

Backend must be reachable at `http://localhost:8000` (see the root README for
`docker compose up -d db redis minio` + `uv run uvicorn app.main:app --reload`).

### Environment variables

| Variable            | Default                          |
| ------------------- | -------------------------------- |
| `VITE_API_BASE_URL` | `http://localhost:8000/api/v1`   |
| `VITE_WS_BASE_URL`  | derived from `VITE_API_BASE_URL` |

## Scripts

```bash
npm run dev       # dev server (port 3000)
npm run build     # type-check + production build to dist/
npm run preview   # serve the production build (port 3000)
npm run lint      # oxlint
```

## Project layout

```text
src/
  lib/          api client, hooks (TanStack Query), types, ws client, utils
  contexts/     auth + toast providers
  components/   layout, org context, task board/drawer/sections, UI primitives
  pages/        one file per route
```

## Notes

- HTTP errors surface the API's `detail` field through toasts.
- The API 404s non-members (tenant isolation), so "not found" is the normal
  denied-access UX.
- Browser uploads go directly to MinIO/S3 via presigned PUT URLs; if uploads
  fail with a CORS error in development, configure the bucket's CORS policy
  (MinIO: `mc cors set` on `teamflow-attachments`).
