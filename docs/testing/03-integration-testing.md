# Testing 03 — Integration Testing

## Concept

Integration tests exercise the real stack: the ASGI app, real PostgreSQL, real
Redis — no mocks except at third-party boundaries TeamFlow doesn't control
(storage, SMTP, outbound HTTP receivers).

## The client — no network server needed

```python
# tests/conftest.py
@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
```

`ASGITransport` calls the app directly in-process (no socket, no uvicorn). It
also **does not run lifespan** — no Redis listener, no bucket bootstrap, no
engine disposal. For HTTP tests that's a feature: less machinery, faster tests.

## Database strategy

| Concern | Approach |
| --- | --- |
| Isolation | dedicated database `teamflow_test`, auto-created once |
| Schema | `SQLModel.metadata.create_all` on a NullPool engine once per session |
| Between tests | `TRUNCATE ... RESTART IDENTITY CASCADE` (autouse async fixture) |
| Engine pooling | `NullPool` in testing (`app/core/db.py`) — multiple event loops |

The truncate fixture:

```python
@pytest_asyncio.fixture(autouse=True)
async def _clean_state():
    yield
    async with engine.begin() as conn:
        tables = ", ".join(f'"{t}"' for t in SQLModel.metadata.tables)
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    from app.core.redis import get_redis_client
    try:
        await get_redis_client().flushdb()
    except Exception:
        pass
```

`RESTART IDENTITY` is irrelevant with UUIDs but harmless; `CASCADE` handles FK
order. Redis DB 15 is flushed for the same isolation guarantee (rate-limit
windows, token whitelists, dashboard caches).

## Real Redis, real consequences

Because Redis is real, integration tests cover behavior mocks can't:

- `test_refresh_rotates_and_old_token_dies` — rotation + reuse detection
  (`auth/04`), which is pure Redis state-machine behavior;
- `test_dashboard_cache_is_populated` — reads the actual cache key back:
  ```python
  cached = await get_redis_client().get(dashboard_key(uuid.UUID(org["id"])))
  assert cached is not None and "total_tasks" in cached
  ```
- rate-limit tests flip `settings.rate_limit_enabled = True` and count real
  429s, then restore it in `finally`.

## Factories: build through the API

```python
async def make_user(client, email="user1@example.com", password=PASSWORD, full_name="Test User"):
    r = await client.post("/api/v1/auth/register",
                          json={"email": email, "password": password, "full_name": full_name})
    assert r.status_code in (201, 409), r.text
    r = await client.post("/api/v1/auth/login", data={"username": email, "password": password})
    assert r.status_code == 200, r.text
    body = r.json()
    return {"token": body["access_token"], "refresh": body["refresh_token"], "email": email}
```

Why API-driven instead of direct inserts: every test's setup exercises the real
registration/login/creation paths, so tests fail precisely where a user's flow
would. The cost (setup is a few HTTP calls) is irrelevant in-process.

## A representative integration test (annotated)

`tests/integration/test_tasks.py::test_task_filters_sort_pagination`:

```python
await make_task(client, alice, project["id"], "Alpha payment", priority="high")
await make_task(client, alice, project["id"], "Beta refactoring", priority="low")
await make_task(client, alice, project["id"], "Gamma payments api", priority="urgent")
t4 = await make_task(client, alice, project["id"], "Delta archived")
await client.post(f"/api/v1/tasks/{t4['id']}/move", json={"status": "in_progress"}, headers=H)

r = await client.get("/api/v1/organizations/task-org/tasks?search=payment&sort=-priority", headers=H)
body = r.json()
assert body["total"] == 2                                  # count matches filters
titles = [t["title"] for t in body["items"]]
assert "Alpha payment" in titles and "Gamma payments api" in titles

r = await client.get("...?status=todo&status=in_progress", headers=H)
assert r.json()["total"] == 4                              # multi-value filter

r = await client.get("...?sort=title&offset=1&limit=2", headers=H)
assert [t["title"] for t in body["items"]] == ...          # pagination window

overdue = await make_task(client, alice, project["id"],
                          due_date=(datetime.now(UTC) - timedelta(days=2)).isoformat())
r = await client.get("...?overdue=true", headers=H)
assert r.json()["items"][0]["id"] == overdue["id"]
```

This one test exercises: repository filter composition, the shared
conditions/count guarantee, SQL ordering, `ILIKE`, multi-value params, offset
windows, and date logic — all against real SQL.

## What's deliberately faked

Only `tests/integration/test_attachments.py` (storage):

```python
class FakeStorage:
    def presign_put(self, key, content_type=None): return f"http://fake-storage/{key}"
    async def stat(self, key): return {"size": 1} if key in self.keys else None
    def presign_get(self, key): return f"http://fake-storage/{key}"
    def remove(self, key): self.keys.discard(key)

app.dependency_overrides[get_storage] = lambda: storage
```

The interesting logic (validation, tenant checks, status transitions) is real;
the byte movement is simulated. The test still asserts the *storage key shape*
(`startswith("orgs/")`, no `../`) — the security-relevant output of the real
service code.

## Django/DRF comparison 🔵

| Django | TeamFlow |
| --- | --- |
| `TestCase` + rollback per test | truncate per test (commits happen by design) |
| `APIClient` | `AsyncClient(ASGITransport)` |
| `django.test.utils.setup_test_environment` | env vars set before imports |
| `override_settings` | mutate the cached `settings` object + restore |
| `factory_boy` | API-driven factories in `tests/utils.py` |

## Common mistakes

1. **Assuming lifespan ran.** Lifecycle behavior (WS listener, bucket check) is
   absent under ASGITransport — use `TestClient` when you need it.
2. **Pointing tests at the dev database.** A truncation fixture against the
   wrong URL is data loss. The dedicated `teamflow_test` name is mandatory.
3. **Leaving rate limits on** for the whole suite (constant test-client IP) —
   unrelated tests start returning 429.
4. **Asserting only status codes.** The suite asserts response *bodies*
   (`total`, ids, roles) — status codes alone would pass on wrong data.
5. **Mocking the repository layer** — then the SQL (the thing most likely to be
   wrong) is untested.

## Review questions

1. Why does `ASGITransport` not run lifespan, and where does that matter?
2. What two pieces of global state does `_clean_state` reset, and why must both?
3. Why are factories API-driven rather than direct DB inserts?
4. In the attachment test, what security property is asserted even though
   storage is faked?
