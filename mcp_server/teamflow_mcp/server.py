"""TeamFlow MCP server (stdio).

Exposes a TeamFlow organization/project board as MCP tools so any MCP-capable
agent can use TeamFlow as its project management board. The server is a pure
API client - it never talks to the database - so it can point at a local dev
instance or a shared deployment via `TEAMFLOW_API_URL`.

Run directly (`teamflow-mcp`), through `python -m teamflow_mcp`, or let the
agent spawn it. Use `teamflow-mcp --check` to verify credentials without an
agent.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer

from .client import TeamFlowError, get_client
from .config import get_settings
from .formatting import (
    STATUS_LABELS,
    STATUS_ORDER,
    comment_item,
    json_text,
    sort_cards,
    task_card,
    task_record,
)

Status = Literal["todo", "in_progress", "in_review", "done"]
Priority = Literal["low", "medium", "high", "urgent"]

TRANSITIONS = {
    "todo": "in_progress",
    "in_progress": "todo | in_review",
    "in_review": "in_progress | done",
    "done": "in_progress",
}

mcp = MCPServer(
    "teamflow",
    instructions=(
        "TeamFlow is a multi-tenant project management board with kanban columns "
        "'todo', 'in_progress', 'in_review', 'done'.\n\n"
        "Typical flow: call whoami() to confirm the account and defaults, then "
        "get_board() to see the current board, then list_tasks()/get_task() to "
        "drill in and create_task()/update_task()/move_task() to make changes.\n\n"
        "Argument conventions:\n"
        "- `project` accepts a project name or UUID (default: TEAMFLOW_PROJECT).\n"
        "- `org_slug` defaults to TEAMFLOW_ORG, or your only organization.\n"
        "- `assignee` accepts 'me', an email address, or a user UUID.\n"
        "- `labels` accept label names or UUIDs.\n\n"
        "Status moves are step-wise only: todo <-> in_progress <-> in_review <-> done "
        "(a task cannot jump from todo straight to done)."
    ),
)


def _client():
    try:
        return get_client()
    except Exception as exc:  # pragma: no cover - configuration guard
        raise TeamFlowError(f"TeamFlow MCP is not configured: {exc}") from exc


# --------------------------------------------------------------------- tools


@mcp.tool()
async def whoami() -> str:
    """Identify the TeamFlow account this MCP server is authenticated as.

    Returns the user profile, the organizations they belong to (with roles), and
    the default org/project the server will use when a tool call omits them.
    Call this first when a task mentions TeamFlow but you do not yet know the
    organization or project.
    """
    client = _client()
    settings = get_settings()
    user = await client.me()
    listing = await client.organizations()
    return json_text(
        {
            "user": user,
            "defaults": {"org": settings.org or None, "project": settings.project or None},
            "api_url": client.base_url,
            "organizations": [
                {
                    "slug": item["organization"]["slug"],
                    "name": item["organization"]["name"],
                    "role": item["role"],
                }
                for item in listing
            ],
        }
    )


@mcp.tool()
async def list_organizations() -> str:
    """List the organizations (workspaces) you belong to, with your role in each.

    The `slug` values are what the `org_slug` argument of every other tool takes.
    """
    listing = await _client().organizations()
    return json_text(
        [
            {
                "slug": item["organization"]["slug"],
                "name": item["organization"]["name"],
                "role": item["role"],
                "is_active": item["organization"]["is_active"],
            }
            for item in listing
        ]
    )


@mcp.tool()
async def list_projects(
    org_slug: str | None = None, include_archived: bool = False
) -> str:
    """List projects in an organization.

    Args:
        org_slug: Organization slug. Defaults to TEAMFLOW_ORG, or your only org.
        include_archived: Include projects with status 'archived' (excluded by default).
    """
    client = _client()
    slug = await client.resolve_org_slug(org_slug)
    projects = await client.get(f"/organizations/{slug}/projects", limit=100) or []
    if not include_archived:
        projects = [p for p in projects if p.get("status") != "archived"]
    return json_text(
        {
            "organization": slug,
            "projects": [
                {
                    "id": p["id"],
                    "name": p["name"],
                    "status": p["status"],
                    "description": p.get("description"),
                    "updated_at": p.get("updated_at"),
                }
                for p in projects
            ],
        }
    )


@mcp.tool()
async def get_board(
    project: str | None = None,
    org_slug: str | None = None,
    per_column: int = 25,
    assignee: str | None = None,
    label: str | None = None,
) -> str:
    """Show the kanban board for a project: every column with its real task count and top cards.

    This is the best first call when you need the state of a project. Cards are
    ordered with overdue first, then by priority, then most recently updated.

    Args:
        project: Project name or UUID. Defaults to TEAMFLOW_PROJECT.
        org_slug: Organization slug. Defaults to TEAMFLOW_ORG, or your only org.
        per_column: How many cards to return per column (1-100). Counts stay accurate.
        assignee: Only cards assigned to this user ('me', email, or UUID).
        label: Only cards carrying this label name.
    """
    client = _client()
    slug, project_data = await client.resolve_project(project, org_slug)
    assignee_id = await client.resolve_user_id(assignee, slug)
    label_id = (await client.resolve_labels([label], slug) or [None])[0] if label else None
    depth = max(1, min(int(per_column), 100))

    shared: dict[str, Any] = {
        "project_id": project_data["id"],
        "assignee_id": assignee_id,
        "label_id": label_id,
        "limit": depth,
        "sort": "-updated_at",
    }

    async def column(status: str) -> dict[str, Any]:
        page = (
            await client.get(f"/organizations/{slug}/tasks", status=status, **shared)
        ) or {}
        cards = sort_cards([task_card(t) for t in page.get("items") or []])
        total = int(page.get("total") or 0)
        column_payload: dict[str, Any] = {
            "status": status,
            "column": STATUS_LABELS[status],
            "count": total,
            "cards": cards,
        }
        if total > len(cards):
            column_payload["truncated"] = f"{total - len(cards)} more not shown"
        return column_payload

    columns = list(await asyncio.gather(*(column(s) for s in STATUS_ORDER)))
    open_tasks = sum(c["count"] for c in columns if c["status"] != "done")

    return json_text(
        {
            "organization": slug,
            "project": {
                "id": project_data["id"],
                "name": project_data["name"],
                "status": project_data["status"],
            },
            "filters": {"assignee": assignee, "label": label, "per_column": depth},
            "open_tasks": open_tasks,
            "columns": columns,
        }
    )


@mcp.tool()
async def list_tasks(
    project: str | None = None,
    org_slug: str | None = None,
    status: list[Status] | None = None,
    priority: list[Priority] | None = None,
    assignee: str | None = None,
    unassigned: bool = False,
    label: str | None = None,
    search: str | None = None,
    overdue: bool = False,
    due_before: str | None = None,
    due_after: str | None = None,
    sort: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> str:
    """Search and filter tasks, optionally narrowed to one project.

    Args:
        project: Project name or UUID. Omit to search the whole organization.
        org_slug: Organization slug. Defaults to TEAMFLOW_ORG, or your only org.
        status: One or more of todo, in_progress, in_review, done.
        priority: One or more of low, medium, high, urgent.
        assignee: 'me', an email address, or a user UUID.
        unassigned: Only tasks with no assignee.
        label: Label name or UUID.
        search: Free-text match on title/description (max 100 chars).
        overdue: Only tasks past their due date and not done.
        due_before: ISO-8601 datetime upper bound on due date.
        due_after: ISO-8601 datetime lower bound on due date.
        sort: Sortable field, prefix '-' for descending. One of created_at,
            updated_at, title, priority, status, due_date (e.g. '-due_date').
        limit: Page size (1-100).
        offset: Pagination offset.
    """
    client = _client()
    project_data = None
    if project or get_settings().project:
        slug, project_data = await client.resolve_project(project, org_slug)
    else:
        slug = await client.resolve_org_slug(org_slug)

    params: dict[str, Any] = {
        "project_id": project_data["id"] if project_data else None,
        "status": status,
        "priority": priority,
        "assignee_id": await client.resolve_user_id(assignee, slug),
        "unassigned": unassigned,
        "label_id": (await client.resolve_labels([label], slug) or [None])[0]
        if label
        else None,
        "search": search,
        "overdue": overdue,
        "due_before": due_before,
        "due_after": due_after,
        "sort": sort,
        "limit": max(1, min(int(limit), 100)),
        "offset": max(0, int(offset)),
    }

    page = (await client.get(f"/organizations/{slug}/tasks", **params)) or {}
    cards = [task_card(t) for t in page.get("items") or []]
    return json_text(
        {
            "organization": slug,
            "project": project_data["name"] if project_data else None,
            "total": page.get("total", 0),
            "offset": page.get("offset", 0),
            "limit": page.get("limit", 0),
            "returned": len(cards),
            "tasks": cards,
        }
    )


@mcp.tool()
async def get_task(task_id: str, include_comments: bool = True) -> str:
    """Fetch one task in full, including description, labels, watchers and (by default) comments.

    Args:
        task_id: Task UUID (as returned by get_board or list_tasks).
        include_comments: Attach the comment thread.
    """
    client = _client()
    task = await client.get(f"/tasks/{task_id}")
    payload: dict[str, Any] = {"task": task_record(task)}
    if include_comments:
        comments = await client.get(f"/tasks/{task_id}/comments", limit=100) or []
        payload["comments"] = [comment_item(c) for c in comments]
    payload["allowed_next_status"] = TRANSITIONS.get(task.get("status"), "")
    return json_text(payload)


@mcp.tool()
async def create_task(
    title: str,
    project: str | None = None,
    org_slug: str | None = None,
    description: str | None = None,
    priority: Priority = "medium",
    due_date: str | None = None,
    assignee: str | None = None,
    labels: list[str] | None = None,
) -> str:
    """Create a task on a project board. New tasks start in the 'todo' column.

    Args:
        title: Short task title (required, max 255 chars).
        project: Project name or UUID. Defaults to TEAMFLOW_PROJECT.
        org_slug: Organization slug. Defaults to TEAMFLOW_ORG, or your only org.
        description: Markdown body (max 20,000 chars).
        priority: low, medium, high, or urgent.
        due_date: ISO-8601 datetime, e.g. '2026-10-01T17:00:00Z'.
        assignee: 'me', a member email, or a user UUID. Must be an org member.
        labels: Label names or UUIDs (must already exist - see create_label).
    """
    client = _client()
    slug, project_data = await client.resolve_project(project, org_slug)
    body: dict[str, Any] = {
        "title": title,
        "description": description,
        "priority": priority,
        "due_date": due_date,
    }
    assignee_id = await client.resolve_user_id(assignee, slug)
    if assignee_id:
        body["assignee_id"] = assignee_id
    label_ids = await client.resolve_labels(labels, slug)
    if label_ids:
        body["label_ids"] = label_ids

    task = await client.post(f"/projects/{project_data['id']}/tasks", body)
    return json_text(
        {
            "created": task_record(task),
            "board": {"organization": slug, "project": project_data["name"]},
            "hint": "New tasks sit in 'todo'. Use move_task to advance them one step.",
        }
    )


@mcp.tool()
async def update_task(
    task_id: str,
    title: str | None = None,
    description: str | None = None,
    priority: Priority | None = None,
    due_date: str | None = None,
    clear_due_date: bool = False,
    assignee: str | None = None,
    labels: list[str] | None = None,
    status: Status | None = None,
) -> str:
    """Update fields on an existing task. Only the arguments you pass are changed.

    Args:
        task_id: Task UUID.
        title: New title.
        description: New markdown body (replaces the old one).
        priority: low, medium, high, or urgent.
        due_date: New ISO-8601 due date, e.g. '2026-10-01T17:00:00Z'.
        clear_due_date: Set true to remove the due date. Overrides due_date.
        assignee: 'me', a member email, a user UUID, or 'unassigned' to clear it.
        labels: Replace the task's labels with this set (names or UUIDs). Pass an
            empty list to remove all labels.
        status: Move to this status. Step-wise only: todo <-> in_progress <->
            in_review <-> done. Prefer move_task for pure status changes.
    """
    client = _client()
    current = await client.get(f"/tasks/{task_id}")
    body: dict[str, Any] = {}

    if title is not None:
        body["title"] = title
    if description is not None:
        body["description"] = description
    if priority is not None:
        body["priority"] = priority
    if clear_due_date:
        body["due_date"] = None
    elif due_date is not None:
        body["due_date"] = due_date

    if assignee is not None:
        if assignee.strip().casefold() in {"unassigned", "none", "nobody", "clear"}:
            body["assignee_id"] = None
        else:
            slug = await client.org_slug_for_id(current["organization_id"])
            resolved = await client.resolve_user_id(assignee, slug)
            if resolved is None:
                raise TeamFlowError("Could not resolve that assignee.")
            body["assignee_id"] = resolved

    if labels is not None:
        if not labels:
            body["label_ids"] = []
        else:
            slug = await client.org_slug_for_id(current["organization_id"])
            body["label_ids"] = await client.resolve_labels(labels, slug)

    if status is not None:
        body["status"] = status

    if not body:
        raise TeamFlowError("Nothing to update - pass at least one field.")

    task = await client.patch(f"/tasks/{task_id}", body)
    return json_text(
        {
            "updated": task_record(task),
            "changed": sorted(body),
            "allowed_next_status": TRANSITIONS.get(task.get("status"), ""),
        }
    )


@mcp.tool()
async def move_task(task_id: str, status: Status, note: str | None = None) -> str:
    """Move a task to a new column, optionally logging a comment explaining why.

    Transitions are step-wise and cannot be skipped:
    todo -> in_progress -> in_review -> done (and one step back).

    Args:
        task_id: Task UUID.
        status: Target status: todo, in_progress, in_review, or done.
        note: Optional comment posted on the task after the move.
    """
    client = _client()
    task = await client.post(f"/tasks/{task_id}/move", {"status": status})
    payload: dict[str, Any] = {
        "moved": task_record(task),
        "allowed_next_status": TRANSITIONS.get(task.get("status"), ""),
    }
    if note:
        comment = await client.post(f"/tasks/{task_id}/comments", {"body": note})
        payload["comment"] = comment_item(comment)
    return json_text(payload)


@mcp.tool()
async def delete_task(task_id: str) -> str:
    """Permanently delete a task. This cannot be undone.

    Note: members can only delete tasks they created; managers and above can
    delete any task in the organization.
    """
    client = _client()
    task = await client.get(f"/tasks/{task_id}")
    await client.delete(f"/tasks/{task_id}")
    return json_text({"deleted": {"id": task["id"], "title": task["title"]}})


@mcp.tool()
async def my_work(
    org_slug: str | None = None,
    status: list[Status] | None = None,
    limit: int = 50,
) -> str:
    """Everything assigned to me, grouped by column - use this for standups and reminders.

    Args:
        org_slug: Organization slug. Defaults to TEAMFLOW_ORG, or your only org.
        status: Restrict to these statuses.
        limit: Max tasks to fetch across the organization (1-100).
    """
    client = _client()
    slug = await client.resolve_org_slug(org_slug)
    me = await client.me()
    page = (
        await client.get(
            f"/organizations/{slug}/tasks",
            assignee_id=me["id"],
            status=status,
            sort="-updated_at",
            limit=max(1, min(int(limit), 100)),
        )
    ) or {}

    grouped: dict[str, list[dict[str, Any]]] = {s: [] for s in STATUS_ORDER}
    for task in page.get("items") or []:
        grouped.setdefault(task["status"], []).append(task_card(task))

    return json_text(
        {
            "user": me["email"],
            "organization": slug,
            "assigned_total": page.get("total", 0),
            "columns": [
                {
                    "status": s,
                    "column": STATUS_LABELS[s],
                    "count": len(grouped.get(s) or []),
                    "cards": sort_cards(grouped.get(s) or []),
                }
                for s in STATUS_ORDER
            ],
        }
    )


@mcp.tool()
async def add_comment(task_id: str, body: str) -> str:
    """Post a comment on a task.

    Args:
        task_id: Task UUID.
        body: Comment text (markdown, max 20,000 chars).
    """
    comment = await _client().post(f"/tasks/{task_id}/comments", {"body": body})
    return json_text({"comment": comment_item(comment)})


@mcp.tool()
async def list_comments(task_id: str, limit: int = 100, offset: int = 0) -> str:
    """Read the comment thread on a task.

    Args:
        task_id: Task UUID.
        limit: Page size (1-200).
        offset: Pagination offset.
    """
    comments = (
        await _client().get(
            f"/tasks/{task_id}/comments",
            limit=max(1, min(int(limit), 200)),
            offset=max(0, int(offset)),
        )
    ) or []
    return json_text(
        {"count": len(comments), "comments": [comment_item(c) for c in comments]}
    )


@mcp.tool()
async def list_members(org_slug: str | None = None) -> str:
    """List organization members with their roles and emails.

    Use the emails returned here as the `assignee` argument of other tools.
    """
    client = _client()
    slug = await client.resolve_org_slug(org_slug)
    members = await client.get(f"/organizations/{slug}/members", limit=200) or []
    return json_text(
        {
            "organization": slug,
            "members": [
                {
                    "user_id": m.get("user_id"),
                    "email": (m.get("user") or {}).get("email"),
                    "full_name": (m.get("user") or {}).get("full_name"),
                    "role": m.get("role"),
                }
                for m in members
            ],
        }
    )


@mcp.tool()
async def list_labels(org_slug: str | None = None) -> str:
    """List the labels available in an organization (names are usable in filters)."""
    client = _client()
    slug = await client.resolve_org_slug(org_slug)
    labels = await client.get(f"/organizations/{slug}/labels", limit=200) or []
    return json_text(
        {
            "organization": slug,
            "labels": [
                {"id": l["id"], "name": l["name"], "color": l.get("color")} for l in labels
            ],
        }
    )


@mcp.tool()
async def create_label(
    name: str, color: str | None = None, org_slug: str | None = None
) -> str:
    """Create a label in an organization so tasks can carry it.

    Args:
        name: Label name, unique within the organization (max 64 chars).
        color: Hex colour in #RRGGBB form, e.g. '#3B82F6'.
        org_slug: Organization slug. Defaults to TEAMFLOW_ORG, or your only org.
    """
    client = _client()
    slug = await client.resolve_org_slug(org_slug)
    body: dict[str, Any] = {"name": name}
    if color:
        body["color"] = color
    label = await client.post(f"/organizations/{slug}/labels", body)
    return json_text({"label": label})


@mcp.tool()
async def get_dashboard(org_slug: str | None = None) -> str:
    """Organization-wide statistics: task counts by status, priority, project and assignee.

    Cheaper than listing tasks when you only need an overview.
    """
    client = _client()
    slug = await client.resolve_org_slug(org_slug)
    stats = await client.get(f"/organizations/{slug}/dashboard")
    return json_text({"organization": slug, "stats": stats})


# ------------------------------------------------------------------ resources


@mcp.resource("teamflow://me")
async def me_resource() -> str:
    """The authenticated TeamFlow user and their organization memberships."""
    return await whoami()


@mcp.resource("teamflow://organizations/{slug}/dashboard")
async def dashboard_resource(slug: str) -> str:
    """Live dashboard statistics for one organization."""
    stats = await _client().get(f"/organizations/{slug}/dashboard")
    return json_text({"organization": slug, "stats": stats})


@mcp.resource("teamflow://projects/{project_id}/board")
async def board_resource(project_id: str) -> str:
    """The current kanban board of a project, addressed by project UUID."""
    return await get_board(project=project_id)


# -------------------------------------------------------------------- prompts


@mcp.prompt()
def daily_standup(project: str = "", org_slug: str = "") -> str:
    """Draft a daily standup summary from the TeamFlow board."""
    target = f"project '{project}'" if project else "the default project"
    where = f" (organization '{org_slug}')" if org_slug else ""
    return (
        f"Produce a daily standup for {target}{where} using the TeamFlow tools.\n\n"
        "1. Call get_board to read every column.\n"
        "2. Call list_tasks with status=['in_progress','in_review'] and sort='-updated_at'.\n"
        "3. Call list_tasks with overdue=True to find at-risk work.\n"
        "4. Call list_tasks with unassigned=True and status=['todo'] to find unowned work.\n\n"
        "Report, in under 200 words: what finished recently, what is in flight and who owns it, "
        "what is blocked or overdue, and what needs an owner. Name task IDs so they can be moved."
    )


@mcp.prompt()
def board_triage(project: str = "", org_slug: str = "") -> str:
    """Review a board and propose concrete next actions."""
    target = f"project '{project}'" if project else "the default project"
    where = f" (organization '{org_slug}')" if org_slug else ""
    return (
        f"Triage {target}{where} and propose actions.\n\n"
        "1. Call get_board, then get_dashboard for the organization.\n"
        "2. For anything stuck in 'in_review' for a while, read get_task to check the last comment.\n"
        "3. Identify: stale in-progress work, overdue tasks, unassigned todo work, and duplicate-looking titles.\n\n"
        "Then, for each recommendation, state the exact tool call you would make "
        "(for example: move_task with status='done' for task <id>). Ask before executing "
        "anything that deletes tasks or reassigns work."
    )


# ----------------------------------------------------------------------- main


async def _check() -> None:
    client = get_client()
    user = await client.me()
    listing = await client.organizations()
    print(f"API        : {client.base_url}")
    print(f"User       : {user['email']} ({user['id']})")
    print(f"Orgs       : {', '.join(o['organization']['slug'] for o in listing) or 'none'}")
    for item in listing:
        slug = item["organization"]["slug"]
        projects = await client.get(f"/organizations/{slug}/projects", limit=100) or []
        names = ", ".join(p["name"] for p in projects) or "no projects"
        print(f"  - {slug} [{item['role']}]: {names}")
    print("OK: credentials work, the MCP server can log in.")


def main() -> None:
    if "--check" in sys.argv[1:]:
        try:
            asyncio.run(_check())
        except TeamFlowError as exc:
            print(f"FAILED: {exc}", file=sys.stderr)
            raise SystemExit(1) from None
        return
    mcp.run()


if __name__ == "__main__":
    main()
