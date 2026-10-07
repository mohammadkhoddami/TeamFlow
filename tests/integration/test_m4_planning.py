"""Integration tests for M4: goals/OKRs, dashboard builder and form intake."""

from datetime import UTC, datetime, timedelta

import pytest

from tests.utils import auth_headers, make_org, make_project, make_task, make_user

ALICE = "m4-alice@example.com"
SLUG = "m4-org"


@pytest.fixture
async def workspace(client):
    alice = await make_user(client, email=ALICE, full_name="Alice")
    org = await make_org(client, alice, name="M4 Org", slug=SLUG)
    project = await make_project(client, alice, SLUG, name="M4 Board")
    return {"alice": alice, "org": org, "project": project}


async def _alice_id(client, alice) -> str:
    r = await client.get(
        f"/api/v1/organizations/{SLUG}/members", headers=await auth_headers(alice)
    )
    assert r.status_code == 200, r.text
    return next(m["user_id"] for m in r.json() if m["user"]["email"] == ALICE)


async def _complete(client, alice, task_id: str) -> None:
    H = await auth_headers(alice)
    for status in ("in_progress", "in_review", "done"):
        r = await client.post(
            f"/api/v1/tasks/{task_id}/move", json={"status": status}, headers=H
        )
        assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_goals_crud_and_progress_rollup(client, workspace):
    alice, project = workspace["alice"], workspace["project"]
    H = await auth_headers(alice)
    epic = await make_task(client, alice, project["id"], title="Goal epic", type="epic")
    done_child = await make_task(
        client, alice, project["id"], title="Done child",
        parent_id=epic["id"], type="task",
    )
    await make_task(
        client, alice, project["id"], title="Open child",
        parent_id=epic["id"], type="task",
    )
    await _complete(client, alice, done_child["id"])

    r = await client.post(
        f"/api/v1/organizations/{SLUG}/goals",
        json={"name": "Ship M4", "description": "Planning and intake"},
        headers=H,
    )
    assert r.status_code == 201, r.text
    goal = r.json()
    assert goal["owner"]["email"] == ALICE
    assert goal["progress_pct"] == 0

    r = await client.post(
        f"/api/v1/organizations/{SLUG}/goals/{goal['id']}/tasks",
        json={"task_ids": [epic["id"]]},
        headers=H,
    )
    assert r.status_code == 200, r.text
    linked = r.json()
    assert linked["progress_pct"] == 50
    assert [task["id"] for task in linked["tasks"]] == [epic["id"]]
    assert linked["tasks"][0]["progress_pct"] == 50

    # Re-linking already-linked tasks is ignored.
    r = await client.post(
        f"/api/v1/organizations/{SLUG}/goals/{goal['id']}/tasks",
        json={"task_ids": [epic["id"], epic["id"]]},
        headers=H,
    )
    assert len(r.json()["tasks"]) == 1

    # Tasks outside the org cannot be linked.
    r = await client.post(
        f"/api/v1/organizations/{SLUG}/goals/{goal['id']}/tasks",
        json={"task_ids": ["00000000-0000-0000-0000-000000000000"]},
        headers=H,
    )
    assert r.status_code == 422

    r = await client.get(f"/api/v1/organizations/{SLUG}/goals", headers=H)
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1 and r.json()[0]["progress_pct"] == 50

    r = await client.patch(
        f"/api/v1/organizations/{SLUG}/goals/{goal['id']}",
        json={"name": "Ship M4 GA", "status": "achieved"},
        headers=H,
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Ship M4 GA" and r.json()["status"] == "achieved"

    r = await client.delete(
        f"/api/v1/organizations/{SLUG}/goals/{goal['id']}/tasks/{epic['id']}",
        headers=H,
    )
    assert r.status_code == 204
    r = await client.get(
        f"/api/v1/organizations/{SLUG}/goals/{goal['id']}", headers=H
    )
    assert r.status_code == 200 and r.json()["tasks"] == []
    assert r.json()["progress_pct"] == 0

    r = await client.delete(
        f"/api/v1/organizations/{SLUG}/goals/{goal['id']}", headers=H
    )
    assert r.status_code == 204
    r = await client.get(f"/api/v1/organizations/{SLUG}/goals", headers=H)
    assert r.json() == []


@pytest.mark.asyncio
async def test_dashboard_builder_and_widget_data(client, workspace):
    alice, project = workspace["alice"], workspace["project"]
    H = await auth_headers(alice)
    alice_id = await _alice_id(client, alice)
    yesterday = datetime.now(UTC) - timedelta(days=1)
    overdue = await make_task(
        client, alice, project["id"], title="Overdue chore",
        due_date=yesterday.isoformat(), assignee_id=alice_id,
    )
    await make_task(
        client, alice, project["id"], title="Fresh chore", assignee_id=alice_id
    )

    r = await client.post(
        f"/api/v1/organizations/{SLUG}/dashboards",
        json={
            "name": "Ops board",
            "widgets": [
                {"type": "stats", "title": "Overview"},
                {"type": "overdue", "title": "Overdue"},
                {"type": "members", "title": "Load"},
                {"type": "activity", "title": "Recent"},
            ],
            "is_default": True,
        },
        headers=H,
    )
    assert r.status_code == 201, r.text
    dashboard = r.json()
    assert dashboard["is_default"] is True
    assert all(widget["id"] for widget in dashboard["widgets"])

    r = await client.get(
        f"/api/v1/organizations/{SLUG}/dashboards/{dashboard['id']}/data",
        headers=H,
    )
    assert r.status_code == 200, r.text
    widgets = {widget["type"]: widget for widget in r.json()["widgets"]}
    assert widgets["stats"]["data"]["total_tasks"] >= 2
    assert widgets["stats"]["data"]["overdue_tasks"] >= 1
    assert widgets["stats"]["data"]["tasks_by_status"]["todo"] >= 1
    overdue_rows = widgets["overdue"]["data"]
    assert [row["id"] for row in overdue_rows] == [overdue["id"]]
    assert overdue_rows[0]["assignee"] == "Alice"
    assert widgets["members"]["data"][0]["open_tasks"] == 2
    assert isinstance(widgets["activity"]["data"], list)

    # Unknown widget types are rejected at create time.
    r = await client.post(
        f"/api/v1/organizations/{SLUG}/dashboards",
        json={"name": "Broken", "widgets": [{"type": "nope", "title": "X"}]},
        headers=H,
    )
    assert r.status_code == 422

    # Only one default dashboard per org.
    r = await client.post(
        f"/api/v1/organizations/{SLUG}/dashboards",
        json={"name": "Other board", "is_default": True},
        headers=H,
    )
    assert r.status_code == 201, r.text
    new_id = r.json()["id"]
    dashboards = (
        await client.get(f"/api/v1/organizations/{SLUG}/dashboards", headers=H)
    ).json()
    defaults = [entry for entry in dashboards if entry["is_default"]]
    assert len(defaults) == 1 and defaults[0]["id"] == new_id

    r = await client.delete(
        f"/api/v1/organizations/{SLUG}/dashboards/{dashboard['id']}", headers=H
    )
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_form_intake(client, workspace):
    alice, project = workspace["alice"], workspace["project"]
    H = await auth_headers(alice)
    r = await client.post(
        f"/api/v1/projects/{project['id']}/forms",
        json={
            "name": "Bug intake",
            "description": "Report a bug",
            "is_public": True,
            "fields": [
                {"key": "summary", "label": "Summary", "type": "textarea",
                 "required": True},
                {"key": "priority_hint", "label": "Priority", "type": "priority"},
                {"key": "browser", "label": "Browser", "type": "select",
                 "options": ["chrome", "firefox"]},
            ],
        },
        headers=H,
    )
    assert r.status_code == 201, r.text
    form = r.json()
    assert form["slug"].startswith("bug-intake-") and form["submit_count"] == 0
    assert form["fields"][0]["required"] is True

    # Public read needs no auth and exposes the definition only.
    r = await client.get(f"/api/v1/forms/{form['slug']}")
    assert r.status_code == 200, r.text
    public = r.json()
    assert public["project_name"] == project["name"]
    assert public["fields"][0]["key"] == "summary"
    assert "id" not in public

    r = await client.post(
        f"/api/v1/forms/{form['slug']}",
        json={
            "data": {
                "summary": "Printer jams",
                "priority_hint": "high",
                "browser": "chrome",
            }
        },
    )
    assert r.status_code == 201, r.text
    submitted = r.json()
    assert submitted["task_key"]

    task = (
        await client.get(f"/api/v1/tasks/{submitted['task_id']}", headers=H)
    ).json()
    assert task["title"] == "Printer jams"
    assert task["priority"] == "high"
    assert task["type"] == "task"
    assert task["description"].startswith("- **Summary:** Printer jams")
    assert "Submitted via form Bug intake" in task["description"]

    r = await client.get(
        f"/api/v1/projects/{project['id']}/forms/{form['id']}", headers=H
    )
    assert r.status_code == 200 and r.json()["submit_count"] == 1

    r = await client.get(
        f"/api/v1/projects/{project['id']}/forms/{form['id']}/submissions",
        headers=H,
    )
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1
    assert r.json()[0]["task_id"] == submitted["task_id"]

    # Required fields are enforced.
    r = await client.post(
        f"/api/v1/forms/{form['slug']}", json={"data": {"summary": "   "}}
    )
    assert r.status_code == 422

    # Private forms 404 publicly (both read and submit).
    r = await client.patch(
        f"/api/v1/projects/{project['id']}/forms/{form['id']}",
        json={"is_public": False},
        headers=H,
    )
    assert r.status_code == 200 and r.json()["is_public"] is False
    r = await client.get(f"/api/v1/forms/{form['slug']}")
    assert r.status_code == 404
    r = await client.post(f"/api/v1/forms/{form['slug']}", json={"data": {}})
    assert r.status_code == 404

    # Unknown slugs 404.
    r = await client.get("/api/v1/forms/does-not-exist-000000")
    assert r.status_code == 404
