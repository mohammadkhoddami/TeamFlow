"""Integration tests for M3 automation rules (#14)."""

import pytest

from tests.utils import auth_headers, make_org, make_project, make_task, make_user

ALICE = "m3a-alice@example.com"
BEN = "m3a-ben@example.com"
SLUG = "m3a-org"


@pytest.fixture
async def board(client):
    alice = await make_user(client, email=ALICE, full_name="Alice")
    ben = await make_user(client, email=BEN, full_name="Ben")
    await make_org(client, alice, name="M3 Automation", slug=SLUG)
    project = await make_project(client, alice, SLUG, name="Automation Board")
    r = await client.post(
        f"/api/v1/organizations/{SLUG}/members",
        json={"user_email": BEN, "role": "member"},
        headers=await auth_headers(alice),
    )
    assert r.status_code == 201, r.text
    return {"alice": alice, "ben": ben, "ben_id": r.json()["user_id"], "project": project}


async def _create_rule(client, actor, **overrides) -> dict:
    payload = {
        "name": "Rule",
        "trigger_type": "task_created",
        "actions": [{"type": "comment", "body": "automated note"}],
        **overrides,
    }
    r = await client.post(
        f"/api/v1/organizations/{SLUG}/automations",
        json=payload,
        headers=await auth_headers(actor),
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _move(client, user, task_id, status):
    return await client.post(
        f"/api/v1/tasks/{task_id}/move",
        json={"status": status},
        headers=await auth_headers(user),
    )


@pytest.mark.asyncio
async def test_rule_crud_templates_and_validation(client, board):
    alice, project = board["alice"], board["project"]
    HA = await auth_headers(alice)

    templates = (
        await client.get(
            f"/api/v1/organizations/{SLUG}/automations/templates", headers=HA
        )
    ).json()
    assert len(templates) >= 5

    r = await client.post(
        f"/api/v1/organizations/{SLUG}/automations",
        json={"name": "bad", "trigger_type": "task_created", "actions": []},
        headers=HA,
    )
    assert r.status_code == 422
    r = await client.post(
        f"/api/v1/organizations/{SLUG}/automations",
        json={
            "name": "bad",
            "trigger_type": "task_created",
            "actions": [{"type": "webhook", "url": "ftp://nope"}],
        },
        headers=HA,
    )
    assert r.status_code == 422

    rule = await _create_rule(client, alice, name="CRUD rule", project_id=project["id"])
    listed = (
        await client.get(
            f"/api/v1/organizations/{SLUG}/automations", headers=HA
        )
    ).json()
    assert any(entry["id"] == rule["id"] for entry in listed)

    r = await client.patch(
        f"/api/v1/organizations/{SLUG}/automations/{rule['id']}", json={"is_active": False}, headers=HA
    )
    assert r.status_code == 200 and r.json()["is_active"] is False

    r = await client.delete(f"/api/v1/organizations/{SLUG}/automations/{rule['id']}", headers=HA)
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_task_created_rule_comments_and_notifies(client, board):
    alice, project, ben_id = board["alice"], board["project"], board["ben_id"]
    rule = await _create_rule(
        client,
        alice,
        name="Greet new tasks",
        project_id=project["id"],
        trigger_type="task_created",
        conditions=[{"field": "priority", "op": "in", "value": ["high", "urgent"]}],
        actions=[
            {"type": "comment", "body": "Created by automation ✅"},
            {"type": "notify", "user_id": ben_id},
            {"type": "set_priority", "priority": "medium"},
        ],
    )
    task = await make_task(
        client, alice, project["id"], title="Urgent thing", priority="high"
    )

    comments = (
        await client.get(
            f"/api/v1/tasks/{task['id']}/comments", headers=await auth_headers(alice)
        )
    ).json()
    assert any("Created by automation" in entry["body"] for entry in comments)

    ben_notifications = (
        await client.get(
            "/api/v1/notifications?limit=100", headers=await auth_headers(board["ben"])
        )
    ).json()["items"]
    assert any(
        entry["type"] == "automation" and entry["task_id"] == task["id"]
        for entry in ben_notifications
    )

    executions = (
        await client.get(
            f"/api/v1/organizations/{SLUG}/automations/{rule['id']}/executions",
            headers=await auth_headers(alice),
        )
    ).json()
    assert len(executions) == 1
    assert executions[0]["status"] == "success"
    assert {entry["action"] for entry in executions[0]["actions_log"]} == {
        "comment",
        "notify",
        "set_priority",
    }

    listed = (
        await client.get(
            f"/api/v1/organizations/{SLUG}/automations", headers=await auth_headers(alice)
        )
    ).json()
    stored = next(entry for entry in listed if entry["id"] == rule["id"])
    assert stored["run_count"] == 1

    # A low-priority task does not match the condition: no extra execution.
    await make_task(client, alice, project["id"], title="Calm thing", priority="low")
    executions = (
        await client.get(
            f"/api/v1/organizations/{SLUG}/automations/{rule['id']}/executions",
            headers=await auth_headers(alice),
        )
    ).json()
    assert len(executions) == 1


@pytest.mark.asyncio
async def test_status_changed_rule_and_invalid_transition_logged(client, board):
    alice, project = board["alice"], board["project"]
    HA = await auth_headers(alice)
    rule = await _create_rule(
        client,
        alice,
        name="Review means high priority",
        trigger_type="status_changed",
        trigger_config={"to_status": "in_progress"},
        actions=[{"type": "set_priority", "priority": "high"}],
    )
    task = await make_task(client, alice, project["id"], title="Flow task")
    r = await _move(client, alice, task["id"], "in_progress")
    assert r.status_code == 200, r.text

    executions = (
        await client.get(
            f"/api/v1/organizations/{SLUG}/automations/{rule['id']}/executions", headers=HA
        )
    ).json()
    assert len(executions) == 1 and executions[0]["status"] == "success"

    refreshed = (await client.get(f"/api/v1/tasks/{task['id']}", headers=HA)).json()
    assert refreshed["priority"] == "high"

    # An invalid transition (todo -> done) fails inside the rule but the rule
    # engine records it and the *triggering* request still succeeds.
    bad_rule = await _create_rule(
        client,
        alice,
        name="Bad transition",
        trigger_type="task_created",
        actions=[{"type": "transition", "status": "in_review"}],
    )
    created = await make_task(client, alice, project["id"], title="No jump")
    executions = (
        await client.get(
            f"/api/v1/organizations/{SLUG}/automations/{bad_rule['id']}/executions", headers=HA
        )
    ).json()
    assert len(executions) == 1
    assert executions[0]["status"] == "failed"
    assert executions[0]["error"]

    # ... and the task is untouched
    fresh = (await client.get(f"/api/v1/tasks/{created['id']}", headers=HA)).json()
    assert fresh["status"] == "todo"


@pytest.mark.asyncio
async def test_scheduled_rule_runs_and_logs(client, board, db):
    alice = board["alice"]
    HA = await auth_headers(alice)
    rule = await _create_rule(
        client,
        alice,
        name="Daily owner ping",
        trigger_type="schedule",
        trigger_config={"interval": "daily", "at": "00:00"},
        actions=[{"type": "notify", "role": "owner"}],
    )
    # Schedule rules with conditions cannot match (no task context) -> skipped.
    skipped_rule = await _create_rule(
        client,
        alice,
        name="Conditional schedule",
        trigger_type="schedule",
        trigger_config={"interval": "daily", "at": "00:00"},
        conditions=[{"field": "priority", "op": "equals", "value": "urgent"}],
        actions=[{"type": "notify", "role": "owner"}],
    )

    from app.services import automations as automation_service

    summary = await automation_service.run_due_scheduled_rules(db)
    assert summary.executed == 1
    assert summary.skipped == 1

    notifications = (
        await client.get("/api/v1/notifications?limit=100", headers=HA)
    ).json()["items"]
    assert any(
        entry["type"] == "automation" and rule["name"] in entry["title"]
        for entry in notifications
    )

    executions = (
        await client.get(
            f"/api/v1/organizations/{SLUG}/automations/{rule['id']}/executions", headers=HA
        )
    ).json()
    assert len(executions) == 1 and executions[0]["trigger_event"] == "schedule"

    # A second run the same day does not re-execute the rule (last_run_at gate).
    summary = await automation_service.run_due_scheduled_rules(db)
    assert summary.executed == 0
    executions = (
        await client.get(
            f"/api/v1/organizations/{SLUG}/automations/{skipped_rule['id']}/executions", headers=HA
        )
    ).json()
    assert executions == []
