# FastAPI 11 — BackgroundTasks (and why TeamFlow doesn't use them)

## Concept

`BackgroundTasks` lets a route enqueue a function to run **after the response is
sent**, in the same process. `background_tasks.add_task(fn, *args)` — no queue,
no broker, no separate worker.

```python
from fastapi import BackgroundTasks

@router.post("/thing")
async def create(background_tasks: BackgroundTasks):
    background_tasks.add_task(send_welcome_email, user.email)
    return {"ok": True}
```

## Why it exists

For genuinely small, fast, best-effort follow-ups (a log line, a metrics ping,
a tiny cache warm) a full Celery round trip is overkill.

## Why TeamFlow does not use it

TeamFlow has four pieces of "work after response" and it routes **all of them**
through Celery or Redis instead. The reasoning is the lesson here.

| Work | TeamFlow mechanism | Why not BackgroundTasks |
| --- | --- | --- |
| Email (invites, reset links) | `celery_app.send_task("teamflow.send_email", ...)` | Needs retries; if SMTP is down the email must eventually arrive |
| Webhook delivery | DB row + Celery task with backoff | Needs retries, delivery tracking, timeouts, and survival across deploys |
| WS event fan-out | `redis.publish` (awaited inline, ~sub-ms) | It's not "background": it's part of the request's side effects and must happen immediately |
| Dashboard cache invalidation | Redis `DEL` inline | Same — instant and cheap |

The failure modes of `BackgroundTasks` that matter at production scale:

1. **No retries.** The function runs once; if it raises, the work is lost
   (Starlette logs the exception).
2. **Process-bound.** Tasks die with the worker on deploy/restart. During a
   rolling deploy, pending emails vanish.
3. **Lives in the request-serving event loop.** A slow background function
   occupies the same loop that serves traffic — the "background" work can
   *delay other requests* if it is CPU-bound or forgets to be async-safe.
4. **No observability.** Nothing tracks success/failure except logs; TeamFlow's
   webhook deliveries are *rows* you can query (`GET /webhooks/{id}/deliveries`).

## What TeamFlow does instead — the pattern

`app/services/events.py` (webhooks):

```python
matching = await WebhookRepository(db).active_for_org_and_event(organization_id, event)
...
for webhook in matching:
    delivery = await delivery_repo.add(WebhookDelivery(...))
    delivery.payload["id"] = str(delivery.id)

await db.commit()  # deliveries are durable before any enqueue attempt

for delivery in pending:
    try:
        await run_in_threadpool(
            celery_app.send_task, "teamflow.deliver_webhook", [str(delivery.id)]
        )
    except Exception:
        logger.exception("Failed to enqueue webhook delivery %s", delivery.id)
```

Four production properties this buys:

1. **Durability before enqueue** — the webhook event exists in Postgres even if
   the broker is down; the cleanup task re-enqueues stranded `pending` rows
   (`app/workers/tasks.py`, `cleanup_expired_data`).
2. **`run_in_threadpool` for the blocking call** — `celery_app.send_task`
   (kombu) is a *synchronous* Redis client call. Calling it directly in an
   async endpoint would block the event loop. This one-liner is the difference
   between "fast API" and "API that hiccups on every webhook org".
3. **Fire-and-track** — the task id is not stored; the *delivery row* is the
   source of truth.
4. **Retries in the worker**, not in the request.

## When BackgroundTasks *would* be acceptable

Teaching honesty: `BackgroundTasks` is a reasonable choice when **all** of these
hold:

- losing the task is acceptable (best-effort),
- it takes milliseconds (no network calls you can't afford),
- it is fine for it to re-run zero or one times (not exactly-once needs),
- no other worker/process must observe it.

Example that fits: incrementing an in-process counter, writing an audit line to
stdout. Example that does **not** fit: anything in TeamFlow's list above —
that's why the codebase has zero `BackgroundTasks` imports.

## Django/DRF comparison 🔵

| Django | FastAPI |
| --- | --- |
| `transaction.on_commit(lambda: send_email(...))` (same-process, no retry) | `BackgroundTasks` (same idea, ASGI flavor) |
| `celery_app.delay(...)` after commit | `celery_app.send_task(...)` after commit (TeamFlow) |
| `django-q`, `huey`, cron | Celery Beat (TeamFlow) |

The Django analog of TeamFlow's webhook pattern is exactly
`transaction.on_commit(lambda: deliver.delay(delivery.id))` — durable row first,
enqueue after commit. Same reasoning, same failure analysis.

## Production perspective

- **`on_commit` semantics**: TeamFlow enqueues *after* `await db.commit()` —
  the async equivalent of Django's `transaction.on_commit`. Enqueueing before
  commit risks a worker picking up a delivery that the transaction then rolls
  back.
- **Broker latency**: `send_task` is a network call (~ms). Doing it inside the
  request via threadpool adds a small constant cost; doing it *after* the
  response (BackgroundTasks) would hide that cost but lose durability. TeamFlow
  chooses durability.
- **Idempotency**: because workers can redeliver, the receiver dedupes on
  `X-TeamFlow-Delivery` and the task short-circuits on
  `status == "success"` (`infrastructure/09-webhooks.md`).

## Common mistakes

1. **Using BackgroundTasks for email** because "it's just an email" — no
   retries, dies on deploy, invisible failures.
2. **Passing ORM objects into background tasks.** After the response, the
   request's DB session is closed. TeamFlow passes *ids* (`str(delivery.id)`)
   and the task loads its own session (`app/core/db_sync.py`).
3. **Assuming `add_task` runs concurrently.** It runs after the response within
   the same loop; it is sequencing, not parallelism.
4. **Calling a blocking library from a background task in an async app** — the
   same event-loop rules apply (`async/03-blocking-vs-nonblocking.md`).

## Cheat sheet

```python
# Best-effort, tiny, same-process:
background_tasks.add_task(fn, arg)

# Durable, retried, cross-process (TeamFlow's choice):
row = await repo.add(JobRow(...)); await db.commit()
await run_in_threadpool(celery_app.send_task, "teamflow.task_name", [str(row.id)])
```

## Review questions

1. Name the four properties TeamFlow gains by using a DB row + Celery instead
   of BackgroundTasks for webhooks.
2. Why is `celery_app.send_task` wrapped in `run_in_threadpool`?
3. Where is the async equivalent of Django's `transaction.on_commit` in
   `dispatch_webhooks`, and why does the order matter?
4. Design a case in TeamFlow where `BackgroundTasks` *would* be the right
   choice, and justify it against the four criteria.
