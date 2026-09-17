# Mastery 09 — Review Checklist (Learning Progress)

This is *your* progress checklist, not a PR checklist (that one is
`05-code-review-checklist.md`). Tick an item only when you can **explain it from
memory and point at the code**.

## FastAPI

- [ ] App factory + lifespan: what runs once per process and what runs per request
- [ ] Routing: prefixes, multiple routers per resource, path vs query vs body decisions
- [ ] Typed params: `Literal` lists, `Query(ge/le)`, why `sort` is a whitelist string
- [ ] Response models: allow-list semantics, generics (`Page[T]`), status-code choices
- [ ] Pydantic: constraints, `field_validator`, `model_fields_set` PATCH semantics
- [ ] Dependency injection: `Depends` graph, caching, generator deps, annotated aliases
- [ ] Advanced dependencies: factories, guards that raise, `dependency_overrides`
- [ ] Middleware: pure ASGI, order semantics, body buffering/replay
- [ ] Exception handling: `AppError` tree, 422 shape, sanitized 500s
- [ ] Lifespan vs BackgroundTasks vs Celery decision
- [ ] WebSockets: handshake auth, rooms, disconnect cleanup, pub/sub scaling
- [ ] OpenAPI: tags/summaries, OAuth2 wiring, what isn't documented (WS, headers)

## Database

- [ ] SQLModel: `table=True` vs schemas, `sa_column` gotchas, `__init__` defaults
- [ ] Keys/FKs: UUIDv4 trade-offs, CASCADE vs SET NULL, unique constraints
- [ ] Relationships: eager strategies, link models, `Optional["X"]`, `foreign_keys`
- [ ] Queries: `select`, `scalar_one_or_none`, count, group-by, FILTER aggregates
- [ ] Pagination: offset/limit, clamped limits, shared conditions for count
- [ ] Transactions: flush vs commit, service boundaries, side-effect ordering
- [ ] Indexes: which query each `tasks` index serves; why tenant-first
- [ ] N+1: joined vs selectin, refetch + `populate_existing`, fresh-object trap
- [ ] Performance: `NullPool` in tests, pool math, known limits + upgrades

## Auth

- [ ] Authentication vs authorization distinction in the codebase
- [ ] Password hashing: bcrypt cost, salt, version pin, blocking trade-off
- [ ] JWT: claims, algorithm pinning, type checks (and the documented gap)
- [ ] Access/refresh: rotation, reuse detection, logout semantics, Redis keys
- [ ] Authorization: 404-vs-403 doctrine, service-enforced rank
- [ ] RBAC: rank map, outrank-target-and-role, owner invariants
- [ ] Multi-tenancy: three enforcement layers, IDOR test matrix, deletion semantics

## Architecture

- [ ] Layer responsibilities and the one-way dependency rule
- [ ] Router discipline (and the two documented exceptions)
- [ ] Dependency layer: context vs guards; read-only invariant
- [ ] Service layer: rules + transaction ownership + side-effect ordering
- [ ] Repository layer: flush-only, org-scoped reads, policy-free returns
- [ ] Transaction decisions: why not `ATOMIC_REQUESTS`, why separate claim commit
- [ ] The 14 design decisions and their trade-offs

## Async

- [ ] Event loop: one per worker process; blocking = global stall
- [ ] `async def` vs blocking calls; `run_in_threadpool` placements
- [ ] Async DB/Redis vs sync workers; why workers can't reuse repositories
- [ ] The accepted inline blocking call (bcrypt) and its justification

## Infrastructure

- [ ] Redis: four uses, keys, TTLs, degradation modes (open/closed/degrade)
- [ ] Caching: cache-aside, invalidation map (and its two gaps), TTL as safety net
- [ ] Rate limiting: ZSET pipeline math, IP+email identities, fail-open reasoning
- [ ] Celery: acks_late → idempotency, queues, task classification, test seams
- [ ] Beat: singleton, cadence choices, sync stats twin
- [ ] WebSocket scaling: publish→listener→rooms, reconnect loop, delivery limits
- [ ] Object storage: presign flow, key layout, validation, documented gaps
- [ ] HTTPX: process-scoped client, timeouts, `trust_env` story, retries one layer up
- [ ] Webhooks: durable rows, HMAC formula, classification, sweeper, SSRF gap

## Testing

- [ ] Unit vs integration vs worker tests: what goes where and why
- [ ] Test infrastructure: env-before-import, truncation, NullPool, Redis DB 15
- [ ] API factories through the public interface
- [ ] Security tests: IDOR matrix, RBAC matrix, token lifecycle, rate limits
- [ ] Worker tests: `task.run`, real receiver, independent HMAC verification
- [ ] WS tests: TestClient lifespan + sync truncation caveat

## Production

- [ ] Dockerfile: multi-stage, non-root, healthcheck, graceful CMD
- [ ] Compose dev vs prod: what differs and why (`:?` guards, migrations step)
- [ ] Configuration: typed settings, environments, secret policy + gap
- [ ] Nginx: WS upgrade headers, body cap, forwarded headers stance
- [ ] ASGI workers: gunicorn+uvicorn, pool math, graceful shutdown path
- [ ] Health vs readiness: what each checks and who should call it
- [ ] Logging: contextvars correlation, JSON mode, what's never logged
- [ ] Security posture: the 8 findings and their fixes
- [ ] Deployment runbook: migrate → start → verify → rollback

## Self-test

If you can answer `mastery/08-final-assessment.md` sections A–H at 85%+, tick
the whole list. If not, each wrong answer points back to the lesson section that
owns it.

## Review questions

1. Which sections felt weakest? Name the lesson files for each.
2. Which three checklist items could you *teach* to another Django developer
   right now, and which three would you need to re-read?
3. Which item is impossible to tick without reading code (not just docs), and
   why?
