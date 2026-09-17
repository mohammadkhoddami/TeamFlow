# Infrastructure 04 — Celery

## Concept

Celery moves work out of the request path to worker processes fed by a broker
(Redis here). TeamFlow uses it for: transactional email, webhook delivery,
cleanup, cache warming, and due-task reminders.

```
FastAPI ──(send_task by name)──► Redis (broker) ──► Celery worker ──► sync DB / SMTP / HTTPX
   ▲                                                        │
   └────────────── teamflow.* task names registered ────────┘
```

## Why Celery (vs BackgroundTasks or cron)

- **Retries with backoff** — webhooks and email must survive transient failures
  (`fastapi/11-background-tasks.md` compares with `BackgroundTasks`).
- **Durability** — tasks wait in the broker if workers restart mid-deploy.
- **Isolation** — an SMTP timeout or slow receiver occupies a worker, not an
  API event loop.
- **Scheduling** — Beat owns periodic jobs (`infrastructure/05-celery-beat.md`).

## The app — `app/workers/celery_app.py`

```python
celery_app = Celery("teamflow", broker=settings.celery_broker_url,
                    backend=settings.celery_result_backend)

celery_app.conf.update(
    task_default_queue="default",
    task_serializer="json", result_serializer="json", accept_content=["json"],
    timezone="UTC", enable_utc=True,
    task_acks_late=True,                       # redeliver if the worker dies mid-task
    worker_prefetch_multiplier=1,              # one task at a time per process slot
    broker_connection_retry_on_startup=True,
    task_track_started=True,
    result_expires=3600,
    beat_schedule={ ... },                     # periodic jobs (lesson 05)
)

celery_app.conf.task_queues = (Queue("default"), Queue("emails"), Queue("webhooks"))
celery_app.conf.task_routes = {
    "teamflow.send_email": {"queue": "emails"},
    "teamflow.deliver_webhook": {"queue": "webhooks"},
}
```

Decisions worth understanding:

- **JSON serialization only.** Pickle is a remote-code-execution footgun; reject
  it (`accept_content=["json"]`).
- **`task_acks_late=True` + `prefetch_multiplier=1`**: a worker that crashes
  mid-task gets the task redelivered; prefetch 1 avoids a worker hoarding tasks
  while busy. Consequence: tasks must be **idempotent** — see delivery
  short-circuits below.
- **Queues** separate concerns so you can scale email independently from
  webhook delivery, and a webhook backlog can't delay password-reset emails.
- **`beat_schedule`** lives in the app config (single source of truth).

## Shared HTTP client per worker process

```python
http_client: httpx.Client | None = None

@worker_process_init.connect
def init_worker(**kwargs):
    global http_client
    http_client = httpx.Client(timeout=settings.webhook_timeout_seconds,
                               trust_env=settings.webhook_httpx_trust_env,
                               limits=httpx.Limits(max_connections=20,
                                                   max_keepalive_connections=10))

@worker_process_shutdown.connect
def shutdown_worker(**kwargs):
    global http_client
    if http_client is not None:
        http_client.close()
        http_client = None
```

One client per worker *process* — connection pooling and keep-alive without the
per-request cost (`infrastructure/08-httpx.md`).

## The tasks — `app/workers/tasks.py`

### Email (autoretry with backoff)

```python
@shared_task(bind=True, name="teamflow.send_email",
             autoretry_for=(Exception,), retry_backoff=True,
             retry_backoff_max=300, retry_jitter=True, max_retries=3)
def send_email_task(self, to: str, kind: str, ctx: dict[str, str]) -> dict:
    from app.services.integrations.email import render, send_sync
    subject, body = render(kind, ctx)
    send_sync(to, subject, body)
    return {"status": "sent", "to": to, "kind": kind, "attempt": self.request.retries + 1}
```

`retry_backoff=True` = exponential (2, 4, 8s…), capped at 300s, with jitter to
avoid synchronized retry storms. Renders and sends synchronously via the
configured backend (console in dev, SMTP via `aiosmtplib` otherwise).

### Webhook delivery — the flagship task

```python
@shared_task(bind=True, name="teamflow.deliver_webhook",
             max_retries=settings.webhook_max_retries)
def deliver_webhook(self, delivery_id: str) -> dict:
    ...
    attempt = self.request.retries + 1
    with session_scope() as db:
        delivery = db.get(WebhookDelivery, uuid.UUID(delivery_id))
        if delivery.status == DeliveryStatus.SUCCESS:
            return {"status": "already_delivered", "delivery_id": delivery_id}
        ...
        body = json.dumps(delivery.payload).encode()
        timestamp = str(int(datetime.now(UTC).timestamp()))
        signature = webhook_signing.sign_payload(webhook.secret, timestamp, body)
        delivery.attempts = max(delivery.attempts, attempt)
        url, event = webhook.url, delivery.event

    # outside the DB session: the HTTP call happens with no transaction open
    response = client.post(url, content=body, headers={..., "X-TeamFlow-Signature": signature})
    verdict = _classify_response(response.status_code)
    with session_scope() as db:
        ...update status/attempts/response_status/delivered_at...
```

Production properties, item by item:

| Property | Mechanism |
| --- | --- |
| Idempotent redelivery | `status == SUCCESS` short-circuits |
| Attempt accounting survives retries | `attempts = max(attempts, attempt)` persisted per attempt |
| No transaction held during HTTP | `session_scope` blocks end before `client.post` |
| Retry policy | `_retry_or_fail`: backoff `min(5 * 2**attempt, 300)`; final failure marks `failed` |
| Permanent vs transient | `_classify_response`: 4xx (except 408/429) = permanent, no retry |
| Failure observability | `last_error`, `response_status`, `attempts` stored per delivery row |
| Stranded recovery | cleanup task re-enqueues `pending` older than 10 min |

Why sync SQLAlchemy here? Workers have no event loop; `session_scope`
(`app/core/db_sync.py`) opens a short-lived sync session per task — simpler and
correct. The consequence (workers can't reuse async repositories) is discussed
in `async/04-async-in-teamflow.md`.

### Cleanup

```python
@shared_task(name="teamflow.cleanup_expired_data")
def cleanup_expired_data() -> dict:
    removed = {"idempotency_keys": 0, "pending_attachments": 0, "deliveries_requeued": 0}
    with session_scope() as db:
        removed["idempotency_keys"] = IdempotencyRepository(db).purge_older_than(cutoff)
        for attachment in AttachmentRepository(db).pending_older_than(...):
            StorageClient.from_settings().remove(attachment.storage_key)     # orphan bytes
            db.execute(delete(Attachment).where(...))
        for delivery in WebhookDeliveryRepository(db).stale_pending(...):
            celery_app.send_task("teamflow.deliver_webhook", [str(delivery.id)])
            removed["deliveries_requeued"] += 1
    return removed
```

Three purges in one pass: idempotency TTL, stale upload intents (rows + orphan
objects), and **stranded webhooks** — the compensating action for broker
downtime (`architecture/06-transactions.md`).

## What belongs in Celery (TeamFlow's boundary)

| Put in Celery | Kept inline |
| --- | --- |
| Email (retries, SMTP latency) | WS publish (sub-ms Redis) |
| Webhook HTTP (retries, timeouts, tracking) | Cache invalidation (sub-ms Redis) |
| Cleanup (scheduled, batch) | Audit/notification inserts (transactional) |
| Cache warming, reminders (scheduled) | Any DB write that must be atomic with the request |
| | Anything the client is waiting for |

## Django/DRF comparison 🔵

The Django+Celery mental model transfers almost 1:1. Differences: task module
registration is explicit (`celery_app` imports `app.workers.tasks`), routing is
declarative per task name, and the enqueue call sites are async-aware
(`run_in_threadpool`) — the last one is the only FastAPI-specific wrinkle.

## Common mistakes

1. **Passing ORM objects to tasks** — serialize ids; the task opens its own
   session (`str(delivery.id)`).
2. **Making tasks non-idempotent** — `acks_late` guarantees redelivery; the
   `SUCCESS` short-circuit exists for this.
3. **Holding a DB transaction during HTTP/SMTP** — holds locks and pool
   connections.
4. **Pickle serialization** — RCE risk; JSON everywhere.
5. **Retrying permanently-failing 4xx forever** — classify and give up.

## Cheat sheet

```
enqueue:  await run_in_threadpool(celery_app.send_task, "teamflow.task", [args])
task:     @shared_task(bind=True, name="teamflow.x", max_retries=N)
session:  with session_scope() as db: ...
queues:   default | emails | webhooks
```

## Review questions

1. Why does `deliver_webhook` close its DB session before making the HTTP call?
2. What makes the task safe to redeliver after `acks_late`? Where is that guard?
3. Which queue would you scale first if password-reset emails lag during a
   webhook storm, and why?
4. What is the compensating mechanism for a broker outage at enqueue time?
