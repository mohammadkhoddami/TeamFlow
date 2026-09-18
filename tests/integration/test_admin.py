"""Integration tests: admin panel auth, dashboard, CRUD and audit trail.

The admin panel is session-cookie based and superuser-only. These tests drive
the rendered HTML endpoints (no API tokens) and assert the side effects land in
Postgres, including the redaction of secrets from the audit trail.
"""

import pytest
import pytest_asyncio
from sqlmodel import select

from app.core.security import hash_password, verify_password
from app.models import AuditLog, Label, Organization, User

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "admin-password-123"


@pytest_asyncio.fixture
async def admin_user(db):
    user = User(
        email=ADMIN_EMAIL,
        full_name="Admin User",
        hashed_password=hash_password(ADMIN_PASSWORD),
        is_superuser=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _login(client, email: str = ADMIN_EMAIL, password: str = ADMIN_PASSWORD):
    return await client.post(
        "/admin/login", data={"username": email, "password": password}
    )


@pytest.mark.asyncio
async def test_admin_requires_superuser_session(client):
    r = await client.get("/admin/")
    assert r.status_code == 302
    assert "/admin/login" in r.headers["location"]

    r = await client.get("/admin/user/list")
    assert r.status_code == 302
    assert "/admin/login" in r.headers["location"]


@pytest.mark.asyncio
async def test_admin_login_rejects_non_superuser(client, admin_user):
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "member@example.com",
            "password": "supersecret123",
            "full_name": "Member",
        },
    )
    assert r.status_code == 201

    r = await _login(client, "member@example.com", "supersecret123")
    assert r.status_code == 400
    assert "Invalid credentials" in r.text

    r = await client.get("/admin/")
    assert r.status_code == 302


@pytest.mark.asyncio
async def test_admin_login_rejects_wrong_password(client, admin_user):
    r = await _login(client, password="wrong-password-1")
    assert r.status_code == 400
    assert "Invalid credentials" in r.text


@pytest.mark.asyncio
async def test_admin_login_grants_dashboard_and_lists(client, admin_user):
    r = await _login(client)
    assert r.status_code == 302
    assert r.headers["location"].endswith("/admin/")

    r = await client.get("/admin/")
    assert r.status_code == 200
    assert "Users" in r.text
    assert ADMIN_EMAIL in r.text

    for identity in ("user", "organization", "task", "audit-log"):
        r = await client.get(f"/admin/{identity}/list")
        assert r.status_code == 200, f"{identity} list returned {r.status_code}"


@pytest.mark.asyncio
async def test_admin_logout_clears_session(client, admin_user):
    r = await _login(client)
    assert r.status_code == 302

    r = await client.get("/admin/logout")
    assert r.status_code == 302
    assert "/admin/login" in r.headers["location"]

    r = await client.get("/admin/")
    assert r.status_code == 302


@pytest.mark.asyncio
async def test_admin_can_create_label_and_audit_trail_written(client, db, admin_user):
    org = Organization(name="Acme", slug="acme", created_by_id=admin_user.id)
    db.add(org)
    await db.commit()
    await db.refresh(org)

    r = await _login(client)
    assert r.status_code == 302

    r = await client.post(
        "/admin/label/create",
        data={"name": "backend", "color": "#ff0000", "organization": str(org.id)},
    )
    assert r.status_code == 302, r.text

    org_id = org.id
    admin_id = admin_user.id
    db.expire_all()
    label = (await db.execute(select(Label))).scalar_one()
    assert label.name == "backend"
    assert label.organization_id == org_id

    entry = (
        await db.execute(select(AuditLog).where(AuditLog.action == "admin.create"))
    ).scalar_one()
    assert entry.actor_id == admin_id
    assert entry.target_type == "label"
    assert entry.target_id == str(label.id)


@pytest.mark.asyncio
async def test_admin_user_create_hashes_password_and_redacts_audit(
    client, db, admin_user
):
    r = await _login(client)
    assert r.status_code == 302

    r = await client.post(
        "/admin/user/create",
        data={
            "email": "New.Admin@Example.com",
            "full_name": "New Admin",
            "password": "brand-new-pass-1",
            "is_active": "y",
            "is_superuser": "y",
        },
    )
    assert r.status_code == 302, r.text

    db.expire_all()
    created = (
        await db.execute(select(User).where(User.email == "new.admin@example.com"))
    ).scalar_one()
    assert created.is_superuser is True
    assert verify_password("brand-new-pass-1", created.hashed_password)

    entry = (
        await db.execute(
            select(AuditLog).where(
                AuditLog.action == "admin.create",
                AuditLog.target_type == "user",
            )
        )
    ).scalar_one()
    serialized = str(entry.meta)
    assert "brand-new-pass-1" not in serialized
    assert created.hashed_password not in serialized


@pytest.mark.asyncio
async def test_admin_cannot_delete_own_account(client, db, admin_user):
    r = await _login(client)
    assert r.status_code == 302

    r = await client.delete(f"/admin/user/delete?pks={admin_user.id}")
    assert r.status_code == 200
    assert "error" in r.text

    admin_id = admin_user.id
    db.expire_all()
    assert await db.get(User, admin_id) is not None
