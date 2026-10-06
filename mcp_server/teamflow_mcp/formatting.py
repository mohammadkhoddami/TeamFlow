"""Payload shaping helpers.

MCP tool results are read by an LLM, so responses are trimmed to the fields
that matter and rendered as indented JSON (readable and unambiguous).

Two projections are used throughout:
  * a *card*  - compact board/list row (description clipped)
  * a *record* - full task detail
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

STATUS_ORDER = ("todo", "in_progress", "in_review", "done")

STATUS_LABELS = {
    "todo": "Todo",
    "in_progress": "In Progress",
    "in_review": "In Review",
    "done": "Done",
}

PRIORITY_RANK = {"urgent": 0, "high": 1, "medium": 2, "low": 3}


def json_text(payload: Any) -> str:
    return json.dumps(payload, indent=2, default=str, ensure_ascii=False)


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def is_overdue(task: dict[str, Any]) -> bool:
    if task.get("status") == "done":
        return False
    due = parse_dt(task.get("due_date"))
    return bool(due and due < datetime.now(timezone.utc))


def _user(user: dict[str, Any] | None) -> str | None:
    if not user:
        return None
    return user.get("email") or user.get("full_name") or None


def _clip(text: str | None, limit: int) -> str | None:
    if not text:
        return None
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    return flat[: limit - 1].rstrip() + "\u2026"


def label_names(task: dict[str, Any]) -> list[str]:
    return [label.get("name", "") for label in task.get("labels") or [] if label]


def task_card(task: dict[str, Any], description_chars: int = 240) -> dict[str, Any]:
    """Compact representation for boards and lists."""
    card: dict[str, Any] = {
        "id": task.get("id"),
        "key": task.get("key"),
        "title": task.get("title"),
        "type": task.get("type") or "task",
        "status": task.get("status"),
        "priority": task.get("priority"),
        "project_id": task.get("project_id"),
        "parent_id": task.get("parent_id"),
        "assignee": _user(task.get("assignee")) or task.get("assignee_id"),
        "due_date": task.get("due_date"),
        "labels": label_names(task),
        "updated_at": task.get("updated_at"),
    }
    if task.get("estimate") is not None:
        card["estimate"] = task.get("estimate")
    if task.get("sprint_name"):
        card["sprint"] = task.get("sprint_name")
    if task.get("child_count"):
        card["children"] = f"{task.get('done_child_count', 0)}/{task['child_count']} done"
    if is_overdue(task):
        card["overdue"] = True
    snippet = _clip(task.get("description"), description_chars)
    if snippet:
        card["description"] = snippet
    return card


def task_record(task: dict[str, Any]) -> dict[str, Any]:
    """Full representation for single-task reads."""
    record = task_card(task, description_chars=20_000)
    record.pop("description", None)
    record["description"] = task.get("description")
    record["organization_id"] = task.get("organization_id")
    record["creator"] = _user(task.get("creator")) or task.get("created_by_id")
    parent = task.get("parent")
    if parent:
        record["parent"] = {
            "id": parent.get("id"),
            "title": parent.get("title"),
            "type": parent.get("type"),
            "status": parent.get("status"),
        }
    record["child_count"] = task.get("child_count") or 0
    record["done_child_count"] = task.get("done_child_count") or 0
    record["completed_at"] = task.get("completed_at")
    record["created_at"] = task.get("created_at")
    record["watcher_ids"] = task.get("watcher_ids") or []
    return record


def sort_cards(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Urgent/overdue first, then by most recent update."""
    return sorted(
        cards,
        key=lambda c: (
            0 if c.get("overdue") else 1,
            PRIORITY_RANK.get(c.get("priority") or "", 9),
            -(parse_dt(c.get("updated_at")) or datetime.min.replace(tzinfo=timezone.utc)).timestamp(),
        ),
    )


def comment_item(comment: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": comment.get("id"),
        "author": _user(comment.get("author")) or comment.get("author_id"),
        "body": comment.get("body"),
        "created_at": comment.get("created_at"),
        "updated_at": comment.get("updated_at"),
    }
