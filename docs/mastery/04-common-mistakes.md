# Mastery 04 — Common Mistakes

## Generic FastAPI mistakes (with TeamFlow's avoidance)

| # | Mistake | Symptom | TeamFlow's rule |
| --- | --- | --- | --- |
| 1 | Business logic in routers | untestable rules, drift | routers ≤ ~15 lines, delegate to services (`architecture/02`) |
| 2 | Committing in repositories | broken multi-write atomicity | repos `flush`; services commit once (`database/06`) |
| 3 | No `response_model` | accidental field leaks | every route declares one (or returns 204) |
| 4 | Lazy relationship loads in async | `MissingGreenlet` | eager strategies + refetch pattern (`database/03`) |
| 5 | Middleware order assumed = added order | logs/errors misplaced | last added = outermost (`fastapi/08`) |
| 6 | Auth in middleware | no per-route control, no OpenAPI | `CurrentUser` dependency (`fastapi/06`) |
| 7 | Accepting `organization_id`/role from the client | cross-tenant writes | server-resolved membership only (`auth/07`) |
| 8 | `Depends(factory(...))` returning `Depends` | "not a callable object" at import | factories return functions (`fastapi/07`) |
| 9 | String-built `ORDER BY`/`WHERE` | SQL injection | `SORT_COLUMNS` whitelist + bound params (`database/04`) |
| 10 | Unbounded `limit` | memory/latency DoS | `le=100` + repo clamp (`database/05`) |
| 11 | Token type never checked at a verification site | refresh token usable as access (S1) | check `type` everywhere (`production/07`) |
| 12 | 403 for non-existent/foreign resources | existence oracle | 404 doctrine (`auth/05`) |

## Django-developer-specific traps

| Trap | Why it happens | Fix |
| --- | --- | --- |
| Expecting 400 for validation | DRF convention | FastAPI returns **422**; assert 422 |
| Assuming request-wide transactions | `ATOMIC_REQUESTS` habit | service-scoped commits; side effects after commit |
| `task.assignee` "just works" | Django lazy FKs | eager strategies or `MissingGreenlet` |
| QuerySet chaining habits | implicit sessions | explicit `select()` + `await db.execute` |
| `post_save` signal assumptions | implicit side effects | explicit `events.notify`/`audit.log` in services |
| `objects.create()` immediacy | manager autocommit | `add` + `flush`, service commits |
| Middleware order intuition | Django top = outermost | FastAPI last-added = outermost |
| `settings.DEBUG` tracebacks in prod | dev habit | handlers sanitize; `DEBUG=false` |
| Mocking the ORM in tests | `TestCase` isolation | truncation + real Postgres (`testing/03`) |
| `request.user` global | middleware-provided | dependency-provided, explicit per route |

## Async traps

| Trap | Consequence | TeamFlow rule |
| --- | --- | --- |
| Sync DB/HTTP calls inline | loop stall (all requests) | async libs or `run_in_threadpool` |
| `time.sleep` | same | never in handlers |
| `asyncio.run` inside API | `RuntimeError` nested loop | only in workers (`email.py`) |
| Sharing a session across tasks | asyncpg task-safety errors | one session per request |
| `await` forgotten | `'coroutine' object has no attribute` | tests catch; care in review |
| bcrypt inline | ~100ms stall per auth call | accepted + rate-limited; threadpool if hot |

## Security traps (team-level)

| Trap | Example in this project | Status |
| --- | --- | --- |
| Inconsistent checks across verification sites | S1 token type | documented gap + fix in `production/07` |
| Trusting declared content types | uploads | documented gap |
| SSRF via user-provided URLs | webhooks | documented gap |
| Default secrets booting in prod | `SECRET_KEY` | documented gap |
| Cache keys missing tenant | dashboard | avoided (key includes org) |
| Logging secrets | audit meta | avoided (emails only) |

## Review smell list (what to grep for in a diff)

```
git grep "await db.commit" app/api/          → forbidden (routers)
git grep "await db.commit" app/repositories/ → forbidden (repos)
git grep "from fastapi" app/services/        → forbidden (except none exist)
git grep "select(" app/services/             → only documented exceptions
git grep "response_model" app/api/routes/    → every route
git grep "organization_id" app/schemas/      → must be empty (never client-supplied)
git grep "invalidate_dashboard"              → expected map in cache.md
```

## Review questions

1. Pick the three mistakes you are most likely to make coming from Django and
   write the one-line detection rule for each.
2. Which "mistake" in this project is an accepted trade-off rather than a bug?
3. Why does `git grep "from fastapi" app/services/` returning a hit signal an
   architectural regression?
4. What is the async equivalent of Django's "fat model" antipattern?
