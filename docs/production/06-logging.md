# Production 06 — Logging and Observability

## Concept

Observability here means: structured logs with request correlation, plus the
two health probes. No traces, no metrics endpoint — an honest scope.

## The logging stack

```
app/core/logging.py      setup + formatters + context filter
app/core/middleware.py   request id assignment, access log line
app/api/deps.py          binds user_id / org_id into the context
app/core/exceptions.py   exception logging (stack traces to logs only)
```

## Correlation: request id through contextvars

```python
# app/core/logging.py
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")
user_id_ctx: ContextVar[str] = ContextVar("user_id", default="-")
org_id_ctx: ContextVar[str] = ContextVar("org_id", default="-")

class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        record.user_id = user_id_ctx.get()
        record.org_id = org_id_ctx.get()
        return True
```

Every log record — anywhere in the app — gets the current request id, user, and
org stamped on it *without passing them as arguments*. Contextvars propagate
across `await` boundaries, which is what makes this work in async code (the
async-safe replacement for thread-locals).

Filled in at:

```python
# app/core/middleware.py — RequestContextMiddleware
request_id = headers.get("x-request-id") or uuid.uuid4().hex
token = request_id_ctx.set(request_id)
try:
    await self.app(scope, receive, send_wrapper)     # adds X-Request-ID to the response
finally:
    logging.getLogger("app.access").info("%s %s -> %s (%.1fms)", method, path, status, ms)
    request_id_ctx.reset(token)                       # vitally: reset per request

# app/api/deps.py
user_id_ctx.set(str(user.id))          # in get_current_user
org_id_ctx.set(str(org.id))            # in get_org_membership / access deps
```

The client can supply `X-Request-ID` (trace propagation); otherwise the server
generates one and echoes it on the response — a support ticket can quote one
header and you can find the exact log lines.

## Two formats

```python
if settings.log_json or settings.is_production:
    handler.setFormatter(JsonFormatter())          # machine-parseable
else:
    handler.setFormatter(logging.Formatter(
        "[%(levelname).1s %(asctime)s %(request_id)s] %(name)s: %(message)s"))
```

JSON for log shippers (ELK/Loki/CloudWatch); human format locally. Same records,
same context fields.

## The access log

```python
logging.getLogger("app.access").info(
    "%s %s -> %s (%.1fms)", scope.get("method"), path, status_holder["status"], duration_ms)
```

One line per request with method, path, status, duration, request id, user id,
org id (via the filter). `/health` paths are skipped — probe noise.

## What is never logged (and where that's enforced)

| Sensitive | Enforcement |
| --- | --- |
| Passwords | never passed to a logger; audit meta stores emails only |
| JWTs | `Authorization` header is never read by logging code |
| Secrets/config | `settings` is never logged; exceptions are formatted, not dumped |
| Request bodies | never captured (idempotency hashes them, doesn't log them) |
| DB internals | `SQLAlchemyError` logs the stack trace, not connection strings |

## Exception logging

```python
@app.exception_handler(SQLAlchemyError)
async def db_error_handler(request, exc):
    logger.exception("Database error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
```

Stack traces go to logs (`logger.exception`) with the request id; clients get a
constant message. The 404/403/422 paths are *not* exceptions in the log sense —
expected errors return responses without stack noise (they're `AppError`, not
logged as errors).

## Debug convenience vs production safety

`DEBUG=true` (dev only) makes Starlette render tracebacks in responses;
`DEBUG=false` returns the generic handler output. Same for `echo=settings.debug`
on the engine — SQL logging in dev, silent in prod.

## What's missing (honest list)

| Missing | Consequence | Upgrade path |
| --- | --- | --- |
| Metrics endpoint (`/metrics`) | no time-series dashboards | `prometheus-fastapi-instrumentator` or middleware counters |
| Distributed tracing | no cross-service spans (this is a monolith; workers are the boundary) | OpenTelemetry SDK + `instrument_app` |
| Celery task metrics | only task return values/logs | `celery-prometheus-exporter` |
| Alerting | none | derive from log/health signals |

Listed in `mastery/10-what-i-actually-master.md`. The current stack answers
"what happened in this request" (excellent) but not "how many 5xx per minute"
(absent).

## Django/DRF comparison 🔵

| Django | TeamFlow |
| --- | --- |
| `LOGGING` dict in settings | `setup_logging()` function |
| `django.request` logger + `ADMINS` emails | access log + exception handlers |
| `django-structlog` package for context | contextvars + `ContextFilter` (built in, no dep) |
| `X-Request-ID` via middleware add-on | `RequestContextMiddleware` |

Django's `request.user` gives per-request identity in logs only if you add it;
TeamFlow's contextvar approach gives identity *and* tenant to every line for
free once the dependency layer runs.

## Review questions

1. How does `org_id` get into a log line produced by a repository deep in the
   call stack?
2. Why is `request_id_ctx.reset(token)` in a `finally` block?
3. What does a support engineer need from a client to find the exact failing
   request in the logs?
4. Which two observability features are explicitly missing, and what is the
   first one you would add?
