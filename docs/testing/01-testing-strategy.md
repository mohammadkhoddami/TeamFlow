# Testing 01 — Testing Strategy

## Concept

TeamFlow's suite (69 tests) is organized by what each test exercises:

```
tests/
├── unit/          pure logic, no I/O            tests/unit/test_security_helpers.py
├── integration/   API + infra behavior          tests/integration/*.py
└── workers/       Celery task functions         tests/workers/*.py
```

## What to test against reality vs mock

| Layer | Approach in TeamFlow | Why |
| --- | --- | --- |
| Password hashing, HMAC, transitions, templates | unit, real functions | pure, fast, deterministic |
| HTTP API (auth, RBAC, tenant isolation, idempotency) | integration via ASGI client + **real Postgres + real Redis** | the bugs live in SQL, constraints, and Redis semantics |
| Attachments | integration with a **fake StorageClient** via dependency override | S3 behavior is an external boundary; the interesting logic is validation + authz |
| Webhook delivery | worker tests with a **real local HTTP receiver** (threaded server) | signatures, statuses, retries are the point |
| Email | worker test with the console backend | rendering + dispatch, not SMTP |
| WebSockets | TestClient (runs lifespan) + real Redis | pub/sub path is the point |

The principle: **mock only external boundaries you don't control; test against
real infrastructure for everything whose semantics you depend on.**

## The test infrastructure — `tests/conftest.py`

```python
os.environ["ENVIRONMENT"] = "testing"
os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL",
    "postgresql+asyncpg://teamflow:teamflow@localhost:5432/teamflow_test")
os.environ.setdefault("DATABASE_URL_SYNC",
    "postgresql+psycopg://teamflow:teamflow@localhost:5432/teamflow_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("EMAIL_BACKEND", "console")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")   # per-test opt-in
```

Key decisions:

- **Env vars are set before importing the app** — settings are `lru_cache`d at
  import; ordering matters.
- **Dedicated test database** (`teamflow_test`, auto-created) and **Redis DB 15**
  (flushed between tests) keep dev data untouched.
- **Rate limiting off by default** — otherwise IP-keyed limits collide across
  tests (the client IP is constant). Rate-limit tests monkeypatch
  `settings.rate_limit_enabled = True`.
- **Schema via `SQLModel.metadata.create_all`** on a throwaway `NullPool`
  engine — production uses Alembic; the suite tests the *models*, and the
  migration is verified separately (`production/08-deployment.md`).
- **Truncation between tests** (`TRUNCATE ... RESTART IDENTITY CASCADE`) with an
  autouse async fixture; WS tests (sync) do their own psycopg truncation
  because sync tests don't run async fixtures.
- **`NullPool` in testing** (`app/core/db.py`) because tests span multiple event
  loops (TestClient portal + pytest-asyncio session loop).

## Fixtures

```python
@pytest_asyncio.fixture
async def client():                      # ASGITransport: no server, no lifespan
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

@pytest_asyncio.fixture
async def db():                          # direct session for assertions
    async with AsyncSessionLocal() as session:
        yield session
```

Factories in `tests/utils.py` build state **through the public API** (no
backdoors):

```python
async def make_user(client, email=..., password=PASSWORD, ...) -> dict: ...
async def make_org(client, user, name=..., slug=...) -> dict: ...
async def make_project(client, user, org_slug, name=...) -> dict: ...
async def make_task(client, user, project_id, title=..., **extra) -> dict: ...
```

Creating users through `/auth/register` + `/auth/login` means every test also
exercises the real auth stack — and the returned dict carries the access token
for `auth_headers(user)`.

## What the suite covers (and where)

| Area | File | Representative assertion |
| --- | --- | --- |
| Health | `test_health.py` | `/ready` checks DB + Redis |
| Auth flows | `test_auth_flow.py` | refresh rotation burns the family on replay |
| Rate limits | `test_rate_limiting.py` | 429 + Retry-After after N hits; fail-open |
| RBAC / invitations | `test_organizations_rbac.py` | every rank rule from the matrix |
| Projects | `test_projects.py` | member can't create; outsider gets 404 |
| Tasks | `test_tasks.py` | transitions, filters, IDOR matrix, mentions |
| Idempotency | `test_idempotency.py` | replay, 422 mismatch, per-user scoping |
| Attachments | `test_attachments.py` | pending→confirm→download, fake storage |
| Notifications/webhooks CRUD | `test_notifications_webhooks.py` | inbox, secret-once, audit |
| Dashboard | `test_dashboard_cache.py` | aggregates fresh after mutations; cache populated |
| WebSockets | `test_websockets.py` | event fan-out, auth closes, ping/pong |
| Workers | `tests/workers/*` | webhook success/retry/permanent/idempotent; cleanup |

## Running

```bash
docker compose up -d db redis        # integration tests need these
uv run pytest tests -q
uv run pytest tests/unit tests/workers -q      # fast subset (~12s)
```

⚠️ Operational note learned in this project: WebSocket tests are the slow ones
(portal + Windows); the fast subset is the first thing to run while iterating.

## Django/DRF comparison 🔵

| Django | TeamFlow |
| --- | --- |
| `pytest-django` + `TestCase` (transaction rollback per test) | truncation between tests (async sessions + commits make rollback fixtures awkward) |
| `APIClient` | `httpx.AsyncClient` + ASGITransport |
| Django test DB creation | `_create_test_database` + `create_all` |
| `freezegun`, factories (factory_boy) | API-driven factories (no extra deps) |
| Channels testing utilities | TestClient websocket + real Redis |

The rollback-per-test pattern doesn't transfer cleanly to FastAPI: services
commit deliberately, and rollback fixtures require holding an outer transaction
the app doesn't know about. Truncation is slower per test but honest and simple.

## Common mistakes

1. **Mocking the DB/session layer** — tests pass while SQL constraints,
   cascades, and indexes go untested. TeamFlow tests against real Postgres.
2. **Creating objects directly in the DB for API tests** — bypasses the very
   authorization paths being tested.
3. **Shared mutable state between tests** (no truncation, shared Redis) —
   order-dependent flakes.
4. **Testing only happy paths.** Half of TeamFlow's tests assert 404/403/422/429
   outcomes — the security surface is the product.
5. **Running the whole suite for every change** when a targeted subset answers
   the question — the fast `unit + workers` split exists for iteration.

## Review questions

1. Why are tests configured through environment variables *before* importing
   `app.main`?
2. Why does the attachment suite use a fake storage dependency instead of
   MinIO, while the webhook suite uses a real local HTTP server?
3. What breaks if rate limiting is left enabled for the whole suite?
4. Why `NullPool` in tests? What error does removing it resurrect?
