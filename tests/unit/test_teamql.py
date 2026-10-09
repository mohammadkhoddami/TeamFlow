"""Unit tests: TeamQL parser (pure, no database)."""

import uuid

import pytest

from app.core.exceptions import ValidationFailedError
from app.services.teamql import parse_teamql

ME = uuid.uuid4()
BOB = uuid.uuid4()
LABEL = uuid.uuid4()
SPRINT = uuid.uuid4()
PROJECT = uuid.uuid4()

LOOKUPS = {
    "me_id": ME,
    "members_by_email": {"bob@example.com": BOB},
    "labels_by_name": {"bug": LABEL},
    "sprints_by_name": {"sprint 4": SPRINT},
}


def test_empty_query_is_noop():
    filters, sort = parse_teamql("")
    assert sort is None
    # Only the implicit "not archived" guard remains.
    assert len(filters.conditions()) == 1
    assert filters.status is None
    assert filters.assignee_id is None


def test_status_and_priority_lists():
    filters, sort = parse_teamql(
        "status in (todo, in_progress) AND priority = high", **LOOKUPS
    )
    assert filters.status == ["todo", "in_progress"]
    assert filters.priority == ["high"]
    assert sort is None


def test_negative_operators_map_to_exclusions():
    filters, _ = parse_teamql("status != done AND priority not in (low)", **LOOKUPS)
    assert filters.exclude_status == ["done"]
    assert filters.exclude_priority == ["low"]


def test_custom_status_keys_are_accepted():
    filters, _ = parse_teamql("status in (new, doing_review)", **LOOKUPS)
    assert filters.status == ["new", "doing_review"]
    filters, _ = parse_teamql("status != verified", **LOOKUPS)
    assert filters.exclude_status == ["verified"]


def test_assignee_variants():
    filters, _ = parse_teamql("assignee = me", **LOOKUPS)
    assert filters.assignee_id == ME
    filters, _ = parse_teamql("assignee = bob@example.com", **LOOKUPS)
    assert filters.assignee_id == BOB
    filters, _ = parse_teamql("assignee = unassigned", **LOOKUPS)
    assert filters.unassigned is True
    filters, _ = parse_teamql(f"assignee != {BOB}", **LOOKUPS)
    assert filters.exclude_assignee_id == BOB


def test_label_and_sprint_names_resolve():
    filters, _ = parse_teamql('label = "bug" AND sprint = "Sprint 4"', **LOOKUPS)
    assert filters.label_id == LABEL
    assert filters.sprint_id == SPRINT
    filters, _ = parse_teamql("sprint is empty", **LOOKUPS)
    assert filters.backlog_only is True
    filters, _ = parse_teamql("label != bug", **LOOKUPS)
    assert filters.exclude_label_id == LABEL


def test_project_by_uuid_and_name():
    filters, _ = parse_teamql(f"project = {PROJECT}", **LOOKUPS)
    assert filters.project_id == PROJECT
    filters, _ = parse_teamql('project = "Team Flow"', **LOOKUPS)
    assert filters.project_name == "Team Flow"


def test_estimate_bounds():
    filters, _ = parse_teamql("estimate >= 3", **LOOKUPS)
    assert filters.estimate_min == 3
    filters, _ = parse_teamql("estimate < 5", **LOOKUPS)
    assert filters.estimate_max is not None and filters.estimate_max < 5
    filters, _ = parse_teamql("estimate is empty", **LOOKUPS)
    assert filters.estimate_empty is True


def test_due_created_and_archived():
    filters, _ = parse_teamql("due < 2026-11-01", **LOOKUPS)
    assert filters.due_before is not None
    filters, _ = parse_teamql("due = overdue", **LOOKUPS)
    assert filters.overdue is True
    filters, _ = parse_teamql("created >= 2026-01-01", **LOOKUPS)
    assert filters.created_after is not None
    filters, _ = parse_teamql("archived = true", **LOOKUPS)
    assert filters.archived_only is True


def test_text_key_roots():
    filters, _ = parse_teamql('text ~ "login timeout"', **LOOKUPS)
    assert filters.text == "login timeout"
    filters, _ = parse_teamql("key in (TEAM-1, TEAM-2)", **LOOKUPS)
    assert filters.keys == ["TEAM-1", "TEAM-2"]
    filters, _ = parse_teamql("roots = true", **LOOKUPS)
    assert filters.roots_only is True


def test_order_by():
    _, sort = parse_teamql("status = todo ORDER BY due DESC", **LOOKUPS)
    assert sort == "-due_date"
    _, sort = parse_teamql("status = todo order by priority", **LOOKUPS)
    assert sort == "priority"


def test_errors_are_human_readable():
    with pytest.raises(ValidationFailedError):
        parse_teamql("banana = 1", **LOOKUPS)
    with pytest.raises(ValidationFailedError):
        parse_teamql("status = not a status!", **LOOKUPS)
    with pytest.raises(ValidationFailedError):
        parse_teamql("this is not a condition", **LOOKUPS)
    with pytest.raises(ValidationFailedError):
        parse_teamql("status = todo ORDER BY nonsense", **LOOKUPS)
    with pytest.raises(ValidationFailedError):
        parse_teamql("assignee = unknown@example.com", **LOOKUPS)
