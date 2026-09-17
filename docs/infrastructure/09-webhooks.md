# Infrastructure 09 — Webhooks

## Concept

Webhooks push events to customer-controlled URLs. The producing system must
assume the receiver is slow, down, or malicious. TeamFlow's design: durable
delivery rows, Celery retries with backoff, HMAC signatures, and receiver-side
idempotency.

## The pipeline

```
business event (task.created, comment.created, ...)
        │  service layer, after commit
        ▼
events.dispatch_webhooks(...)                    app/services/events.py
   ├── match active webhooks for (org, event)
   ├── INSERT one WebhookDelivery row per webhook   (flush)
   ├── commit delivery rows                         (durable intent)
   └── enqueue teamflow.deliver_webhook per row     (threadpool)
                │
                ▼
deliver_webhook (Celery, queue=webhooks)         app/workers/tasks.py
   ├── short-circuit if already SUCCESS            (idempotent redelivery)
   ├── sign body, POST via shared httpx client     (5s timeout)
   ├── classify 2xx / 4xx-permanent / transient
   └── update row: attempts, response_status, last_error, delivered_at
                │
                ▼
cleanup_expired_data (every 6h) re-enqueues stranded PENDING rows
```

## Event production — `app/services/events.py`

```python
async def dispatch_webhooks(db, *, organization_id, event, data) -> None:
    matching = await WebhookRepository(db).active_for_org_and_event(organization_id, event)
    if not matching:
        return

    delivery_repo = WebhookDeliveryRepository(db)
    pending: list[WebhookDelivery] = []
    for webhook in matching:
        delivery = await delivery_repo.add(WebhookDelivery(
            webhook_id=webhook.id, event=event,
            payload={"id": None, "event": event,
                     "organization_id": str(organization_id),
                     "created_at": now_iso(), "data": data},
        ))
        delivery.payload["id"] = str(delivery.id)
        pending.append(delivery)

    await db.commit()          # deliveries are durable before any enqueue attempt

    for delivery in pending:
        try:
            await run_in_threadpool(celery_app.send_task,
                                    "teamflow.deliver_webhook", [str(delivery.id)])
        except Exception:
            logger.exception("Failed to enqueue webhook delivery %s", delivery.id)
```

The transaction-ordering analysis: `database/06-transactions.md`. The key
invariants:

1. **No event without a business change** (called after the service's commit).
2. **No lost event on broker outage** — rows are `pending` and the sweeper
   retries.
3. **No blocking** — the kombu producer runs in a threadpool.

Emitted events (from the service layer): `task.created`, `task.updated`,
`task.completed` (on transition), `comment.created`. (`member.joined` is
defined in `WebhookEvent.ALL` but is not currently dispatched — an honest gap
noted for review.)

## Delivery — `app/workers/tasks.py`

### Idempotency at every level

| Layer | Mechanism |
| --- | --- |
| Task redelivery (acks_late) | `if delivery.status == SUCCESS: return already_delivered` |
| Attempt accounting | `attempts = max(delivery.attempts, attempt)` (no double count) |
| Receiver dedupe | `X-TeamFlow-Delivery: <delivery uuid>` header — stable across retries |
| Sweeper re-enqueue | only rows still `pending` (never `success`) |

### Signing — `app/services/integrations/webhook_signing.py`

```python
def sign_payload(secret: str, timestamp: str, body: bytes) -> str:
    mac = hmac.new(secret.encode(), digestmod=hashlib.sha256)
    mac.update(f"{timestamp}.".encode())
    mac.update(body)
    return "v1=" + mac.hexdigest()
```

Request headers:

```
X-TeamFlow-Event:     task.created
X-TeamFlow-Delivery:  3f2a...            (dedupe key)
X-TeamFlow-Timestamp: 1717000000         (part of the signed payload)
X-TeamFlow-Signature: v1=<hex hmac>
```

- Signing `timestamp.body` binds the timestamp to the content, enabling the
  receiver to reject replayed old requests (recommended: reject >5 min old).
- The `v1=` prefix versions the scheme without breaking old receivers.
- The per-webhook `secret` is generated server-side (`secrets.token_urlsafe(32)`)
  and returned **once** at creation (`WebhookCreated` schema).

Receiver verification recipe (documented behavior — no receiver in this repo):

```python
expected = "v1=" + hmac.new(secret, f"{ts}.".encode() + raw_body, sha256).hexdigest()
assert hmac.compare_digest(expected, received_signature)
assert abs(now - int(ts)) < 300
```

### Response classification — `_classify_response`

```python
def _classify_response(code: int) -> str:
    if 200 <= code < 300: return "success"
    if 400 <= code < 500 and code not in (408, 429): return "permanent"
    return "transient"
```

| Receiver response | TeamFlow action |
| --- | --- |
| 2xx | `success`, `delivered_at` stamped |
| 4xx (except 408/429) | `failed` immediately — retrying a 404 or 400 is pointless |
| 408/429/5xx/transport error | retry with backoff `min(5 × 2^attempt, 300)` up to 5 attempts, then `failed` |

This classification is the difference between a well-behaved sender and one
that hammers a misconfigured receiver forever.

## Tracking and observability

Every delivery is a row:

```
GET /organizations/{slug}/webhooks/{id}/deliveries
→ [{event, status, attempts, response_status, last_error, delivered_at}, ...]
```

That endpoint is the operator console: "did we deliver, how many attempts, what
did the receiver say". Audit action `webhook.created`/`webhook.deleted` covers
configuration changes.

## SSRF — the honest gap

`WebhookCreate` validates `AnyHttpUrl` (scheme/host shape) but **does not block
internal addresses** (127.0.0.1, 10.x, 169.254.x metadata endpoints). Admin+
users can therefore point webhooks at internal services. Threat model: an
admin of an org is already trusted inside the app, but a multi-tenant SaaS
should still restrict egress. Remedies (documented in
`production/07-security.md`): resolve the host and reject private CIDR ranges,
allow-list ports, or route delivery through an egress proxy.

## Django/DRF comparison 🔵

| Django | TeamFlow |
| --- | --- |
| `requests.post` in a `post_save` signal | durable row + Celery task |
| `django-webhook` / `drf-webhooks` packages | hand-rolled (this lesson) |
| retries via celery `autoretry_for` | manual classification + backoff |
| no delivery history | `webhook_deliveries` table + API |
| shared secret in settings | per-webhook generated secret, shown once |

The transferable architecture is language-agnostic: **durable intent →
asynchronous delivery → signed payload → observable attempts → idempotent
receiver**.

## Review questions

1. Why does `dispatch_webhooks` commit before enqueueing, and which failure
   does that ordering survive?
2. A receiver returns 404 forever. How many times does TeamFlow POST before
   giving up, and why so few?
3. Which header would a receiver use to deduplicate a redelivery, and where is
   its value created?
4. Explain the SSRF gap and the two most practical mitigations.
