# Async 03 — Blocking vs Non-Blocking

## Concept

A call is **blocking** if it occupies the calling thread until it completes
(network, disk, sleep, CPU work). In async code, blocking calls must be either
avoided (use the async equivalent) or offloaded (`run_in_threadpool`).

## The decision table TeamFlow applies to every I/O in a request

| Need | Async? | TeamFlow choice |
| --- | --- | --- |
| PostgreSQL | yes | `asyncpg` engine (`app/core/db.py`) |
| Redis | yes | `redis.asyncio` (`app/core/redis.py`) |
| Outbound HTTP | yes | would use `httpx.AsyncClient` — but the only outbound HTTP (webhooks) lives in **workers** |
| S3/MinIO presign | pure CPU (HMAC) | inline, no I/O |
| S3 `stat`/`remove` | sync SDK, network | `run_in_threadpool` inside `StorageClient` |
| Celery enqueue | sync kombu | `run_in_threadpool` at call sites |
| SMTP | sync/async hybrid | Celery task: `aiosmtplib` via `asyncio.run` (no loop running there) |
| Email templating | CPU, trivial | inline in worker |
| bcrypt | CPU, ~100ms | inline in auth services (accepted, documented) |

## The two offloading patterns, side by side

```python
# app/services/events.py — explicit at the call site
await run_in_threadpool(
    celery_app.send_task, "teamflow.deliver_webhook", [str(delivery.id)]
)
```

```python
# app/services/integrations/storage.py — hidden inside the client
async def stat(self, key: str) -> dict | None:
    """Async wrapper over blocking network I/O."""
    try:
        return await run_in_threadpool(self._stat_sync, key)
    except S3Error as exc: ...
```

Design guidance TeamFlow follows: **if the blocking is inherent to a small
client, hide the offload inside the client** (callers get a clean async API);
**if the chosen call is a library policy decision** (Celery producer), offload
at the call site so it is visible in the service's flow.

## Why presign is allowed inline

`presign_put`/`presign_get` only compute an HMAC signature locally — no socket
is touched. CPU cost is microseconds. Making it async would be noise. This is
the distinction: *sync API* ≠ *blocking call*. Reviewers must look at what the
call actually does, not just its signature.

## bcrypt — the deliberate exception

```python
user.hashed_password = security.hash_password(data.new_password)   # ~100ms CPU
```

| Property | Value |
| --- | --- |
| Cost | ~100–250ms at cost factor 12 |
| Frequency | auth endpoints only; rate limited (5/min/email + IP) |
| Alternative | `run_in_threadpool(hash_password, pw)` |
| Why not | one extra thread hop for a bounded, rare, rate-limited cost |

The expected-review answer: *"It blocks the loop for ~100ms per auth attempt,
bounded by rate limits; moving to a threadpool is the known upgrade if auth
becomes hot."* Stating the trade-off is what separates an accepted exception
from a defect.

## Async SMTP in a sync worker (the odd one out)

`app/services/integrations/email.py`:

```python
def _send_smtp(to, subject, body) -> None:
    import asyncio
    async def _send() -> None:
        import aiosmtplib
        ...
        await aiosmtplib.send(message, hostname=..., ...)
    asyncio.run(_send())
```

Why this is fine: Celery workers are sync, have no running loop, and each task
may create one (`asyncio.run`). The alternative (`smtplib` sync) would block a
worker thread during SMTP — equally "fine" in a worker, but TeamFlow already had
`aiosmtplib` and reuses the same send path for both backends. The rule that
matters: **never call `asyncio.run` inside the API process** (loop already
running → `RuntimeError`).

## Detecting blocking code in review

1. Any import of `requests`, `psycopg`, `time.sleep`, `boto3` (sync), `smtplib`
   in `app/api/` or `app/services/` (except workers/integrations) — flag it.
2. Any sync repository/session call in an async function — `MissingGreenlet`
   will tell you anyway.
3. Any `.get()`/`.execute()` on a sync `Session` in the API path.
4. Long loops over big Python collections in handlers (CPU blocking without a
   library tell).

## Django/DRF comparison 🔵

| Django | FastAPI |
| --- | --- |
| Sync ORM in threads — blocking is normal | blocking in the loop is a defect |
| `requests` everywhere | `httpx` (async in API, sync in workers) |
| `send_mail` inline (blocks the request) | Celery task (never blocks requests) |
| `time.sleep` in a view blocks one thread | blocks the whole worker |
| DRF throttling | Redis sliding window dependency |

## Production perspective

- Threadpool exhaustion replaces loop starvation as the failure mode once you
  offload aggressively — size `anyio`'s limiter (default 40) knowingly.
- The one-line discipline ("offload sync I/O") has an outsized payoff: it is
  the difference between a worker serving hundreds of concurrent requests and
  one serving one-at-a-time.
- Health `/ready` does a DB round trip and Redis ping — an early-warning probe
  for loop/pool trouble.

## Review questions

1. Why is `presign_put` allowed inline while `stat` is not?
2. Where would you put the offload for a new sync SDK (client-internal vs call
   site), and what decides it?
3. What happens if someone calls `asyncio.run(...)` inside `app/services/`?
4. Give the full expected-review answer for the inline bcrypt call.
