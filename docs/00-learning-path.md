# 00 — Learning Path

## Goal

After this course you should be able to:

1. Read any FastAPI codebase and explain what each layer is responsible for.
2. Review agent-generated FastAPI code and spot architectural/security mistakes.
3. Design a similar production system (multi-tenant API + workers + realtime).

## Recommended order

The order below builds concepts incrementally. Each section assumes the previous.

### Phase 1 — Orientation (read first, ~1h)

| # | Lesson | Why |
| --- | --- | --- |
| 1 | [01-project-overview](01-project-overview.md) | Domain + feature inventory |
| 2 | [02-architecture](02-architecture.md) | The layers and their rules |
| 3 | [03-request-lifecycle](03-request-lifecycle.md) | One request end-to-end |

### Phase 2 — FastAPI core (~4h)

Read `fastapi/01` → `fastapi/13` in order. Do not skip
[06-dependency-injection](fastapi/06-dependency-injection.md); FastAPI's `Depends`
is the single most important idea in the framework and replaces a large part of
DRF's machinery.

### Phase 3 — Data layer (~3h)

`database/01` → `database/09`. Key lessons:
[04-queries](database/04-queries.md), [06-transactions](database/06-transactions.md),
[08-loading-and-n-plus-one](database/08-loading-and-n-plus-one.md).

### Phase 4 — Auth + multi-tenancy (~2h)

`auth/01` → `auth/07`. If you only read one:
[07-multi-tenancy](auth/07-multi-tenancy.md) — it is the backbone of the whole app.

### Phase 5 — Architecture deep dive (~2h)

`architecture/01` → `07`. This is where the "why" lives.

### Phase 6 — Async (~1h)

`async/01` → `04`. The most common Django-dev trap: assuming `async def` means
nothing blocks.

### Phase 7 — Infrastructure (~4h)

`infrastructure/01` → `09`. Redis, Celery, WebSockets, MinIO, HTTPX, webhooks.

### Phase 8 — Testing (~2h)

`testing/01` → `06`. Learn what to test against real infrastructure vs mock.

### Phase 9 — Production (~2h)

`production/01` → `08`. Docker, config, nginx, workers, health, logs, security.

### Phase 10 — Mastery (~1h + practice)

`mastery/01` → `10`. Cheat sheets first, then the
[final assessment](mastery/08-final-assessment.md), then the honest
[what you actually mastered](mastery/10-what-i-actually-master.md).

## Suggested exercise loop

For each lesson:

1. Read the concept section.
2. Open the referenced files in the repository and re-read the actual code.
3. Answer the review questions in your head *before* checking the answers.
4. Try to reproduce one small piece from memory (e.g., write a new endpoint in
   the same style: router → schema → dependency → service → repository).

## Prerequisites to run the project

```bash
docker compose up -d db redis minio minio-setup
uv run alembic upgrade head
uv run uvicorn app.main:app --reload      # http://localhost:8000/docs
uv run pytest tests -q                    # 69 functional tests
```

## Time budget summary

| Phase | Content | Hours |
| --- | --- | --- |
| 1 | Orientation | 1 |
| 2 | FastAPI core | 4 |
| 3 | Database | 3 |
| 4 | Auth | 2 |
| 5 | Architecture | 2 |
| 6 | Async | 1 |
| 7 | Infrastructure | 4 |
| 8 | Testing | 2 |
| 9 | Production | 2 |
| 10 | Mastery | 1 |
| **Total** | | **~22h** |
