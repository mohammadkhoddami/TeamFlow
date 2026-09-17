# Infrastructure 08 — HTTPX

## Concept

HTTPX is the outbound HTTP client. TeamFlow's *only* outbound HTTP is webhook
delivery, which happens in Celery workers — so the client lives there, one
instance per worker process.

## The rule TeamFlow follows

> **One client per process, not per request.**

Creating a client per request (or per task execution) throws away TCP
connection reuse, TLS handshakes, and keep-alive — real latency and CPU costs
under volume. It also leaks connection pools if clients aren't closed.

## Implementation — `app/workers/celery_app.py`

```python
http_client: httpx.Client | None = None

@worker_process_init.connect
def init_worker(**kwargs: object) -> None:
    global http_client
    http_client = httpx.Client(
        timeout=settings.webhook_timeout_seconds,          # 5s default
        trust_env=settings.webhook_httpx_trust_env,        # proxy handling
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )

@worker_process_shutdown.connect
def shutdown_worker(**kwargs: object) -> None:
    global http_client
    if http_client is not None:
        http_client.close()
        http_client = None
```

| Setting | Why |
| --- | --- |
| `timeout=5s` | an unresponsive receiver must not occupy a worker slot indefinitely |
| `limits(max_connections=20)` | bounds sockets per worker; a slow receiver can't exhaust workers |
| `trust_env=configurable` | see the war story below |
| `worker_process_init` signal | one client per **forked process**, not per task |
| `worker_process_shutdown` | graceful close of the pool |

### The `trust_env` war story (real, from this project)

On a machine with a system proxy configured, httpx routed `localhost` webhook
deliveries through the proxy → every delivery got `502` instead of reaching the
local receiver. The fix:

```python
# app/core/config.py
webhook_httpx_trust_env: bool = True   # honor HTTP(S)_PROXY
# .env (dev): WEBHOOK_HTTPX_TRUST_ENV=false
```

The lesson: environment-based proxying is desirable in prod (egress proxies)
and hostile in dev (localhost interception). Making it a setting with a
documented symptom is the production-grade resolution.

## Timeouts

`settings.webhook_timeout_seconds = 5.0` is a **total** timeout in httpx
(connect+read+write+pool). For webhooks that is deliberate: a receiver slower
than 5s is a failure the retry policy should handle, and hanging sockets are
worse than fast failures.

## Retries live one layer up (not in httpx)

HTTPX has no retry logic by default — correctly so, because retries are policy.
TeamFlow's policy is Celery's (`infrastructure/04-celery.md`):

```
attempt 1 → 5s timeout / 5xx         → retry with countdown 10s
attempt 2 → ...                      → retry 20s
...
attempt 5 → final                    → mark delivery failed (last_error recorded)
4xx (except 408/429)                 → permanent, no retry
```

The DB delivery row records every attempt (`attempts`, `response_status`,
`last_error`), making retries observable — an HTTPX-level retry would hide them.

## Where HTTPX appears in the codebase

| Location | Mode | Purpose |
| --- | --- | --- |
| `app/workers/celery_app.py` | `httpx.Client` | shared webhook client (process lifecycle) |
| `app/workers/tasks.py` `deliver_webhook` | uses the shared client | the POST with HMAC headers |
| `tests/**` | `httpx.AsyncClient` (ASGITransport) | API tests without a network server |
| `tests/**` | `httpx.Client(trust_env=False)` | local receiver/webhook assertions |

Notably: **the API has no HTTPX client at all.** No API endpoint calls an
external service. If one ever does, the pattern is an `httpx.AsyncClient`
created in lifespan (not per request) — the mirrors of the worker signal
pattern.

## The task's use of the client

```python
from app.workers.celery_app import http_client

client = http_client or httpx.Client(
    timeout=settings.webhook_timeout_seconds,
    trust_env=settings.webhook_httpx_trust_env,
)
```

The `or` fallback exists so unit tests can run the task without the worker
signal (`tests/workers/test_webhook_delivery.py`), constructing an equivalent
client. In production `http_client` is always set by `worker_process_init`.

## Django/DRF comparison 🔵

| Django | TeamFlow |
| --- | --- |
| `requests` (sync) inline in views | HTTPX in workers; API makes no outbound calls |
| module-level `requests.Session()` | lifespan/signal-managed client with explicit limits |
| `requests` has no async | `httpx.AsyncClient` when an API path needs it |
| No standard lifecycle hook | `worker_process_init` / lifespan |

Django devs often create `requests.get(...)` calls ad hoc. The two things to
carry over: reuse a client (sessions/pools), and never make a blocking outbound
call in a request path that must stay responsive — in FastAPI that's
non-negotiable (`async/03`).

## Common mistakes

1. **`httpx.get(...)` per task** — new pool each time, no keep-alive; under load
   this is measurable.
2. **No timeout** — a hanged receiver holds a worker indefinitely.
3. **Retries inside httpx** while the task also retries — double retry storms.
4. **Ignoring proxies in dev** (or blindly trusting `X-Forwarded-For`/proxy env)
   — the 502 war story.
5. **Using `requests` in an async path** — blocking the loop.

## Cheat sheet

```python
# worker process
@worker_process_init.connect
def init_worker(**kw):
    global http_client
    http_client = httpx.Client(timeout=..., trust_env=..., limits=httpx.Limits(...))

# per task
client = http_client or httpx.Client(...)     # test fallback
response = client.post(url, content=body, headers=headers)
```

## Review questions

1. Why is the client created on a worker-process signal rather than at module
   import?
2. Where do retries happen, and why deliberately not inside HTTPX?
3. What does the `trust_env` setting control, and what real bug did it fix?
4. If an API endpoint needed to call an external service, what's the correct
   pattern in this codebase?
