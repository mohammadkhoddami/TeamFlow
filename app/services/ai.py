"""Heuristic work breakdown (M4 "AI", no external API).

Parses lightweight markdown into an epic > story > task proposal:

  - `#` headings become epics; `##`+ headings become stories (children of the
    nearest epic, or top-level stories when no epic exists)
  - bullet / numbered list items become tasks under the current heading
  - with no headings, bullets become top-level tasks
  - blank input -> provided=False, items=[]

Also provides a keyword-based `suggest_priority` used to pre-fill proposals.
"""

import re
from typing import Any

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.+?)\s*$")

URGENT_WORDS = (
    "urgent",
    "asap",
    "critical",
    "blocker",
    "immediately",
    "emergency",
    "outage",
    "production down",
    "p0",
)
HIGH_WORDS = (
    "important",
    "high priority",
    "deadline",
    "must",
    "priority",
    "p1",
    "soon",
)
LOW_WORDS = (
    "low priority",
    "minor",
    "trivial",
    "nice to have",
    "someday",
    "whenever",
    "optional",
)

MAX_TITLE = 255


def suggest_priority(text: str) -> str:
    """Keyword heuristic: urgent > high > low > medium (first match wins)."""
    haystack = (text or "").lower()
    if any(word in haystack for word in URGENT_WORDS):
        return "urgent"
    if any(word in haystack for word in HIGH_WORDS):
        return "high"
    if any(word in haystack for word in LOW_WORDS):
        return "low"
    return "medium"


def _node(title: str, item_type: str) -> dict[str, Any]:
    title = " ".join((title or "").split())
    return {
        "title": title[:MAX_TITLE],
        "type": item_type,
        "priority": suggest_priority(title),
        "children": [],
    }


def breakdown(description: str) -> dict[str, Any]:
    text = (description or "").strip()
    if not text:
        return {"provided": False, "items": [], "suggested_priority": "medium"}

    items: list[dict[str, Any]] = []
    loose: list[dict[str, Any]] = []
    paragraphs: list[str] = []
    current_epic: dict[str, Any] | None = None
    current_story: dict[str, Any] | None = None
    saw_heading = False

    for line in text.splitlines():
        heading = HEADING_RE.match(line)
        if heading:
            saw_heading = True
            level = len(heading.group(1))
            title = heading.group(2).strip()
            if not title:
                continue
            node = _node(title, "epic" if level == 1 else "story")
            if level == 1:
                items.append(node)
                current_epic = node
                current_story = None
            elif current_epic is not None:
                current_epic["children"].append(node)
                current_story = node
            else:
                items.append(node)
                current_story = node
            continue

        bullet = BULLET_RE.match(line)
        if bullet:
            title = bullet.group(1).strip()
            if not title:
                continue
            child = _node(title, "task")
            parent = current_story or current_epic
            if parent is not None:
                parent["children"].append(child)
            else:
                loose.append(child)
        elif line.strip():
            paragraphs.append(line.strip())

    if not saw_heading:
        items = loose
        if not items and paragraphs:
            # Plain prose still yields one actionable task.
            items = [_node(paragraphs[0], "task")]
        return {
            "provided": True,
            "items": items,
            "suggested_priority": suggest_priority(text),
        }

    return {
        "provided": True,
        "items": items + loose,
        "suggested_priority": suggest_priority(text),
    }
