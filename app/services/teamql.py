"""TeamQL: a small query language over task fields.

Grammar (case-insensitive keywords, quoted values, `AND` between conditions):

    status in (todo, in_progress) AND priority = high AND assignee = me
    sprint = "Sprint 4" AND label = bug AND due < 2026-11-01
    text ~ "login timeout" ORDER BY priority DESC

Supported fields: project, status, priority, type, assignee, label, sprint,
text/q, key, estimate, due, created, updated, archived, parent, roots.
Operators: =, !=, >, >=, <, <=, ~ (full-text), in, not in, is empty,
is not empty.

The parser is pure (no DB access): callers preload lookup maps (member emails,
label names, sprint names) and the resolved `me` user id.
"""

import re
import uuid
from datetime import UTC, datetime, time, timedelta

from app.core.exceptions import ValidationFailedError
from app.models import TaskPriority, TaskStatus, TaskType
from app.repositories import TaskFilters

SORTABLE = {
    "created": "created_at",
    "created_at": "created_at",
    "updated": "updated_at",
    "updated_at": "updated_at",
    "due": "due_date",
    "due_date": "due_date",
    "priority": "priority",
    "status": "status",
    "title": "title",
    "estimate": "estimate",
    "number": "number",
    "key": "key",
    "rank": "backlog_rank",
    "backlog_rank": "backlog_rank",
}

ORDER_BY_RE = re.compile(r"\border\s+by\s+([a-z_]+)(?:\s+(asc|desc))?\s*$", re.IGNORECASE)
CONDITION_RE = re.compile(
    r"^(?P<field>[a-z_]+)\s*"
    r"(?P<op>not\s+in|is\s+not\s+empty|is\s+empty|in|>=|<=|!=|~|=|>|<)\s*"
    r"(?P<value>.*)$",
    re.IGNORECASE | re.DOTALL,
)


def _split_and(text: str) -> list[str]:
    """Splits on the AND keyword outside quotes/parentheses."""
    parts: list[str] = []
    buffer: list[str] = []
    quote: str | None = None
    depth = 0
    tokens = re.split(r"(\s+)", text)
    index = 0
    while index < len(tokens):
        token = tokens[index]
        stripped = token.strip()
        if quote is None and depth == 0 and stripped.lower() == "and":
            parts.append("".join(buffer).strip())
            buffer = []
            index += 1
            continue
        for char in token:
            if quote:
                if char == quote:
                    quote = None
            elif char in ("'", '"'):
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth = max(0, depth - 1)
        buffer.append(token)
        index += 1
    parts.append("".join(buffer).strip())
    return [part for part in parts if part]


def _parse_values(raw: str) -> list[str]:
    value = raw.strip()
    if value.startswith("(") and value.endswith(")"):
        value = value[1:-1]
    values: list[str] = []
    buffer: list[str] = []
    quote: str | None = None
    for char in value:
        if quote:
            if char == quote:
                quote = None
            else:
                buffer.append(char)
        elif char in ("'", '"'):
            quote = char
        elif char == ",":
            entry = "".join(buffer).strip()
            if entry:
                values.append(entry)
            buffer = []
        else:
            buffer.append(char)
    entry = "".join(buffer).strip()
    if entry:
        values.append(entry)
    return values


def _single(values: list[str], field: str) -> str:
    if len(values) != 1:
        raise ValidationFailedError(f"Field '{field}' expects a single value")
    return values[0]


def _as_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _parse_datetime(value: str, *, end_of_day: bool = False) -> datetime:
    lowered = value.lower()
    today = datetime.now(UTC).date()
    if lowered in ("today", "tomorrow", "yesterday"):
        target = {
            "today": today,
            "tomorrow": today + timedelta(days=1),
            "yesterday": today - timedelta(days=1),
        }[lowered]
        moment = time.max if end_of_day else time.min
        return datetime.combine(target, moment, tzinfo=UTC)
    try:
        if len(value) == 10:  # date only
            parsed = datetime.fromisoformat(value)
            moment = time.max if end_of_day else time.min
            return datetime.combine(parsed.date(), moment, tzinfo=UTC)
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        raise ValidationFailedError(f"Invalid date value '{value}'") from None


def _validate_choice(values: list[str], allowed: tuple[str, ...], field: str) -> list[str]:
    lowered = [value.lower() for value in values]
    invalid = [value for value in lowered if value not in allowed]
    if invalid:
        raise ValidationFailedError(
            f"Invalid {field} value(s): {', '.join(invalid)}"
        )
    return lowered


def parse_teamql(
    text: str,
    *,
    me_id: uuid.UUID | None = None,
    members_by_email: dict[str, uuid.UUID] | None = None,
    labels_by_name: dict[str, uuid.UUID] | None = None,
    sprints_by_name: dict[str, uuid.UUID] | None = None,
    custom_fields_by_key: dict[str, uuid.UUID] | None = None,
) -> tuple[TaskFilters, str | None]:
    """Translates a TeamQL string into `(TaskFilters, sort)`.

    Raises `ValidationFailedError` with a human-readable message on bad syntax.
    """
    query = (text or "").strip()
    if not query:
        return TaskFilters(), None
    if len(query) > 2000:
        raise ValidationFailedError("Query is too long (max 2000 characters)")

    sort: str | None = None
    order_match = ORDER_BY_RE.search(query)
    if order_match:
        field = order_match.group(1).lower()
        column = SORTABLE.get(field)
        if column is None:
            raise ValidationFailedError(f"Unknown sort field '{field}'")
        direction = (order_match.group(2) or "asc").lower()
        sort = f"-{column}" if direction == "desc" else column
        query = query[: order_match.start()].strip()

    members_by_email = {k.lower(): v for k, v in (members_by_email or {}).items()}
    labels_by_name = {k.lower(): v for k, v in (labels_by_name or {}).items()}
    sprints_by_name = {k.lower(): v for k, v in (sprints_by_name or {}).items()}
    custom_fields_by_key = {
        k.lower(): v for k, v in (custom_fields_by_key or {}).items()
    }

    kwargs: dict = {}
    for part in _split_and(query):
        match = CONDITION_RE.match(part)
        if not match:
            raise ValidationFailedError(f"Cannot parse condition: '{part}'")
        field = match.group("field").lower()
        op = re.sub(r"\s+", " ", match.group("op").lower())
        raw = match.group("value").strip()
        values = _parse_values(raw) if raw else []
        is_empty = op in ("is empty", "is not empty")
        negative = op in ("!=", "not in", "is not empty")
        if not values and not is_empty:
            raise ValidationFailedError(f"Field '{field}' needs a value")

        if field in ("status",):
            key = "exclude_status" if negative else "status"
            kwargs[key] = _validate_choice(values, TaskStatus.ALL, field)
        elif field == "priority":
            key = "exclude_priority" if negative else "priority"
            kwargs[key] = _validate_choice(values, TaskPriority.ALL, field)
        elif field == "type":
            key = "exclude_type" if negative else "type"
            kwargs[key] = _validate_choice(values, TaskType.ALL, field)
        elif field == "project":
            if negative:
                raise ValidationFailedError("'project' does not support != / not in")
            value = _single(values, field)
            parsed = _as_uuid(value)
            if parsed:
                kwargs["project_id"] = parsed
            else:
                kwargs["project_name"] = value
        elif field == "assignee":
            value = _single(values, field).lower()
            if value in ("me",):
                if me_id is None:
                    raise ValidationFailedError("'assignee = me' requires a signed-in user")
                resolved = me_id
            elif value in ("none", "unassigned", "empty"):
                if negative:
                    raise ValidationFailedError("'assignee != unassigned' is not supported")
                kwargs["unassigned"] = True
                resolved = None
            elif value in members_by_email:
                resolved = members_by_email[value]
            else:
                resolved = _as_uuid(value)
                if resolved is None:
                    raise ValidationFailedError(f"Unknown member '{value}'")
            if resolved is not None:
                key = "exclude_assignee_id" if negative else "assignee_id"
                kwargs[key] = resolved
        elif field == "label":
            value = _single(values, field)
            parsed = _as_uuid(value)
            if parsed:
                resolved = parsed
            elif value.lower() in labels_by_name:
                resolved = labels_by_name[value.lower()]
            else:
                raise ValidationFailedError(f"Unknown label '{value}'")
            key = "exclude_label_id" if negative else "label_id"
            kwargs[key] = resolved
        elif field == "sprint":
            if is_empty:
                kwargs["backlog_only"] = True
            else:
                value = _single(values, field)
                if value.lower() in ("none", "backlog"):
                    kwargs["backlog_only"] = True
                else:
                    parsed = _as_uuid(value)
                    if parsed:
                        kwargs["sprint_id"] = parsed
                    elif value.lower() in sprints_by_name:
                        kwargs["sprint_id"] = sprints_by_name[value.lower()]
                    else:
                        raise ValidationFailedError(f"Unknown sprint '{value}'")
        elif field in ("text", "q", "search"):
            if negative:
                raise ValidationFailedError(f"Field '{field}' does not support negation")
            kwargs["text"] = " ".join(values)
        elif field == "key":
            key = "exclude_keys" if negative else "keys"
            kwargs[key] = values
        elif field == "estimate":
            if is_empty:
                kwargs["estimate_empty"] = True
            else:
                number = _parse_number(_single(values, field), field)
                if op in ("=", ">="):
                    kwargs["estimate_min"] = number
                if op in ("=", "<="):
                    kwargs["estimate_max"] = number
                if op == ">":
                    kwargs["estimate_min"] = number + 0.000001
                if op == "<":
                    kwargs["estimate_max"] = number - 0.000001
        elif field == "due":
            if is_empty:
                kwargs["due_empty"] = True
            else:
                value = _single(values, field)
                if value.lower() == "overdue":
                    kwargs["overdue"] = True
                elif op in ("=",):
                    moment = _parse_datetime(value)
                    kwargs["due_after"] = moment
                    kwargs["due_before"] = _parse_datetime(value, end_of_day=True)
                elif op in ("<", "<="):
                    kwargs["due_before"] = _parse_datetime(value, end_of_day=(op == "<="))
                elif op in (">", ">="):
                    kwargs["due_after"] = _parse_datetime(value)
                else:
                    raise ValidationFailedError(f"Operator '{op}' is not valid for 'due'")
        elif field in ("created", "updated"):
            moment = _parse_datetime(_single(values, field), end_of_day=(op in ("<", "<=")))
            after_key = f"{field}_after"
            before_key = f"{field}_before"
            if op in ("=", ">="):
                kwargs[after_key] = moment
            if op in ("=", "<="):
                kwargs[before_key] = moment
            if op == ">":
                kwargs[after_key] = moment
            if op == "<":
                kwargs[before_key] = moment
            if op not in ("=", ">", "<", ">=", "<="):
                raise ValidationFailedError(f"Operator '{op}' is not valid for '{field}'")
        elif field in ("archived",):
            value = _single(values, field).lower() if values else "true"
            if value in ("true", "yes", "1"):
                kwargs["archived_only"] = True
            elif value in ("false", "no", "0"):
                kwargs["include_archived"] = False
            else:
                raise ValidationFailedError("'archived' expects true or false")
        elif field in ("roots", "root"):
            value = _single(values, field).lower() if values else "true"
            kwargs["roots_only"] = value in ("true", "yes", "1")
        elif field == "parent":
            value = _single(values, field).lower()
            if value in ("none", "empty"):
                kwargs["roots_only"] = True
            else:
                parsed = _as_uuid(value)
                if parsed is None:
                    raise ValidationFailedError("'parent' expects a task UUID or 'none'")
                kwargs["parent_id"] = parsed
        elif field.startswith("cf_"):
            key = field[3:]
            field_id = custom_fields_by_key.get(key)
            if field_id is None:
                raise ValidationFailedError(f"Unknown custom field '{key}'")
            if op not in ("=", "!=", "~"):
                raise ValidationFailedError(
                    f"Custom fields support =, != and ~ (got '{op}')"
                )
            if is_empty:
                raise ValidationFailedError("Custom fields do not support 'is empty'")
            kwargs.setdefault("custom_filters", []).append(
                (field_id, op, " ".join(values))
            )
        else:
            raise ValidationFailedError(f"Unknown field '{field}'")

    return TaskFilters(**kwargs), sort


def _parse_number(value: str, field: str) -> float:
    try:
        return float(value)
    except ValueError:
        raise ValidationFailedError(f"Field '{field}' expects a number") from None
