# TeamFlow MCP server

An [MCP](https://modelcontextprotocol.io) server that turns a TeamFlow
installation into a project management board your coding agents can use.
It speaks stdio, so any MCP-capable client (opencode, Claude Desktop, Cursor,
VS Code, ...) can spawn it and get TeamFlow tools.

The server is a **pure API client**: it logs into the TeamFlow REST API with a
normal user account and never touches the database. That means you can point it
at `http://localhost:8000` for local work or a shared deployment from any other
repository.

```
agent  ──stdio──▶  teamflow-mcp  ──HTTPS/JSON──▶  TeamFlow API  ──▶  Postgres
```

## Install

Requires Python 3.10+. From this directory:

```bash
uv sync                 # create .venv and install dependencies
uv run teamflow-mcp --check   # verify credentials end-to-end
```

Or install it as a standalone tool that any agent can launch:

```bash
uv tool install .
# or
pipx install .
```

TeamFlow itself must be running (`uv run uvicorn app.main:app --reload` in the
repository root, or your deployed instance).

## Configure

All settings come from environment variables prefixed `TEAMFLOW_`. A `.env`
file in the working directory also works (see `.env.example`).

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `TEAMFLOW_API_URL` | yes | `http://localhost:8000` | TeamFlow base URL. `/api/v1` is appended if missing. |
| `TEAMFLOW_EMAIL` | yes | – | Account the agent acts as. |
| `TEAMFLOW_PASSWORD` | yes | – | Password (min 10 chars, matching TeamFlow's rules). |
| `TEAMFLOW_ORG` | no | your only org | Default organization slug. |
| `TEAMFLOW_PROJECT` | no | – | Default project name or UUID. |
| `TEAMFLOW_TIMEOUT` | no | `30` | HTTP timeout in seconds. |
| `TEAMFLOW_VERIFY_SSL` | no | `true` | Set `false` only for self-signed local TLS. |

The server logs in once, refreshes its access token automatically, and
re-authenticates if a token is revoked. No token juggling required.

Create the account first if you do not have one:

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"agent@example.com","password":"a-long-password","full_name":"Agent"}'
```

Then add it to an organization in the TeamFlow UI (or via
`POST /api/v1/organizations/{slug}/members`).

## Connect an agent

### opencode

Add to `opencode.json` (project) or `~/.config/opencode/opencode.json` (global).
Tools are exposed to the model prefixed with the server name, e.g.
`teamflow_get_board`.

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "teamflow": {
      "type": "local",
      "command": ["uv", "run", "--directory", "C:/repos/TeamFlow/mcp_server", "teamflow-mcp"],
      "environment": {
        "TEAMFLOW_API_URL": "http://localhost:8000",
        "TEAMFLOW_EMAIL": "{env:TEAMFLOW_EMAIL}",
        "TEAMFLOW_PASSWORD": "{env:TEAMFLOW_PASSWORD}",
        "TEAMFLOW_ORG": "my-org",
        "TEAMFLOW_PROJECT": "My Board"
      }
    }
  }
}
```

Using `{env:...}` keeps secrets out of the config file. If you installed with
`uv tool install`, `"command": ["teamflow-mcp"]` is enough.

Once connected, prompt it directly:

```
Use the teamflow tools: show me the board for "Payments API",
then move TASK_ID to in_review and assign the checkout bug to alice@example.com.
```

### Claude Desktop / Cursor / VS Code

Any client that supports stdio MCP servers uses the same shape
(`command` + `args` + `env`). For example, Claude Desktop's
`claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "teamflow": {
      "command": "uv",
      "args": ["run", "--directory", "C:/repos/TeamFlow/mcp_server", "teamflow-mcp"],
      "env": {
        "TEAMFLOW_API_URL": "http://localhost:8000",
        "TEAMFLOW_EMAIL": "agent@example.com",
        "TEAMFLOW_PASSWORD": "a-long-password"
      }
    }
  }
}
```

## Share it with your team

The API is already deployed, so a teammate only needs the MCP server package
and their **own** TeamFlow account. Nothing runs on their machine except the
MCP server process itself, and it talks straight to the VPS.

### 1. Point at the deployment

```jsonc
"environment": {
  "TEAMFLOW_API_URL": "https://arsene.ir/flow",   // /api/v1 is appended automatically
  "TEAMFLOW_EMAIL": "{env:TEAMFLOW_EMAIL}",
  "TEAMFLOW_PASSWORD": "{env:TEAMFLOW_PASSWORD}",
  "TEAMFLOW_ORG": "your-org"
}
```

Give the **base URL only** (`https://arsene.ir/flow`), not `/api/v1`.
On this deployment only `/flow/api/v1/*` is routed to the API — `/flow/docs`
and `/flow/openapi.json` fall through to the web app, so do not rely on them.
Verify reachability and credentials with:

```bash
teamflow-mcp --check
# API        : https://arsene.ir/flow/api/v1
# User       : teammate@example.com (...)
# Orgs       : your-org [member]
# OK: credentials work, the MCP server can log in.
```

### 2. Give each teammate their own account

Never share one login across the team: task attribution, audit logs, comments
and notification emails all key off the account, and one leaked password would
expose everything. The API also returns `404` (not `403`) to non-members, so a
teammate without a membership sees "not found" rather than an error.

1. Teammate signs up at `https://arsene.ir/flow/register`
   (password must be at least 10 characters).
2. An owner/admin invites them from
   `https://arsene.ir/flow/org/<slug>/members` (choose the role).
3. Teammate accepts at `https://arsene.ir/flow/invitations`.

Roles are `owner` > `admin` > `manager` > `member`. Tenant isolation means a
teammate's agent can only ever read and write the organizations they belong to
— the VPS shares one database, but not one visible board.

### 3. Get them the MCP server

The GitHub repo is private, so pick whichever fits your team:

**Option A — share the built wheel (simplest).**

```bash
cd mcp_server && uv build     # produces dist/teamflow_mcp-0.1.0-py3-none-any.whl
```

Send them `teamflow_mcp-0.1.0-py3-none-any.whl`, then they run:

```bash
uv tool install ./teamflow_mcp-0.1.0-py3-none-any.whl   # or: pipx install ...
teamflow-mcp --check
```

and use `"command": ["teamflow-mcp"]`. No repo access or Python project setup
needed beyond [uv](https://docs.astral.sh/uv/) (or pipx).

**Option B — teammates with repo access clone it.**

```bash
git clone https://github.com/arsene-ir/TeamFlow.git
uv run --directory TeamFlow/mcp_server teamflow-mcp --check
```

and use
`"command": ["uv", "run", "--directory", "/abs/path/TeamFlow/mcp_server", "teamflow-mcp"]`.

**Option C — publish once, everyone runs `uvx teamflow-mcp`.**
Best ergonomics for a growing team. `uv publish` to PyPI (public) or a private
index such as GitHub Packages. Note the repo is private, so publishing puts the
*client code* on that index — it contains no secrets, only an API client.

**Option D — Docker, for teammates without Python.**

```dockerfile
FROM python:3.12-slim
RUN pip install --no-cache-dir teamflow-mcp
ENTRYPOINT ["teamflow-mcp"]
```

```jsonc
"command": ["docker", "run", "-i", "--rm",
            "-e", "TEAMFLOW_API_URL=https://arsene.ir/flow",
            "-e", "TEAMFLOW_EMAIL", "-e", "TEAMFLOW_PASSWORD",
            "ghcr.io/arsene-ir/teamflow-mcp:latest"]
```

### Operational notes for a shared deployment

- Login is rate limited to 5 attempts/minute/IP. The MCP server logs in once per
  session and then rotates its refresh token, so normal use never hits this — but
  a team behind one office NAT that restarts many agents at once can.
- Access tokens last 30 minutes; the server refreshes them silently. Revoking a
  teammate's sessions in TeamFlow logs their agent out on the next call.
- Keep `TEAMFLOW_PASSWORD` in the agent's `environment` block via `{env:...}` or
  a `.env` file — never inline in a config file you might commit.
- Config changes (org/project defaults) are per-teammate; nothing is stored on
  the VPS for the MCP server.

## Tools

| Tool | What it does |
| --- | --- |
| `whoami` | Account, roles, and the defaults this server uses. Call it first. |
| `list_organizations` | Organizations you belong to, with roles. |
| `list_projects` | Projects in an organization. |
| `get_board` | **Kanban board**: each column with accurate counts and top cards. |
| `list_tasks` | Filter by status, priority, assignee, label, due dates, overdue, free text. |
| `get_task` | One task in full, with its comment thread. |
| `create_task` | Create a task on a project (starts in `todo`). |
| `update_task` | Change title, description, priority, due date, assignee, labels, status. |
| `move_task` | Move a card between columns, optionally with an explanatory comment. |
| `delete_task` | Permanently delete a task. |
| `my_work` | Everything assigned to you, grouped by column — ideal for standups. |
| `add_comment` / `list_comments` | Task discussion. |
| `list_members` | Emails and roles, for resolving assignees. |
| `list_labels` / `create_label` | Label management. |
| `get_dashboard` | Org-wide statistics (cheap overview). |

Resources: `teamflow://me`,
`teamflow://organizations/{slug}/dashboard`,
`teamflow://projects/{project_id}/board`.

Prompts: `daily_standup`, `board_triage`.

### Conventions worth knowing

- `project` accepts a **name or UUID**; `assignee` accepts `me`, an **email**,
  or a UUID; `labels` accept names or UUIDs. The server resolves them to IDs
  and returns helpful errors listing valid options.
- Column moves are **step-wise**: `todo ⇄ in_progress ⇄ in_review ⇄ done`.
  A task cannot jump from `todo` to `done`; call `move_task` twice.
- `update_task` only changes the fields you pass. Clear an assignee with
  `assignee="unassigned"` and a due date with `clear_due_date=true`.
- Passing `labels=[...]` to `update_task` **replaces** the whole label set;
  `labels=[]` removes all labels.
- `delete_task` is permission-gated server-side: `member` role can only delete
  tasks they created.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `TEAMFLOW_EMAIL and TEAMFLOW_PASSWORD are not set` | Add them to the agent's `environment`/`env` block or a `.env` file. |
| `TeamFlow API 401` | Wrong credentials, or the account was deactivated. Check with `teamflow-mcp --check`. |
| `Cannot reach TeamFlow at ...` | The API is not running, or `TEAMFLOW_API_URL` is wrong. |
| `TEAMFLOW_ORG is not set and this account belongs to N organizations` | Set `TEAMFLOW_ORG`, or pass `org_slug` per call. |
| `No project named '...'` | The tool lists available projects in the error. Names are matched case-insensitively. |
| `Rate limited - retry in a moment` | TeamFlow limits login attempts per IP. Wait ~60s. |
| Tools do not appear in the agent | Run `teamflow-mcp --check` manually to confirm the server starts, and check the client's MCP logs. |

## Development

```bash
uv run python -m teamflow_mcp          # start the stdio server by hand
uv run teamflow-mcp --check            # auth + org/project smoke test
npx @modelcontextprotocol/inspector uv run teamflow-mcp   # interactive tool explorer
```

Layout: `config.py` (env settings), `client.py` (auth + HTTP + name/ID
resolution), `formatting.py` (compact task projections), `server.py` (tools,
resources, prompts).
