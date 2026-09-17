"""Integration tests: attachments (fake storage backend)."""


import pytest

from app.api.deps import get_storage
from app.main import app
from tests.utils import auth_headers, make_org, make_project, make_task, make_user

ALICE = "attach-alice@example.com"
OUTSIDER = "attach-outsider@example.com"


class FakeStorage:
    """Stands in for MinIO: presigning is deterministic, objects exist only
    after the test simulates the client-side PUT by adding the key."""

    def __init__(self) -> None:
        self.keys: set[str] = set()

    def presign_put(self, key: str, content_type: str | None = None) -> str:
        # NOTE: does NOT create the object; upload happens client-side.
        return f"http://fake-storage/{key}"

    def presign_get(self, key: str) -> str:
        return f"http://fake-storage/{key}"

    async def stat(self, key: str) -> dict:
        if key in self.keys:
            return {"size": 1, "etag": "x"}
        return None

    def remove(self, key: str) -> None:
        self.keys.discard(key)

    async def ensure_bucket(self) -> None:
        pass


@pytest.fixture
async def fake_storage():
    storage = FakeStorage()
    app.dependency_overrides[get_storage] = lambda: storage
    yield storage
    app.dependency_overrides.pop(get_storage, None)


@pytest.mark.asyncio
async def test_attachment_flow_pending_confirm_download(client, fake_storage):
    alice = await make_user(client, email=ALICE)
    await make_org(client, alice, name="Attach Org", slug="attach-org")
    project = await make_project(client, alice, "attach-org")
    task = await make_task(client, alice, project["id"])
    H = await auth_headers(alice)

    r = await client.post(
        f"/api/v1/tasks/{task['id']}/attachments",
        json={"filename": "report.pdf", "content_type": "application/pdf", "size": 12345},
        headers=H,
    )
    assert r.status_code == 201, r.text
    grant = r.json()
    assert grant["attachment"]["status"] == "pending"
    assert "/orgs/" in grant["upload_url"]  # org-prefixed key
    storage_key = grant["upload_url"].split("http://fake-storage/")[1]
    assert storage_key.startswith("orgs/") and "../" not in storage_key

    # confirm before upload -> 422 (object missing)
    r = await client.post(
        f"/api/v1/tasks/{task['id']}/attachments/{grant['attachment']['id']}/confirm",
        headers=H,
    )
    assert r.status_code == 422

    # simulate the S3 PUT happening (FakeStorage tracks keys on presign)
    fake_storage.keys.add(storage_key)
    r = await client.post(
        f"/api/v1/tasks/{task['id']}/attachments/{grant['attachment']['id']}/confirm",
        headers=H,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "available"

    # download grant works only when available
    r = await client.post(
        f"/api/v1/attachments/{grant['attachment']['id']}/download-url", headers=H
    )
    assert r.status_code == 200
    assert r.json()["download_url"]

    r = await client.get(f"/api/v1/tasks/{task['id']}/attachments", headers=H)
    assert len(r.json()) == 1


@pytest.mark.asyncio
async def test_upload_validation_rules(client, fake_storage):
    alice = await make_user(client, email=ALICE)
    await make_org(client, alice, name="Attach Org 2", slug="attach-org-2")
    project = await make_project(client, alice, "attach-org-2")
    task = await make_task(client, alice, project["id"])
    H = await auth_headers(alice)

    # disallowed type
    r = await client.post(
        f"/api/v1/tasks/{task['id']}/attachments",
        json={"filename": "a.exe", "content_type": "application/x-msdownload", "size": 10},
        headers=H,
    )
    assert r.status_code == 422

    # too big
    r = await client.post(
        f"/api/v1/tasks/{task['id']}/attachments",
        json={"filename": "a.zip", "content_type": "application/zip", "size": 999_999_999},
        headers=H,
    )
    assert r.status_code == 422

    # traversal is sanitized
    r = await client.post(
        f"/api/v1/tasks/{task['id']}/attachments",
        json={"filename": "../../etc/passwd.txt", "content_type": "text/plain", "size": 12},
        headers=H,
    )
    assert r.status_code == 201
    assert r.json()["attachment"]["filename"] == "passwd.txt"


@pytest.mark.asyncio
async def test_attachment_tenant_isolation(client, fake_storage):
    alice = await make_user(client, email=ALICE)
    await make_org(client, alice, name="Attach Org 3", slug="attach-org-3")
    project = await make_project(client, alice, "attach-org-3")
    task = await make_task(client, alice, project["id"])
    H = await auth_headers(alice)

    r = await client.post(
        "/api/v1/tasks/{task_id}/attachments".format(task_id=task["id"]),
        json={"filename": "a.txt", "content_type": "text/plain", "size": 5},
        headers=H,
    )
    attachment_id = r.json()["attachment"]["id"]

    outsider = await make_user(client, email="attach-outsider@example.com")
    OH = await auth_headers(outsider)
    r = await client.post(
        f"/api/v1/attachments/{attachment_id}/download-url", headers=OH
    )
    assert r.status_code == 404
    r = await client.delete(f"/api/v1/attachments/{attachment_id}", headers=OH)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_permissions_uploader_vs_member(client, fake_storage):
    alice = await make_user(client, email=ALICE)
    await make_org(client, alice, name="Attach Org 4", slug="attach-org-4")
    project = await make_project(client, alice, "attach-org-4")

    # add a plain member
    member = await make_user(client, email="attach-member@example.com")
    await client.post(
        "/api/v1/organizations/attach-org-4/invitations",
        json={"email": "attach-member@example.com"},
        headers=await auth_headers(alice),
    )
    invs = (await client.get("/api/v1/invitations/me", headers=await auth_headers(member))).json()
    await client.post(
        f"/api/v1/invitations/{invs[0]['id']}/accept", headers=await auth_headers(member)
    )

    task = await make_task(client, alice, project["id"])
    r = await client.post(
        f"/api/v1/tasks/{task['id']}/attachments",
        json={"filename": "a.txt", "content_type": "text/plain", "size": 5},
        headers=await auth_headers(alice),
    )
    attachment_id = r.json()["attachment"]["id"]

    # member (not uploader) cannot delete
    r = await client.delete(
        f"/api/v1/attachments/{attachment_id}", headers=await auth_headers(member)
    )
    assert r.status_code == 403

    # uploader can
    r = await client.delete(f"/api/v1/attachments/{attachment_id}", headers=await auth_headers(alice))
    assert r.status_code == 204
