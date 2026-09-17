# Mastery 05 — Code Review Checklist

Use this when reviewing any FastAPI PR (or agent output). Every item names
where TeamFlow demonstrates the standard.

## FastAPI

- [ ] Route declares `response_model` (or returns 204/None intentionally)
- [ ] Correct status code (201 create, 204 delete, 202 accepted, 422 invalid)
- [ ] Path/query params typed; `limit` bounded (`le=`); `sort` whitelisted
- [ ] No business logic in the handler; ≤ ~15 lines
- [ ] Dependencies are read-only; tenant gate present for id-addressed routes
- [ ] Exceptions are `AppError` subclasses; no `HTTPException` in services
- [ ] Middleware additions are pure ASGI and order-reasoned
- [ ] Lifespan untouched or additions are once-per-process with teardown
- [ ] WS endpoints: auth + membership before rooms; invalid input handled
- [ ] OpenAPI: summary/tags present; no duplicate operation ids

**Evidence:** `fastapi/01–13`

## Database / SQLModel

- [ ] Models: `organization_id` CASCADE + index on tenant tables
- [ ] `__init__` defaults for NOT NULL `sa_column` fields
- [ ] Relationships: eager strategy + `Optional["X"]` + `foreign_keys` when needed
- [ ] Queries in repositories only; tenant filters (`*_in_org`) on all reads
- [ ] No `ILIKE`/`ORDER BY` built by concatenation
- [ ] Pagination: page + count use the same conditions
- [ ] Transactions: commit only in services; effects after commit
- [ ] New index justified by a query; migration present (`alembic revision`)
- [ ] No N+1: serialized relationships are eager-loaded or refetched
- [ ] `populate_existing=True` where a previously-loaded collection changed

**Evidence:** `database/01–09`, `architecture/06`

## Auth & authorization

- [ ] Authentication via `CurrentUser`; token type checked at every site
- [ ] Authorization in services with `role_rank`; no client-supplied roles/orgs
- [ ] Non-member access → 404; insufficient rank → 403; illegal state → 422
- [ ] Privileged writes audited (`audit.log` with actor + org)
- [ ] Passwords/tokens never logged or returned

**Evidence:** `auth/01–07`, `production/07`

## Async

- [ ] No blocking calls inline (`requests`, sync DB, `time.sleep`)
- [ ] Celery enqueue through `run_in_threadpool`
- [ ] Workers use sync sessions; services stay async-only
- [ ] No `asyncio.run` in API paths

**Evidence:** `async/01–04`

## Infrastructure

- [ ] New Redis keys follow `teamflow:{purpose}:...`, have TTLs, and a
      documented degradation mode (fail open/closed/degrade)
- [ ] Cache keys embed the tenant; invalidation added for mutations
- [ ] Celery tasks: idempotent, bounded retries, no ORM objects passed
- [ ] Webhook/HTTP: timeout set, shared client, retries classified
- [ ] Storage keys server-generated; validation before presign

**Evidence:** `infrastructure/01–09`

## Testing

- [ ] Happy path + at least one failure path per change
- [ ] Security-relevant behavior asserted with the right status code
- [ ] Tests use API factories, not direct DB inserts
- [ ] Worker tests run task functions directly with a real receiver/fake storage
- [ ] No mocks of the DB/session layer

**Evidence:** `testing/01–06`

## Production

- [ ] Config via `Settings`; no new `os.getenv`
- [ ] Migrations included and reversible; no model/DDL drift
- [ ] Health/readiness untouched (or additions justified)
- [ ] Logs: no secrets; contextvars preserved
- [ ] Compose/env updates for new dependencies

**Evidence:** `production/01–08`

## The five questions for any diff

1. Where does the tenant check happen for every new id-addressed read/write?
2. Where is the transaction boundary, and what happens on rollback?
3. What happens if Redis / the broker / storage is down?
4. Which queries does this add, and do they use indexes?
5. What does the client see when it goes wrong — and does it leak existence?

## Scoring a review

| Outcome | Criteria |
| --- | --- |
| **Approve** | all boxes checked or explicitly justified deviations |
| **Request changes** | any tenant/transaction/auth box unchecked |
| **Discuss** | performance or design trade-offs without a documented reason |

## Review questions

1. Which three checklist items are hard blockers even if "it works"?
2. Take any past change you made and score it against this list.
3. Which items does the TeamFlow codebase itself fail today? (Cross-check
   `production/07` findings.)
