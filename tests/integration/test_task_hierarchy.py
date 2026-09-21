"""Integration tests: task hierarchy — epics, stories, tasks and their rules."""

import pytest

from tests.utils import auth_headers, make_org, make_project, make_task, make_user

ALICE = "hierarchy-alice@example.com"


@pytest.fixture
async def board(client):
    alice = await make_user(client, email=ALICE, full_name="Alice")
    org = await make_org(client, alice, name="Hierarchy Org", slug="hierarchy-org")
    project = await make_project(client, alice, "hierarchy-org", name="Roadmap")
    return {"alice": alice, "org": org, "project": project}


@pytest.mark.asyncio
async def test_create_and_read_hierarchy(client, board):
    alice, project = board["alice"], board["project"]
    H = await auth_headers(alice)

    epic = await make_task(client, alice, project["id"], "Payments epic", type="epic")
    assert epic["type"] == "epic"
    assert epic["parent_id"] is None
    assert epic["parent"] is None

    story = await make_task(
        client,
        alice,
        project["id"],
        "Checkout story",
        type="story",
        parent_id=epic["id"],
    )
    assert story["type"] == "story"
    assert story["parent"]["id"] == epic["id"]
    assert story["parent"]["type"] == "epic"

    task = await make_task(
        client,
        alice,
        project["id"],
        "Stripe webhook",
        type="task",
        parent_id=story["id"],
    )
    direct = await make_task(
        client,
        alice,
        project["id"],
        "Docs task",
        type="task",
        parent_id=epic["id"],
    )

    # Default type stays 'task' for legacy-style creates.
    plain = await make_task(client, alice, project["id"], "Plain task")
    assert plain["type"] == "task"

    # Children endpoint returns direct children, higher level first.
    r = await client.get(f"/api/v1/tasks/{epic['id']}/children", headers=H)
    assert r.status_code == 200
    assert [child["id"] for child in r.json()] == [story["id"], direct["id"]]

    body = (await client.get(f"/api/v1/tasks/{epic['id']}", headers=H)).json()
    assert body["child_count"] == 2
    assert body["done_child_count"] == 0

    # Completing a child updates the parent's progress counters.
    for status in ("in_progress", "in_review", "done"):
        r = await client.post(
            f"/api/v1/tasks/{direct['id']}/move", json={"status": status}, headers=H
        )
        assert r.status_code == 200, r.text
    body = (await client.get(f"/api/v1/tasks/{epic['id']}", headers=H)).json()
    assert body["done_child_count"] == 1

    # Leaf tasks report zero children.
    body = (await client.get(f"/api/v1/tasks/{task['id']}", headers=H)).json()
    assert body["child_count"] == 0 and body["done_child_count"] == 0


@pytest.mark.asyncio
async def test_parent_rules_rejected(client, board):
    alice, project = board["alice"], board["project"]
    H = await auth_headers(alice)

    epic = await make_task(client, alice, project["id"], "Epic", type="epic")
    story = await make_task(
        client, alice, project["id"], "Story", type="story", parent_id=epic["id"]
    )
    task = await make_task(
        client, alice, project["id"], "Task", type="task", parent_id=story["id"]
    )

    async def create_bad(**extra):
        return await client.post(
            f"/api/v1/projects/{project['id']}/tasks",
            json={"title": "bad", **extra},
            headers=H,
        )

    # Same-level nesting and higher-level-as-parent are both rejected.
    assert (await create_bad(type="task", parent_id=task["id"])).status_code == 422
    assert (await create_bad(type="story", parent_id=story["id"])).status_code == 422
    assert (await create_bad(type="story", parent_id=task["id"])).status_code == 422
    # An epic can never have a parent.
    assert (await create_bad(type="epic", parent_id=epic["id"])).status_code == 422

    # Cross-project parent rejected.
    other_project = await make_project(client, alice, "hierarchy-org", name="Other")
    r = await client.post(
        f"/api/v1/projects/{other_project['id']}/tasks",
        json={"title": "cross", "type": "story", "parent_id": epic["id"]},
        headers=H,
    )
    assert r.status_code == 422

    # Cross-org parent is invisible (tenant-safe 422, not a leak).
    await make_org(client, alice, name="Other Org", slug="hierarchy-other")
    foreign_project = await make_project(client, alice, "hierarchy-other", name="Elsewhere")
    foreign_epic = await make_task(
        client, alice, foreign_project["id"], "Foreign epic", type="epic"
    )
    r = await client.post(
        f"/api/v1/projects/{project['id']}/tasks",
        json={"title": "foreign", "type": "story", "parent_id": foreign_epic["id"]},
        headers=H,
    )
    assert r.status_code == 422

    # A task cannot parent itself, and unknown parents 422.
    r = await client.patch(
        f"/api/v1/tasks/{story['id']}", json={"parent_id": story["id"]}, headers=H
    )
    assert r.status_code == 422
    r = await client.patch(
        f"/api/v1/tasks/{story['id']}",
        json={"parent_id": "00000000-0000-0000-0000-000000000000"},
        headers=H,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_type_change_rules(client, board):
    alice, project = board["alice"], board["project"]
    H = await auth_headers(alice)

    epic = await make_task(client, alice, project["id"], "Epic", type="epic")
    story = await make_task(
        client, alice, project["id"], "Story", type="story", parent_id=epic["id"]
    )
    await make_task(
        client, alice, project["id"], "Task", type="task", parent_id=story["id"]
    )

    # Lowering a type with existing children violates the invariant.
    r = await client.patch(f"/api/v1/tasks/{epic['id']}", json={"type": "story"}, headers=H)
    assert r.status_code == 422

    # Raising a type while still nested under an equal/lower level also fails…
    r = await client.patch(f"/api/v1/tasks/{story['id']}", json={"type": "epic"}, headers=H)
    assert r.status_code == 422

    # …but the same change succeeds once detached explicitly.
    r = await client.patch(f"/api/v1/tasks/{story['id']}", json={"parent_id": None}, headers=H)
    assert r.status_code == 200
    assert r.json()["parent_id"] is None
    r = await client.patch(f"/api/v1/tasks/{story['id']}", json={"type": "epic"}, headers=H)
    assert r.status_code == 200
    assert r.json()["type"] == "epic"


@pytest.mark.asyncio
async def test_project_tree_endpoint(client, board):
    alice, project = board["alice"], board["project"]
    H = await auth_headers(alice)

    epic = await make_task(client, alice, project["id"], "Epic", type="epic")
    story = await make_task(
        client, alice, project["id"], "Story", type="story", parent_id=epic["id"]
    )
    task = await make_task(
        client, alice, project["id"], "Task", type="task", parent_id=story["id"]
    )
    orphan = await make_task(client, alice, project["id"], "Standalone task")

    r = await client.get(f"/api/v1/projects/{project['id']}/tasks/tree", headers=H)
    assert r.status_code == 200, r.text
    roots = r.json()
    assert [node["id"] for node in roots] == [epic["id"], orphan["id"]]

    assert roots[0]["child_count"] == 1
    assert [child["id"] for child in roots[0]["children"]] == [story["id"]]
    assert [child["id"] for child in roots[0]["children"][0]["children"]] == [task["id"]]
    assert roots[0]["children"][0]["children"][0]["children"] == []
    assert roots[1]["children"] == []


@pytest.mark.asyncio
async def test_filters_by_type_parent_and_roots(client, board):
    alice, project = board["alice"], board["project"]
    H = await auth_headers(alice)

    epic = await make_task(client, alice, project["id"], "Epic", type="epic")
    story = await make_task(
        client, alice, project["id"], "Story", type="story", parent_id=epic["id"]
    )
    await make_task(client, alice, project["id"], "Top task")

    base = "/api/v1/organizations/hierarchy-org/tasks"
    body = (await client.get(f"{base}?type=epic&type=story", headers=H)).json()
    assert body["total"] == 2

    body = (await client.get(f"{base}?parent_id={epic['id']}", headers=H)).json()
    assert [item["id"] for item in body["items"]] == [story["id"]]

    body = (await client.get(f"{base}?roots_only=true&project_id={project['id']}", headers=H)).json()
    assert {item["title"] for item in body["items"]} == {"Epic", "Top task"}


@pytest.mark.asyncio
async def test_deleting_parent_detaches_children(client, board):
    alice, project = board["alice"], board["project"]
    H = await auth_headers(alice)

    epic = await make_task(client, alice, project["id"], "Epic", type="epic")
    story = await make_task(
        client, alice, project["id"], "Story", type="story", parent_id=epic["id"]
    )
    task = await make_task(
        client, alice, project["id"], "Task", type="task", parent_id=story["id"]
    )

    r = await client.delete(f"/api/v1/tasks/{story['id']}", headers=H)
    assert r.status_code == 204

    body = (await client.get(f"/api/v1/tasks/{task['id']}", headers=H)).json()
    assert body["parent_id"] is None
    assert body["parent"] is None

    body = (await client.get(f"/api/v1/tasks/{epic['id']}", headers=H)).json()
    assert body["child_count"] == 0
