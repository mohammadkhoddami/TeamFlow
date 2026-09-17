# TeamFlow — A FastAPI Course Built From a Real Project

This directory is a **course**, not API documentation. Every lesson starts from a
concept, then walks through the *actual* TeamFlow source code so you can see how
an experienced FastAPI developer applies it in a production-shaped system.

## Who this is for

Experienced backend developers (you know Python, Django, DRF, Postgres, Redis,
Celery, Docker) who are new to FastAPI/SQLModel and want to learn the ecosystem
deeply by reviewing a real codebase instead of toy examples.

## The one rule

**The source code is the source of truth.** These lessons quote the repository.
If a lesson and the code disagree, the code wins — and any difference is called
out explicitly (including things TeamFlow does *not* do, like `BackgroundTasks`).

## Start here

1. [`00-learning-path.md`](00-learning-path.md) — reading order and time budget.
2. [`01-project-overview.md`](01-project-overview.md) — what TeamFlow is.
3. [`02-architecture.md`](02-architecture.md) — the layered architecture.
4. [`03-request-lifecycle.md`](03-request-lifecycle.md) — one request, end to end.

## Sections

| Section | You learn |
| --- | --- |
| [`fastapi/`](fastapi/01-fastapi-application.md) | The framework itself: routing, validation, DI, middleware, lifespan, WS, OpenAPI |
| [`database/`](database/01-sqlmodel.md) | SQLModel, models, queries, transactions, indexes, N+1, performance |
| [`auth/`](auth/01-authentication.md) | Password hashing, JWT, refresh rotation, RBAC, multi-tenancy |
| [`architecture/`](architecture/01-layered-architecture.md) | Router/dependency/service/repository layers and why they exist |
| [`async/`](async/01-async-await.md) | Event loop, blocking vs non-blocking, TeamFlow's async decisions |
| [`infrastructure/`](infrastructure/01-redis.md) | Redis, cache, rate limits, Celery, WS scaling, MinIO, HTTPX, webhooks |
| [`testing/`](testing/01-testing-strategy.md) | Unit, integration, API, security, realtime, background-job tests |
| [`production/`](production/01-docker.md) | Docker, config, nginx, workers, health, logging, security, deployment |
| [`mastery/`](mastery/01-fastapi-cheatsheet.md) | Cheat sheets, common mistakes, review checklist, mastery map, assessment |

## How to read a lesson

Every lesson follows the same shape:

1. **Concept** — what the thing is.
2. **Why it exists** — the problem it solves.
3. **Mental model** — how to think about it.
4. **TeamFlow implementation** — real files and real code.
5. **Code walkthrough** — block-by-block explanation of nontrivial code.
6. **Django/DRF comparison** — when it genuinely helps.
7. **Production perspective** — multi-worker, failure, performance behavior.
8. **Common mistakes** — including Django-developer-specific traps.
9. **Cheat sheet + review questions**.

## Feature map (what actually exists)

```
app/
├── main.py                 app factory, middleware wiring, lifespan
├── api/
│   ├── deps.py             auth, tenant context, access dependencies
│   ├── router.py           one include point for all v1 routers
│   └── routes/             14 routers (auth, orgs, projects, tasks, ...)
├── models/                 16 SQLModel tables
├── schemas/                request/response models (never leak DB fields)
├── services/               business rules, authorization, audit, events
│   └── integrations/       storage (MinIO), email, webhook signing
├── repositories/           every SQL query lives here
├── core/                   config, db, redis, security, logging, middleware,
│                           exceptions, rate limiting, idempotency
├── websocket/              connection manager + Redis listener + WS endpoint
└── workers/                Celery app + tasks (email, webhooks, cleanup)
migrations/                 Alembic (async env, one initial migration)
tests/                      69 functional tests (unit/integration/workers)
```

Honest coverage notes live in [`mastery/10-what-i-actually-master.md`](mastery/10-what-i-actually-master.md).

## Conventions used in lessons

- Paths are relative to the repository root (`app/services/tasks.py`).
- Code excerpts are verbatim from the repository unless marked *simplified*.
- 🔵 marks Django/DRF comparisons.
- ⚠️ marks common mistakes or production traps.
