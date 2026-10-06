"""Integration tests for M2: workflows/boards/WIP, custom fields, links,
reports, capacity, worklogs, templates, recurrence, multi-assignees/checklists
and import/export."""

from datetime import UTC, datetime, timedelta

import pytest

from tests.utils import auth_headers, make_org, make_project, make_task, make_user

ALICE = "m2-alice@example.com"
BOB = "m2-bob@example.com"
SLUG = "m2-org"


@pytest.fixture
async def board(client):
    alice = await make_user(client, email=ALICE, full_name="Alice")
    bob = await make_user(client, email=BOB, full_name="Bob")
    org = await make_org(client, alice, name="M2 Org", slug=SLUG)
    project = await make_project(client, alice, SLUG, name="M2 Board")
    return {"alice": alice, "bob": bob, "org": org, "project": project}


async def _bob_id(client, alice, slug=SLUG) -> str:
    r = await client.post(
        f"/api/v1/organizations/{slug}/members",
        json={"user_email": BOB, "role": "member"},
        headers=await auth_headers(alice),
    )
    assert r.status_code == 201, r.text
    return r.json()["user_id"]


async def _complete(client, alice, task_id: str) -> None:
    H = await auth_headers(alice)
    for status in ("in_progress", "in_review", "done"):
        r = await client.post(
            f"/api/v1/tasks/{task_id}/move", json={"status": status}, headers=H
        )
        assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_custom_workflow_transitions_wip_and_categories(client, board):
    alice, project = board["alice"], board["project"]
    H = await auth_headers(alice)
    workflow = {
        "wip_enforced": True,
        "statuses": [
            {"key": "new", "name": "New", "category": "todo", "transitions": ["doing"]},
            {"key": "doing", "name": "Doing", "category": "in_progress",
             "transitions": ["review"], "wip_limit": 1},
            {"key": "review", "name": "Review", "category": "in_review",
             "transitions": ["verified", "doing"]},
            {"key": "verified", "name": "Verified", "category": "done",
             "transitions": ["doing"]},
        ],
    }
    r = await client.put(
        f"/api/v1/projects/{project['id']}/workflow", json=workflow, headers=H
    )
    assert r.status_code == 200, r.text
    assert [entry["key"] for entry in r.json()] == ["new", "doing", "review", "verified"]

    first = await make_task(client, alice, project["id"], title="Workflow one")
    assert first["status"] == "new"
    assert first["status_category"] == "todo"

    r = await client.post(
        f"/api/v1/tasks/{first['id']}/move", json={"status": "verified"}, headers=H
    )
    assert r.status_code == 422  # no transition path

    r = await client.post(
        f"/api/v1/tasks/{first['id']}/move", json={"status": "doing"}, headers=H
    )
    assert r.status_code == 200 and r.json()["status_category"] == "in_progress"

    second = await make_task(client, alice, project["id"], title="Workflow two")
    r = await client.post(
        f"/api/v1/tasks/{second['id']}/move", json={"status": "doing"}, headers=H
    )
    assert r.status_code == 422  # WIP limit 1 reached

    for status in ("review", "verified"):
        r = await client.post(
            f"/api/v1/tasks/{first['id']}/move", json={"status": status}, headers=H
        )
        assert r.status_code == 200, r.text
    done = (await client.get(f"/api/v1/tasks/{first['id']}", headers=H)).json()
    assert done["status_category"] == "done"

    dashboard = (await client.get(f"/api/v1/organizations/{SLUG}/dashboard", headers=H)).json()
    assert dashboard["completed_tasks"] >= 1

    # Removing a status re-homes its tasks instead of orphaning them.
    r = await client.put(
        f"/api/v1/projects/{project['id']}/workflow",
        json={
            "statuses": [
                {"key": "new", "name": "New", "category": "todo", "transitions": ["doing"]},
                {"key": "doing", "name": "Doing", "category": "in_progress",
                 "transitions": ["new"]},
            ]
        },
        headers=H,
    )
    assert r.status_code == 200, r.text
    moved = (await client.get(f"/api/v1/tasks/{first['id']}", headers=H)).json()
    assert moved["status"] in ("new", "doing")


@pytest.mark.asyncio
async def test_boards_crud(client, board):
    alice, project = board["alice"], board["project"]
    H = await auth_headers(alice)
    r = await client.post(
        f"/api/v1/projects/{project['id']}/boards",
        json={"name": "Scrum board", "swimlane_by": "assignee",
              "filter_query": "status = todo", "is_default": True},
        headers=H,
    )
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["swimlane_by"] == "assignee"

    r = await client.get(f"/api/v1/projects/{project['id']}/boards", headers=H)
    assert [entry["name"] for entry in r.json()] == ["Scrum board"]

    r = await client.patch(
        f"/api/v1/organizations/{SLUG}/boards/{created['id']}", json={"swimlane_by": "label"}, headers=H
    )
    assert r.status_code == 200 and r.json()["swimlane_by"] == "label"

    r = await client.post(
        f"/api/v1/projects/{project['id']}/boards",
        json={"name": "Broken", "columns": ["nope"]},
        headers=H,
    )
    assert r.status_code == 422

    r = await client.delete(f"/api/v1/organizations/{SLUG}/boards/{created['id']}", headers=H)
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_custom_fields_values_and_teamql(client, board):
    alice, project = board["alice"], board["project"]
    bob_id = await _bob_id(client, alice)
    H = await auth_headers(alice)

    fields = {}
    for payload in (
        {"name": "Notes", "field_type": "text"},
        {"name": "Points", "field_type": "number"},
        {"name": "Severity", "field_type": "select", "options": ["low", "high"]},
        {"name": "Reviewer", "field_type": "user"},
        {"name": "Platforms", "field_type": "multi_select", "options": ["web", "ios"]},
    ):
        r = await client.post(
            f"/api/v1/projects/{project['id']}/custom-fields", json=payload, headers=H
        )
        assert r.status_code == 201, r.text
        fields[payload["name"]] = r.json()

    r = await client.post(
        f"/api/v1/projects/{project['id']}/tasks",
        json={
            "title": "Sized task",
            "custom_fields": {
                fields["Notes"]["key"]: "hello world",
                fields["Points"]["key"]: 8,
                fields["Severity"]["key"]: "high",
                fields["Reviewer"]["key"]: bob_id,
                fields["Platforms"]["key"]: ["web", "ios"],
            },
        },
        headers=H,
    )
    assert r.status_code == 201, r.text
    task = r.json()
    values = {entry["key"]: entry["value"] for entry in task["custom_fields"]}
    assert values["points"] == 8.0
    assert values["severity"] == "high"
    assert values["platforms"] == ["web", "ios"]

    r = await client.post(
        f"/api/v1/projects/{project['id']}/tasks",
        json={"title": "Bad", "custom_fields": {fields["Severity"]["key"]: "nope"}},
        headers=H,
    )
    assert r.status_code == 422

    # Required fields are enforced.
    r = await client.post(
        f"/api/v1/projects/{project['id']}/custom-fields",
        json={"name": "Component", "field_type": "text", "is_required": True},
        headers=H,
    )
    fields["Component"] = r.json()
    r = await client.post(
        f"/api/v1/projects/{project['id']}/tasks", json={"title": "Missing"}, headers=H
    )
    assert r.status_code == 422

    # TeamQL custom-field filters.
    r = await client.get(
        f"/api/v1/organizations/{SLUG}/tasks/query",
        params={"q": f"cf_{fields['Points']['key']} = 8"},
        headers=H,
    )
    assert [item["id"] for item in r.json()["items"]] == [task["id"]]
    r = await client.get(
        f"/api/v1/organizations/{SLUG}/tasks/query",
        params={"q": f"cf_{fields['Notes']['key']} ~ hell"},
        headers=H,
    )
    assert [item["id"] for item in r.json()["items"]] == [task["id"]]

    r = await client.patch(
        f"/api/v1/tasks/{task['id']}",
        json={"custom_fields": {fields["Points"]["key"]: 3}},
        headers=H,
    )
    updated = {entry["key"]: entry["value"] for entry in r.json()["custom_fields"]}
    assert updated["points"] == 3.0
    assert fields["Component"]["key"] == "component"


@pytest.mark.asyncio
async def test_task_links_and_blocked_filter(client, board):
    alice, project = board["alice"], board["project"]
    H = await auth_headers(alice)
    blocker = await make_task(client, alice, project["id"], title="Blocker")
    blocked = await make_task(client, alice, project["id"], title="Blocked")

    r = await client.post(
        f"/api/v1/tasks/{blocker['id']}/links",
        json={"to_task_id": blocked["id"], "link_type": "blocks"},
        headers=H,
    )
    assert r.status_code == 201, r.text
    assert len(r.json()["blocks"]) == 1

    read = (await client.get(f"/api/v1/tasks/{blocked['id']}", headers=H)).json()
    assert read["is_blocked"] is True
    assert read["blocked_by_count"] == 1

    r = await client.get(
        f"/api/v1/organizations/{SLUG}/tasks",
        params={"project_id": project["id"], "blocked": True},
        headers=H,
    )
    assert [item["id"] for item in r.json()["items"]] == [blocked["id"]]

    # Cycles are rejected.
    r = await client.post(
        f"/api/v1/tasks/{blocked['id']}/links",
        json={"to_task_id": blocker["id"], "link_type": "blocks"},
        headers=H,
    )
    assert r.status_code == 422

    # Symmetric duplicates are rejected.
    r = await client.post(
        f"/api/v1/tasks/{blocker['id']}/links",
        json={"to_task_id": blocked["id"], "link_type": "relates_to"},
        headers=H,
    )
    assert r.status_code == 201
    r = await client.post(
        f"/api/v1/tasks/{blocked['id']}/links",
        json={"to_task_id": blocker["id"], "link_type": "relates_to"},
        headers=H,
    )
    assert r.status_code == 409

    await _complete(client, alice, blocker["id"])
    read = (await client.get(f"/api/v1/tasks/{blocked['id']}", headers=H)).json()
    assert read["is_blocked"] is False


@pytest.mark.asyncio
async def test_reports(client, board):
    alice, project = board["alice"], board["project"]
    H = await auth_headers(alice)
    start = datetime.now(UTC) - timedelta(days=7)
    end = datetime.now(UTC)
    sprint = (
        await client.post(
            f"/api/v1/projects/{project['id']}/sprints",
            json={"name": "Report sprint", "start_date": start.isoformat(),
                  "end_date": end.isoformat()},
            headers=H,
        )
    ).json()
    done_task = await make_task(
        client, alice, project["id"], title="Done task", estimate=5, sprint_id=sprint["id"]
    )
    await make_task(
        client, alice, project["id"], title="Open task", estimate=3, sprint_id=sprint["id"]
    )
    r = await client.post(f"/api/v1/sprints/{sprint['id']}/start", headers=H)
    assert r.status_code == 200, r.text
    await _complete(client, alice, done_task["id"])

    r = await client.get(
        f"/api/v1/projects/{project['id']}/reports/burndown",
        params={"sprint_id": sprint["id"]},
        headers=H,
    )
    assert r.status_code == 200, r.text
    burndown = r.json()
    assert burndown["total_points"] == 8
    assert burndown["points"][-1]["remaining_points"] == 3

    r = await client.get(
        f"/api/v1/projects/{project['id']}/reports/velocity", headers=H
    )
    assert r.json()["sprints"][0]["completed_points"] == 5

    r = await client.get(
        f"/api/v1/projects/{project['id']}/reports/cumulative-flow",
        params={"days": 14},
        headers=H,
    )
    assert len(r.json()["points"]) == 14

    r = await client.get(
        f"/api/v1/projects/{project['id']}/reports/cycle-time", headers=H
    )
    cycle = r.json()
    assert cycle["count"] == 1 and cycle["avg_lead_time_days"] is not None
    r = await client.get(
        f"/api/v1/projects/{project['id']}/reports/cycle-time",
        params={"format": "csv"},
        headers=H,
    )
    assert r.headers["content-type"].startswith("text/csv")
    assert "lead_time_days" in r.text

    r = await client.get(
        f"/api/v1/sprints/{sprint['id']}/report", headers=H
    )
    report = r.json()
    assert report["committed_tasks"] == 2
    assert report["completed_tasks"] == 1
    assert report["completed_points"] == 5


@pytest.mark.asyncio
async def test_capacity_planning(client, board):
    alice, project = board["alice"], board["project"]
    bob_id = await _bob_id(client, alice)
    H = await auth_headers(alice)
    sprint = (
        await client.post(
            f"/api/v1/projects/{project['id']}/sprints",
            json={"name": "Capacity sprint"},
            headers=H,
        )
    ).json()
    await make_task(
        client, alice, project["id"], title="Big", estimate=8,
        sprint_id=sprint["id"], assignee_id=bob_id,
    )
    members = (await client.get(f"/api/v1/organizations/{SLUG}/members", headers=H)).json()
    alice_id = next(m["user_id"] for m in members if m["user"]["email"] == ALICE)
    r = await client.put(
        f"/api/v1/sprints/{sprint['id']}/capacity",
        json={"entries": [{"user_id": bob_id, "capacity": 5},
                          {"user_id": alice_id, "capacity": 10}]},
        headers=H,
    )
    assert r.status_code == 200, r.text
    rows = {entry["user_id"]: entry for entry in r.json()}
    assert rows[bob_id]["overloaded"] is True
    assert rows[bob_id]["assigned_points"] == 8
    assert rows[alice_id]["overloaded"] is False


@pytest.mark.asyncio
async def test_worklogs_and_timesheet(client, board):
    alice, project = board["alice"], board["project"]
    H = await auth_headers(alice)
    task = await make_task(client, alice, project["id"], title="Timed")
    now = datetime.now(UTC)

    r = await client.post(
        f"/api/v1/tasks/{task['id']}/worklogs",
        json={"minutes": 90, "started_at": now.isoformat(), "description": "kickoff"},
        headers=H,
    )
    assert r.status_code == 201, r.text
    worklog = r.json()
    read = (await client.get(f"/api/v1/tasks/{task['id']}", headers=H)).json()
    assert read["logged_minutes"] == 90
    assert read["actual_estimate"] == 1.5

    await client.post(
        f"/api/v1/tasks/{task['id']}/worklogs",
        json={"minutes": 30, "started_at": now.isoformat()},
        headers=H,
    )
    read = (await client.get(f"/api/v1/tasks/{task['id']}", headers=H)).json()
    assert read["logged_minutes"] == 120 and read["actual_estimate"] == 2.0

    r = await client.get(f"/api/v1/organizations/{SLUG}/timesheet", headers=H)
    sheet = r.json()
    assert sheet["total_minutes"] == 120
    assert sheet["totals_by_user"][0]["minutes"] == 120

    r = await client.patch(
        f"/api/v1/organizations/{SLUG}/worklogs/{worklog['id']}", json={"minutes": 60}, headers=H
    )
    assert r.status_code == 200
    read = (await client.get(f"/api/v1/tasks/{task['id']}", headers=H)).json()
    assert read["logged_minutes"] == 90

    r = await client.delete(f"/api/v1/organizations/{SLUG}/worklogs/{worklog['id']}", headers=H)
    assert r.status_code == 204
    read = (await client.get(f"/api/v1/tasks/{task['id']}", headers=H)).json()
    assert read["logged_minutes"] == 30


@pytest.mark.asyncio
async def test_templates(client, board):
    alice, project = board["alice"], board["project"]
    H = await auth_headers(alice)
    r = await client.get(f"/api/v1/organizations/{SLUG}/project-templates", headers=H)
    ids = [entry["id"] for entry in r.json()]
    assert "builtin:kanban" in ids and "builtin:scrum" in ids

    r = await client.post(
        f"/api/v1/organizations/{SLUG}/projects/from-template",
        json={"name": "Kanban flow", "template_id": "builtin:kanban"},
        headers=H,
    )
    assert r.status_code == 201, r.text
    kanban = r.json()
    r = await client.get(f"/api/v1/projects/{kanban['id']}/workflow", headers=H)
    assert [entry["key"] for entry in r.json()] == ["todo", "in_progress", "done"]
    labels = (await client.get(f"/api/v1/organizations/{SLUG}/labels", headers=H)).json()
    assert "expedite" in [label["name"] for label in labels]

    r = await client.post(
        f"/api/v1/projects/{kanban['id']}/save-as-template",
        json={"name": "My kanban"},
        headers=H,
    )
    assert r.status_code == 201, r.text
    custom_id = r.json()["id"]
    r = await client.post(
        f"/api/v1/organizations/{SLUG}/projects/from-template",
        json={"name": "Copy of kanban", "template_id": custom_id},
        headers=H,
    )
    assert r.status_code == 201, r.text

    r = await client.post(
        f"/api/v1/organizations/{SLUG}/task-templates",
        json={"name": "Bug report", "title": "Reproduce the bug",
              "checklist": ["Reproduce", "Fix", "Verify"]},
        headers=H,
    )
    assert r.status_code == 201, r.text
    template = r.json()
    r = await client.post(
        f"/api/v1/organizations/{SLUG}/task-templates/{template['id']}/apply",
        json={"project_id": project["id"]},
        headers=H,
    )
    assert r.status_code == 201, r.text
    applied = r.json()
    assert applied["title"] == "Reproduce the bug"
    assert applied["checklist_total"] == 3


@pytest.mark.asyncio
async def test_recurring_tasks(client, board):
    alice, project = board["alice"], board["project"]
    H = await auth_headers(alice)
    yesterday = datetime.now(UTC) - timedelta(days=1)
    r = await client.post(
        f"/api/v1/projects/{project['id']}/tasks",
        json={"title": "Daily standup", "recurrence_rule": "FREQ=DAILY",
              "due_date": yesterday.isoformat()},
        headers=H,
    )
    assert r.status_code == 201, r.text
    task = r.json()

    r = await client.post(
        f"/api/v1/projects/{project['id']}/tasks",
        json={"title": "Broken rule", "recurrence_rule": "NOT_A_RULE"},
        headers=H,
    )
    assert r.status_code == 422

    await _complete(client, alice, task["id"])
    r = await client.get(
        f"/api/v1/organizations/{SLUG}/tasks",
        params={"search": "Daily standup"},
        headers=H,
    )
    items = r.json()["items"]
    assert len(items) == 2
    occurrence = next(item for item in items if item["id"] != task["id"])
    assert occurrence["recurrence_source_id"] == task["id"]
    assert occurrence["due_date"] > yesterday.isoformat()


@pytest.mark.asyncio
async def test_multi_assignees_and_checklist(client, board):
    alice, project = board["alice"], board["project"]
    bob_id = await _bob_id(client, alice)
    H = await auth_headers(alice)
    members = (await client.get(f"/api/v1/organizations/{SLUG}/members", headers=H)).json()
    alice_id = next(m["user_id"] for m in members if m["user"]["email"] == ALICE)
    task = await make_task(client, alice, project["id"], title="Team task")

    r = await client.put(
        f"/api/v1/tasks/{task['id']}/assignees",
        json={"assignees": [
            {"user_id": bob_id, "role": "assignee"},
            {"user_id": alice_id, "role": "approver"},
        ]},
        headers=H,
    )
    assert r.status_code == 200, r.text
    assert {entry["role"] for entry in r.json()} == {"assignee", "approver"}
    read = (await client.get(f"/api/v1/tasks/{task['id']}", headers=H)).json()
    assert read["assignee_id"] == bob_id
    assert len(read["assignees"]) == 2

    first = (
        await client.post(
            f"/api/v1/tasks/{task['id']}/checklist", json={"text": "Step one"}, headers=H
        )
    ).json()
    await client.post(
        f"/api/v1/tasks/{task['id']}/checklist", json={"text": "Step two"}, headers=H
    )
    r = await client.patch(
        f"/api/v1/tasks/{task['id']}/checklist/{first['id']}", json={"is_done": True}, headers=H
    )
    assert r.status_code == 200
    read = (await client.get(f"/api/v1/tasks/{task['id']}", headers=H)).json()
    assert read["checklist_total"] == 2 and read["checklist_done"] == 1

    r = await client.delete(f"/api/v1/tasks/{task['id']}/checklist/{first['id']}", headers=H)
    assert r.status_code == 204
    read = (await client.get(f"/api/v1/tasks/{task['id']}", headers=H)).json()
    assert read["checklist_total"] == 1


@pytest.mark.asyncio
async def test_import_and_export(client, board):
    alice, project = board["alice"], board["project"]
    H = await auth_headers(alice)
    await _bob_id(client, alice)
    csv_content = (
        "title,description,status,priority,labels,assignee_email,due_date,estimate\n"
        f"Imported one,First task,done,high,imported;backend,{BOB},2026-12-01,5\n"
        "Imported two,Second task,in_progress,low,imported,,2026-12-02,2\n"
        "Imported three,Third task,To Do,medium,,,,\n"
    )
    r = await client.post(
        f"/api/v1/organizations/{SLUG}/imports",
        data={"project_id": project["id"], "format": "csv"},
        files={"file": ("tasks.csv", csv_content.encode(), "text/csv")},
        headers=H,
    )
    assert r.status_code == 200, r.text
    summary = r.json()
    assert summary["created_tasks"] == 3
    assert summary["created_labels"] == 2

    r = await client.get(
        f"/api/v1/organizations/{SLUG}/tasks", params={"search": "Imported"}, headers=H
    )
    assert r.json()["total"] == 3

    # Dry run does not write.
    r = await client.post(
        f"/api/v1/organizations/{SLUG}/imports",
        data={"project_id": project["id"], "format": "csv", "dry_run": "true"},
        files={"file": ("tasks.csv", csv_content.encode(), "text/csv")},
        headers=H,
    )
    assert r.json()["created_tasks"] == 3
    r = await client.get(
        f"/api/v1/organizations/{SLUG}/tasks", params={"search": "Imported"}, headers=H
    )
    assert r.json()["total"] == 3

    r = await client.get(f"/api/v1/organizations/{SLUG}/export", headers=H)
    assert r.status_code == 200
    payload = r.json()
    assert payload["version"] == 2
    assert len(payload["tasks"]) >= 3

    r = await client.get(f"/api/v1/projects/{project['id']}/export", headers=H)
    assert r.headers["content-type"].startswith("text/csv")
    assert "Imported one" in r.text
