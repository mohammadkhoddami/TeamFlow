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
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer

from .client import TeamFlowError, get_client
from .config import describe_sources, get_settings
from .formatting import (
    STATUS_LABELS,
    STATUS_ORDER,
    comment_item,
    json_text,
    parse_dt,
    sort_cards,
    task_card,
    task_record,
)

Priority = Literal["low", "medium", "high", "urgent"]
TaskType = Literal["epic", "story", "task"]

DEFAULT_WORKFLOW: list[dict[str, Any]] = [
    {
        "key": "todo",
        "name": "To do",
        "category": "todo",
        "position": 0,
        "wip_limit": None,
        "transitions": ["in_progress"],
    },
    {
        "key": "in_progress",
        "name": "In progress",
        "category": "in_progress",
        "position": 1,
        "wip_limit": None,
        "transitions": ["todo", "in_review"],
    },
    {
        "key": "in_review",
        "name": "In review",
        "category": "in_review",
        "position": 2,
        "wip_limit": None,
        "transitions": ["in_progress", "done"],
    },
    {
        "key": "done",
        "name": "Done",
        "category": "done",
        "position": 3,
        "wip_limit": None,
        "transitions": ["in_progress"],
    },
]

ROADMAP_EPIC_LIMIT = 30
ROADMAP_CHILD_LIMIT = 5
GOAL_TASK_LIMIT = 25

mcp = MCPServer(
    "teamflow",
    instructions=(
        "TeamFlow is a multi-tenant project management board. Each project defines "
        "its own workflow of statuses; the default is 'todo', 'in_progress', "
        "'in_review', 'done' but managers can add custom statuses and decide which "
        "moves are allowed between them.\n\n"
        "Typical flow: call whoami() to confirm the account and defaults, then "
        "get_board() to see the current board (columns, allowed transitions and a "
        "saved board's filters), then list_tasks()/get_task() to drill in and "
        "create_task()/update_task()/move_task() to make changes.\n\n"
        "Argument conventions:\n"
        "- `project` accepts a project name or UUID (default: TEAMFLOW_PROJECT).\n"
        "- `org_slug` defaults to TEAMFLOW_ORG, or your only organization.\n"
        "- `assignee` accepts 'me', an email address, or a user UUID.\n"
        "- `labels` accept label names or UUIDs.\n\n"
        "Work items form an epic > story > task hierarchy: create_task() takes\n"
        "`type` and `parent_id`, and get_task_tree() renders the whole project\n"
        "tree. A parent must be a higher level in the same project.\n\n"
        "Status moves follow the project workflow: call get_board() first to see "
        "each column's allowed transitions, and move_task() rejects moves that "
        "are not allowed."
    ),
)


def _client():
    try:
        return get_client()
    except Exception as exc:  # pragma: no cover - configuration guard
        raise TeamFlowError(f"TeamFlow MCP is not configured: {exc}") from exc


async def _fetch_workflow(client, project_id: str) -> list[dict[str, Any]]:
    """The project's workflow statuses (defaults are synthesized by the API)."""
    workflow = await client.get(f"/projects/{project_id}/workflow")
    return list(workflow or [])


def _workflow_entry(
    workflow: list[dict[str, Any]], status_key: str | None
) -> dict[str, Any] | None:
    for entry in workflow:
        if entry.get("key") == status_key:
            return entry
    return None


def _workflow_transitions(
    workflow: list[dict[str, Any]], status_key: str | None
) -> list[str]:
    entry = _workflow_entry(workflow, status_key)
    if entry is None:
        return []
    return list(entry.get("transitions") or [])


def _allowed_next(workflow: list[dict[str, Any]], status_key: str | None) -> str:
    return " | ".join(_workflow_transitions(workflow, status_key))


async def _resolve_board(client, project_id: str, board: str) -> dict[str, Any]:
    boards = await client.get(f"/projects/{project_id}/boards") or []
    needle = board.strip().lower()
    for entry in boards:
        if entry.get("id") == board or (entry.get("name") or "").lower() == needle:
            return entry
    names = ", ".join(entry.get("name", "") for entry in boards) or "none"
    raise TeamFlowError(f"Board '{board}' not found. Available boards: {names}.")


def _ordered_statuses(workflow: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(workflow, key=lambda entry: entry.get("position", 0))


def _release_item(release: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": release.get("id"),
        "name": release.get("name"),
        "version": release.get("version"),
        "status": release.get("status"),
        "release_date": release.get("release_date"),
        "task_count": release.get("task_count", 0),
        "done_task_count": release.get("done_task_count", 0),
    }


def _calendar_window(start: str | None, end: str | None) -> dict[str, str]:
    """Default the window to the month containing `start` (or now), UTC."""
    anchor = parse_dt(start) or datetime.now(timezone.utc)
    if not start:
        start = anchor.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        ).isoformat()
    if not end:
        first = anchor.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = (first + timedelta(days=32)).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        ).isoformat()
    return {"start": start, "end": end}


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
    board: str | None = None,
    per_column: int = 25,
    assignee: str | None = None,
    label: str | None = None,
) -> str:
    """Show the kanban board for a project: every column with its real task count and top cards.

    This is the best first call when you need the state of a project. Columns
    follow the project workflow (custom statuses included) and each column
    reports its allowed next statuses. Cards are ordered with overdue first,
    then by priority, then most recently updated.

    Args:
        project: Project name or UUID. Defaults to TEAMFLOW_PROJECT.
        org_slug: Organization slug. Defaults to TEAMFLOW_ORG, or your only org.
        board: Optional saved board name or UUID. Defaults to the project's
            default board when one exists; pass "all" to ignore saved boards.
            A saved board can hide issue types, hide status columns and apply
            its own TeamQL filter.
        per_column: How many cards to return per column (1-100). Counts stay accurate.
        assignee: Only cards assigned to this user ('me', email, or UUID).
        label: Only cards carrying this label name.
    """
    client = _client()
    slug, project_data = await client.resolve_project(project, org_slug)
    project_id = project_data["id"]
    workflow = await _fetch_workflow(client, project_id) or list(DEFAULT_WORKFLOW)
    ordered = _ordered_statuses(workflow)

    selected_board: dict[str, Any] | None = None
    if board and board.strip().lower() not in ("all", "none"):
        selected_board = await _resolve_board(client, project_id, board)
    elif not board:
        boards = await client.get(f"/projects/{project_id}/boards") or []
        selected_board = next(
            (entry for entry in boards if entry.get("is_default")), None
        )

    visible_keys = [entry["key"] for entry in ordered]
    issue_types: list[str] | None = None
    board_filter = ""
    if selected_board:
        if selected_board.get("columns"):
            allowed = set(selected_board["columns"])
            visible_keys = [key for key in visible_keys if key in allowed]
        issue_types = selected_board.get("issue_types") or None
        board_filter = (selected_board.get("filter_query") or "").strip()

    assignee_id = await client.resolve_user_id(assignee, slug)
    label_id = (await client.resolve_labels([label], slug) or [None])[0] if label else None
    depth = max(1, min(int(per_column), 100))

    def build_query(status_key: str) -> str:
        conditions = [f"status = {status_key}", f"project = {project_id}"]
        if issue_types:
            conditions.append(f"type in ({', '.join(issue_types)})")
        if assignee_id:
            conditions.append(f"assignee = {assignee_id}")
        if label_id:
            conditions.append(f"label = {label_id}")
        if board_filter:
            conditions.append(board_filter)
        return " AND ".join(conditions)

    async def column(status_key: str) -> dict[str, Any]:
        page = (
            await client.get(
                f"/organizations/{slug}/tasks/query",
                q=build_query(status_key),
                limit=depth,
            )
        ) or {}
        cards = sort_cards([task_card(t) for t in page.get("items") or []])
        total = int(page.get("total") or 0)
        entry = _workflow_entry(workflow, status_key) or {}
        column_payload: dict[str, Any] = {
            "status": status_key,
            "column": entry.get("name") or status_key,
            "category": entry.get("category"),
            "wip_limit": entry.get("wip_limit"),
            "transitions": list(entry.get("transitions") or []),
            "count": total,
            "cards": cards,
        }
        if total > len(cards):
            column_payload["truncated"] = f"{total - len(cards)} more not shown"
        return column_payload

    columns = list(await asyncio.gather(*(column(key) for key in visible_keys)))
    open_tasks = sum(
        c["count"] for c in columns if c.get("category") != "done"
    )

    payload: dict[str, Any] = {
        "organization": slug,
        "project": {
            "id": project_id,
            "name": project_data["name"],
            "status": project_data["status"],
        },
        "filters": {"assignee": assignee, "label": label, "per_column": depth},
        "open_tasks": open_tasks,
        "columns": columns,
    }
    if selected_board:
        payload["board"] = {
            "name": selected_board.get("name"),
            "issue_types": issue_types or "all",
            "filter_query": board_filter or None,
            "hidden_columns": [
                entry["key"]
                for entry in ordered
                if entry["key"] not in set(visible_keys)
            ],
        }
    else:
        payload["board"] = None
    return json_text(payload)


@mcp.tool()
async def list_tasks(
    project: str | None = None,
    org_slug: str | None = None,
    status: list[str] | None = None,
    priority: list[Priority] | None = None,
    type: list[TaskType] | None = None,
    parent_id: str | None = None,
    roots_only: bool = False,
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
        status: One or more workflow status keys (custom project statuses allowed).
        priority: One or more of low, medium, high, urgent.
        type: One or more of epic, story, task.
        parent_id: Only direct children of this task UUID.
        roots_only: Only top-level tasks (no parent).
        assignee: 'me', an email address, or a user UUID.
        unassigned: Only tasks with no assignee.
        label: Label name or UUID.
        search: Free-text match on title/description (max 100 chars).
        overdue: Only tasks past their due date and not done.
        due_before: ISO-8601 datetime upper bound on due date.
        due_after: ISO-8601 datetime lower bound on due date.
        sort: Sortable field, prefix '-' for descending. One of created_at,
            updated_at, title, priority, status, due_date, type (e.g. '-due_date').
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
        "type": type,
        "parent_id": parent_id,
        "roots_only": roots_only,
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
    children = await client.get(f"/tasks/{task_id}/children") or []
    payload["children"] = [task_card(child) for child in children]
    if include_comments:
        comments = await client.get(f"/tasks/{task_id}/comments", limit=100) or []
        payload["comments"] = [comment_item(c) for c in comments]
    workflow = await _fetch_workflow(client, task["project_id"])
    payload["allowed_next_status"] = _allowed_next(workflow, task.get("status"))
    return json_text(payload)


@mcp.tool()
async def get_task_tree(project: str | None = None, org_slug: str | None = None) -> str:
    """Show a project's epic > story > task hierarchy as a nested tree.

    Use this to understand how work is broken down: epics contain stories,
    stories contain tasks (a task may also sit directly under an epic). Each
    node reports the child progress as `done/total`.

    Args:
        project: Project name or UUID. Defaults to TEAMFLOW_PROJECT.
        org_slug: Organization slug. Defaults to TEAMFLOW_ORG, or your only org.
    """
    client = _client()
    slug, project_data = await client.resolve_project(project, org_slug)
    roots = await client.get(f"/projects/{project_data['id']}/tasks/tree") or []

    def node(item: dict[str, Any]) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "id": item.get("id"),
            "title": item.get("title"),
            "type": item.get("type"),
            "status": item.get("status"),
            "priority": item.get("priority"),
        }
        assignee = item.get("assignee") or {}
        if assignee:
            entry["assignee"] = assignee.get("email") or assignee.get("full_name")
        children = item.get("children") or []
        if children:
            entry["progress"] = (
                f"{item.get('done_child_count', 0)}/{item.get('child_count', 0)} children done"
            )
            entry["children"] = [node(child) for child in children]
        return entry

    return json_text(
        {
            "organization": slug,
            "project": {"id": project_data["id"], "name": project_data["name"]},
            "roots": len(roots),
            "tree": [node(root) for root in roots],
        }
    )


@mcp.tool()
async def create_task(
    title: str,
    project: str | None = None,
    org_slug: str | None = None,
    description: str | None = None,
    priority: Priority = "medium",
    type: TaskType = "task",
    parent_id: str | None = None,
    due_date: str | None = None,
    assignee: str | None = None,
    labels: list[str] | None = None,
) -> str:
    """Create a task on a project board. New tasks start in the project's initial
    workflow status ('todo' by default).

    Args:
        title: Short task title (required, max 255 chars).
        project: Project name or UUID. Defaults to TEAMFLOW_PROJECT.
        org_slug: Organization slug. Defaults to TEAMFLOW_ORG, or your only org.
        description: Markdown body (max 20,000 chars).
        priority: low, medium, high, or urgent.
        type: epic, story, or task (default).
        parent_id: UUID of the parent work item. A story nests under an epic;
            a task nests under a story or directly under an epic. The parent
            must be in the same project.
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
        "type": type,
        "due_date": due_date,
    }
    if parent_id:
        body["parent_id"] = parent_id
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
            "hint": (
                "New tasks start in the project's initial workflow status "
                "('todo' by default). Use get_board to see columns and "
                "move_task to advance them."
            ),
        }
    )


@mcp.tool()
async def update_task(
    task_id: str,
    title: str | None = None,
    description: str | None = None,
    priority: Priority | None = None,
    type: TaskType | None = None,
    parent_id: str | None = None,
    clear_parent: bool = False,
    due_date: str | None = None,
    clear_due_date: bool = False,
    assignee: str | None = None,
    labels: list[str] | None = None,
    status: str | None = None,
) -> str:
    """Update fields on an existing task. Only the arguments you pass are changed.

    Args:
        task_id: Task UUID.
        title: New title.
        description: New markdown body (replaces the old one).
        priority: low, medium, high, or urgent.
        type: epic, story, or task. Must keep parents higher-level than children.
        parent_id: UUID of a new parent work item in the same project.
        clear_parent: Set true to detach the task from its parent.
        due_date: New ISO-8601 due date, e.g. '2026-10-01T17:00:00Z'.
        clear_due_date: Set true to remove the due date. Overrides due_date.
        assignee: 'me', a member email, a user UUID, or 'unassigned' to clear it.
        labels: Replace the task's labels with this set (names or UUIDs). Pass an
            empty list to remove all labels.
        status: Move to this workflow status key. Moves follow the project
            workflow; prefer move_task for pure status changes.
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
    if type is not None:
        body["type"] = type
    if clear_parent:
        body["parent_id"] = None
    elif parent_id is not None:
        body["parent_id"] = parent_id
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

    workflow = await _fetch_workflow(client, current["project_id"])
    if status is not None:
        keys = {entry.get("key") for entry in workflow}
        if current.get("status") in keys and status != current.get("status"):
            allowed = _workflow_transitions(workflow, current.get("status"))
            if status not in allowed:
                raise TeamFlowError(
                    f"Cannot move task from '{current.get('status')}' to "
                    f"'{status}'. Allowed: {', '.join(allowed) or 'none'}."
                )
        body["status"] = status

    if not body:
        raise TeamFlowError("Nothing to update - pass at least one field.")

    task = await client.patch(f"/tasks/{task_id}", body)
    return json_text(
        {
            "updated": task_record(task),
            "changed": sorted(body),
            "allowed_next_status": _allowed_next(workflow, task.get("status")),
        }
    )


@mcp.tool()
async def move_task(task_id: str, status: str, note: str | None = None) -> str:
    """Move a task to a new column, optionally logging a comment explaining why.

    Moves follow the project workflow; get_board reports each column's allowed
    next statuses. Moves that are not allowed are rejected.

    Args:
        task_id: Task UUID.
        status: Target workflow status key (e.g. todo, in_progress, in_review,
            done, or a custom project status).
        note: Optional comment posted on the task after the move.
    """
    client = _client()
    task = await client.get(f"/tasks/{task_id}")
    workflow = await _fetch_workflow(client, task["project_id"])
    current = task.get("status")
    if _workflow_entry(workflow, current) is not None and status != current:
        allowed = _workflow_transitions(workflow, current)
        if status not in allowed:
            raise TeamFlowError(
                f"Cannot move task from '{current}' to '{status}'. "
                f"Allowed: {', '.join(allowed) or 'none'}."
            )
    moved = await client.post(f"/tasks/{task_id}/move", {"status": status})
    payload: dict[str, Any] = {
        "moved": task_record(moved),
        "allowed_next_status": _allowed_next(workflow, moved.get("status")),
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
    status: list[str] | None = None,
    limit: int = 50,
) -> str:
    """Everything assigned to me, grouped by column - use this for standups and reminders.

    Args:
        org_slug: Organization slug. Defaults to TEAMFLOW_ORG, or your only org.
        status: Restrict to these workflow status keys (custom statuses allowed).
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

    grouped: dict[str, list[dict[str, Any]]] = {}
    for task in page.get("items") or []:
        grouped.setdefault(task["status"], []).append(task_card(task))

    # Default columns first, then any custom statuses that showed up.
    ordered = [s for s in STATUS_ORDER if s in grouped] + [
        s for s in grouped if s not in STATUS_ORDER
    ]
    return json_text(
        {
            "user": me["email"],
            "organization": slug,
            "assigned_total": page.get("total", 0),
            "columns": [
                {
                    "status": s,
                    "column": STATUS_LABELS.get(s, s),
                    "count": len(grouped.get(s) or []),
                    "cards": sort_cards(grouped.get(s) or []),
                }
                for s in ordered
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


@mcp.tool()
async def list_sprints(project: str | None = None, org_slug: str | None = None) -> str:
    """List a project's sprints with their schedule and progress.

    Each entry has its state (planned, active, completed), dates, and how many
    of its tasks are done. Read this before planning work so new tasks fit the
    current sprint.

    Args:
        project: Project name or UUID. Defaults to TEAMFLOW_PROJECT.
        org_slug: Organization slug. Defaults to TEAMFLOW_ORG, or your only org.
    """
    client = _client()
    slug, project_data = await client.resolve_project(project, org_slug)
    sprints = await client.get(f"/projects/{project_data['id']}/sprints") or []
    return json_text(
        {
            "organization": slug,
            "project": {"id": project_data["id"], "name": project_data["name"]},
            "count": len(sprints),
            "sprints": [
                {
                    "id": sprint["id"],
                    "name": sprint["name"],
                    "state": sprint.get("state"),
                    "start_date": sprint.get("start_date"),
                    "end_date": sprint.get("end_date"),
                    "task_count": sprint.get("task_count", 0),
                    "done_task_count": sprint.get("done_task_count", 0),
                }
                for sprint in sprints
            ],
        }
    )


@mcp.tool()
async def list_releases(project: str | None = None, org_slug: str | None = None) -> str:
    """List a project's releases with version, status and progress.

    A release groups tasks shipped together; `task_count` minus
    `done_task_count` is the work still open before `release_date`. Statuses
    are planned, in_progress, released and cancelled.

    Args:
        project: Project name or UUID. Defaults to TEAMFLOW_PROJECT.
        org_slug: Organization slug. Defaults to TEAMFLOW_ORG, or your only org.
    """
    client = _client()
    slug, project_data = await client.resolve_project(project, org_slug)
    releases = await client.get(f"/projects/{project_data['id']}/releases") or []
    return json_text(
        {
            "organization": slug,
            "project": {"id": project_data["id"], "name": project_data["name"]},
            "count": len(releases),
            "releases": [_release_item(release) for release in releases],
        }
    )


@mcp.tool()
async def get_roadmap(project: str | None = None, org_slug: str | None = None) -> str:
    """Show a project's roadmap: releases plus epics with their top child tasks.

    One compact read of the delivery plan: every release with its progress,
    then each epic with dates, task counts and up to five child task titles.
    Use get_task_tree when you need the complete hierarchy.

    Args:
        project: Project name or UUID. Defaults to TEAMFLOW_PROJECT.
        org_slug: Organization slug. Defaults to TEAMFLOW_ORG, or your only org.
    """
    client = _client()
    slug, project_data = await client.resolve_project(project, org_slug)
    data = await client.get(f"/projects/{project_data['id']}/roadmap") or {}
    epics = data.get("epics") or []

    def epic_item(epic: dict[str, Any]) -> dict[str, Any]:
        children = epic.get("children") or []
        item: dict[str, Any] = {
            "id": epic.get("id"),
            "key": epic.get("key"),
            "title": epic.get("title"),
            "status": epic.get("status"),
            "priority": epic.get("priority"),
            "start_date": epic.get("start_date"),
            "due_date": epic.get("due_date"),
            "task_count": epic.get("task_count", 0),
            "done_task_count": epic.get("done_task_count", 0),
            "children": [c.get("title") for c in children[:ROADMAP_CHILD_LIMIT]],
        }
        if len(children) > ROADMAP_CHILD_LIMIT:
            item["children_hidden"] = len(children) - ROADMAP_CHILD_LIMIT
        return item

    payload: dict[str, Any] = {
        "organization": slug,
        "project": {"id": project_data["id"], "name": project_data["name"]},
        "releases": [_release_item(r) for r in data.get("releases") or []],
        "epics": [epic_item(epic) for epic in epics[:ROADMAP_EPIC_LIMIT]],
    }
    if len(epics) > ROADMAP_EPIC_LIMIT:
        payload["epics_hidden"] = len(epics) - ROADMAP_EPIC_LIMIT
    unassigned = data.get("unassigned") or []
    if unassigned:
        payload["unassigned_count"] = len(unassigned)
    return json_text(payload)


@mcp.tool()
async def get_calendar(
    start: str | None = None,
    end: str | None = None,
    project: str | None = None,
    org_slug: str | None = None,
    assignee: str | None = None,
) -> str:
    """List tasks with due dates inside a date window (defaults to this month).

    Org-wide unless `project` is passed. `start` is inclusive and `end`
    exclusive; both accept ISO-8601 (e.g. '2026-10-01T00:00:00Z'). Pair with
    list_tasks overdue=True to separate late work from upcoming work.

    Args:
        start: ISO-8601 window start (inclusive). Defaults to the 1st of this month.
        end: ISO-8601 window end (exclusive). Defaults to the 1st of next month.
        project: Optional project name or UUID to narrow the calendar.
        org_slug: Organization slug. Defaults to TEAMFLOW_ORG, or your only org.
        assignee: Optional 'me', member email, or user UUID filter.
    """
    client = _client()
    slug = await client.resolve_org_slug(org_slug)
    window = _calendar_window(start, end)
    project_id = None
    if project:
        _slug, project_data = await client.resolve_project(project, org_slug)
        project_id = project_data["id"]
    data = (
        await client.get(
            f"/organizations/{slug}/calendar",
            start=window["start"],
            end=window["end"],
            project_id=project_id,
            assignee=await client.resolve_user_id(assignee, slug),
        )
    ) or {}
    tasks = data.get("tasks") or []
    return json_text(
        {
            "organization": slug,
            "window": {"start": data.get("start"), "end": data.get("end")},
            "count": len(tasks),
            "tasks": [
                {
                    "id": t.get("id"),
                    "key": t.get("key"),
                    "title": t.get("title"),
                    "due_date": t.get("due_date"),
                    "status": t.get("status"),
                    "priority": t.get("priority"),
                    "project": t.get("project_name"),
                    "assignee": (t.get("assignee") or {}).get("email"),
                }
                for t in tasks
            ],
        }
    )


@mcp.tool()
async def list_automations(org_slug: str | None = None) -> str:
    """List an organization's automation rules and how often they have run.

    Shows what already fires automatically on the board (`trigger_type`),
    whether each rule is enabled, and its run count/last run - useful before
    proposing manual steps for recurring work.

    Args:
        org_slug: Organization slug. Defaults to TEAMFLOW_ORG, or your only org.
    """
    client = _client()
    slug = await client.resolve_org_slug(org_slug)
    rules = await client.get(f"/organizations/{slug}/automations") or []
    return json_text(
        {
            "organization": slug,
            "count": len(rules),
            "automations": [
                {
                    "id": rule["id"],
                    "name": rule["name"],
                    "is_active": rule.get("is_active"),
                    "trigger_type": rule.get("trigger_type"),
                    "run_count": rule.get("run_count", 0),
                    "last_run_at": rule.get("last_run_at"),
                }
                for rule in rules
            ],
        }
    )


@mcp.tool()
async def list_goals(org_slug: str | None = None) -> str:
    """List organization goals/OKRs with progress and the keys of linked tasks.

    `progress_pct` rolls up the completion of the linked tasks; `task_keys`
    can be passed to get_task. Goals are organization-wide, not per project.

    Args:
        org_slug: Organization slug. Defaults to TEAMFLOW_ORG, or your only org.
    """
    client = _client()
    slug = await client.resolve_org_slug(org_slug)
    goals = await client.get(f"/organizations/{slug}/goals") or []
    payload: list[dict[str, Any]] = []
    for goal in goals:
        tasks = goal.get("tasks") or []
        keys = [t.get("key") or t.get("title") for t in tasks]
        entry: dict[str, Any] = {
            "id": goal["id"],
            "name": goal.get("name"),
            "status": goal.get("status"),
            "due_date": goal.get("due_date"),
            "progress_pct": goal.get("progress_pct", 0),
            "task_keys": keys[:GOAL_TASK_LIMIT],
        }
        if len(keys) > GOAL_TASK_LIMIT:
            entry["task_keys_hidden"] = len(keys) - GOAL_TASK_LIMIT
        payload.append(entry)
    return json_text({"organization": slug, "count": len(goals), "goals": payload})


@mcp.tool()
async def list_forms(project: str | None = None, org_slug: str | None = None) -> str:
    """List a project's intake forms with visibility and submission counts.

    A form turns external submissions into tasks; `slug` is the public path it
    is shared by, and `submit_count` shows how many tasks it has created.

    Args:
        project: Project name or UUID. Defaults to TEAMFLOW_PROJECT.
        org_slug: Organization slug. Defaults to TEAMFLOW_ORG, or your only org.
    """
    client = _client()
    slug, project_data = await client.resolve_project(project, org_slug)
    forms = await client.get(f"/projects/{project_data['id']}/forms") or []
    return json_text(
        {
            "organization": slug,
            "project": {"id": project_data["id"], "name": project_data["name"]},
            "count": len(forms),
            "forms": [
                {
                    "id": form["id"],
                    "name": form.get("name"),
                    "slug": form.get("slug"),
                    "is_public": form.get("is_public"),
                    "submit_count": form.get("submit_count", 0),
                }
                for form in forms
            ],
        }
    )


@mcp.tool()
async def list_dashboards(org_slug: str | None = None) -> str:
    """List saved organization dashboards with their widget types.

    `widget_types` shows what each dashboard summarizes (stats, status,
    members, overdue, activity) and `is_default` marks the one to open first.
    Use get_dashboard for live org-wide numbers instead.

    Args:
        org_slug: Organization slug. Defaults to TEAMFLOW_ORG, or your only org.
    """
    client = _client()
    slug = await client.resolve_org_slug(org_slug)
    dashboards = await client.get(f"/organizations/{slug}/dashboards") or []
    return json_text(
        {
            "organization": slug,
            "count": len(dashboards),
            "dashboards": [
                {
                    "id": dashboard["id"],
                    "name": dashboard.get("name"),
                    "is_default": dashboard.get("is_default"),
                    "widget_types": [
                        widget.get("type") for widget in dashboard.get("widgets") or []
                    ],
                }
                for dashboard in dashboards
            ],
        }
    )


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


def _mask_email(value: str) -> str:
    """Keep the domain (useful for diagnosis) but not the full local part."""
    local, _, domain = value.partition("@")
    if not domain:
        return "***"
    if len(local) <= 2:
        masked = f"{local[:1]}***"
    else:
        masked = f"{local[0]}***{local[-1]}"
    return f"{masked}@{domain}"


async def _check() -> None:
    sources = describe_sources()
    print(f"Working dir: {sources['cwd']}")
    print(f"  project env: {sources['project_env_file'] or '(none found)'}"
          f"{'' if sources['project_env_file_exists'] else '  [does not exist]'}")
    print(f"  shared env : {sources['shared_env_file'] or '(none)'}")
    if sources["env_file_override"]:
        print(f"  override   : {sources['env_file_override']}")
    if sources["credentials_from_process_env"]:
        print("  credentials: from process environment (not from a file)")

    settings = get_settings()
    if settings.org:
        print(f"  default org: {settings.org}")

    client = get_client()
    user = await client.me()
    listing = await client.organizations()
    print(f"API        : {client.base_url}")
    print(f"User       : {_mask_email(user['email'])} ({user['id']})")
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
