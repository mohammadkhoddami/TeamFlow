# Performance & scale proof (M3 #37)

TeamFlow publishes explicit performance targets and the harness to verify
them. "Fast" is part of the product story: the numbers below are enforced in
CI-ish runs against the 1M-row seed corpus.

## Targets

| Path | Target (p95) | Notes |
| --- | --- | --- |
| Board tree (`GET /projects/{id}/tasks/tree`) on a 10k-task project | < 1 000 ms | Single bounded fetch + in-memory grouping |
| Task list, offset (`GET /organizations/{slug}/tasks`) | < 400 ms | First pages; deep offsets degrade (see cursor) |
| Task list, cursor (`GET /organizations/{slug}/tasks/cursor`) | < 300 ms | O(1) deep pages (keyset) |
| Search (`GET /organizations/{slug}/search`) | < 500 ms | Postgres FTS + GIN |
| Roadmap (`GET /projects/{id}/roadmap`) | < 500 ms | Single project fetch + group-by |
| Calendar (`GET /organizations/{slug}/calendar`) | < 300 ms | Due-date range on `ix_tasks_due_date` |

Budgets are measured on the reference deployment (1 vCPU API, Postgres 16,
1M-row seed) with warm caches.

## Query budgets

Endpoints have hard upper bounds on SQL statements per request, asserted in
`tests/integration/test_m3_performance.py`:

| Endpoint | Max queries |
| --- | --- |
| Task detail | 30 |
| Project task tree | 15 |
| Task list (page) | 30 |
| Cursor page | 25 |
| Roadmap | 20 |
| Calendar | 8 |

These budgets catch accidental N+1 regressions long before they show up in
latency graphs.

## Seed corpus

```bash
docker compose up -d db redis
# Default "heavy" preset (~1M rows, < 1 minute with COPY)
docker compose exec api uv run python scripts/seed_mock_data.py
# Reset + maximum size
docker compose exec api uv run python scripts/seed_mock_data.py --preset extreme --reset
```

The seed now covers M1/M2/M3 tables: sprints, releases, threaded comments,
comment reactions, activities, notifications with project/task pointers.

## Load test

`scripts/loadtest/k6_board.js` drives board/roadmap/listing and cursor
pagination, with thresholds encoded in the script:

```bash
k6 run \
  -e BASE_URL=https://arsene.ir/flow \
  -e API_TOKEN=tf_xxx \
  -e ORG=arsene \
  -e PROJECT=<project-uuid> \
  scripts/loadtest/k6_board.js
```

Use a personal access token (M3 #24) — no human password in CI.

## Cursor pagination

`GET /organizations/{slug}/tasks/cursor` orders by `(created_at DESC, id
DESC)` and returns an opaque `next_cursor`. Unlike `OFFSET`, cost does not
grow with page depth, and new rows never shift subsequent pages. Cursors are
validated; malformed values return 422.
