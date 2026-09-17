# FastAPI 08 — Middleware

## Concept

Middleware wraps the entire ASGI application: it sees every request/response, can
modify both, and runs outside routing and dependency resolution. FastAPI
middleware is Starlette middleware — `BaseHTTPMiddleware` (convenient,
limited) or pure ASGI middleware (full control, recommended for anything
non-trivial).

## Why it exists

Some concerns apply to *all* requests and must run before routing:
correlation ids, access logs, CORS, idempotency replay. Dependencies can't do
this because dependencies run per-route, after routing has matched.

## TeamFlow's middleware stack

`app/main.py`:

```python
app.add_middleware(RequestContextMiddleware)
app.add_middleware(IdempotencyMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
    expose_headers=["X-Request-ID", "Idempotency-Replayed"],
)
```

⚠️ **Order trap**: Starlette builds the stack so the **last added middleware is
outermost** (runs first on the request path). Effective order:

```
CORS → Idempotency → RequestContext → routing → deps → handler
```

Consequences you can reason about:

- CORS runs first so preflight `OPTIONS` requests and error responses still get
  CORS headers.
- Idempotency sees requests *after* CORS but before routing; it can short-circuit
  and return a stored response without hitting handlers or dependencies.
- RequestContext sees everything except CORS preflight (which CORS answers
  itself) — fine, preflights don't need access logs.

## 1. RequestContextMiddleware — pure ASGI

`app/core/middleware.py`:

```python
class RequestContextMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        request_id = headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_ctx.set(request_id)
        start = time.perf_counter()
        status_holder = {"status": None}

        async def send_wrapper(message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                MutableHeaders(scope=message).append("x-request-id", request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            ...
            logging.getLogger("app.access").info("%s %s -> %s (%.1fms)", ...)
            request_id_ctx.reset(token)
```

Why pure ASGI instead of `BaseHTTPMiddleware`:

- `BaseHTTPMiddleware` buffers/rewraps responses and has a history of subtle
  issues with streaming, `background` tasks, and WebSocket scopes.
- Pure ASGI handles WS scopes explicitly (`if scope["type"] != "http"`) and
  passes them straight through.
- The wrapper chain (`send_wrapper`) is the standard technique for observing
  responses without consuming them.

The contextvar (`request_id_ctx` from `app/core/logging.py`) is how the request
id reaches log records *without props-drilling* into every function. This is the
async-safe replacement for thread-local request state — contextvars propagate
across `await` boundaries within a task.

## 2. IdempotencyMiddleware — stateful, DB-backed

`app/core/idempotency.py`, condensed:

```python
class IdempotencyMiddleware:
    HEADER = "idempotency-key"
    IDEMPOTENT_METHODS = frozenset({"POST", "PATCH", "DELETE"})

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope.get("method") not in self.IDEMPOTENT_METHODS:
            await self.app(scope, receive, send); return

        raw_key = Headers(scope=scope).get(self.HEADER)
        if not raw_key:
            await self.app(scope, receive, send); return
        if not VALID_KEY.match(raw_key):
            await _send_json(send, 400, {"detail": "Invalid Idempotency-Key"}); return

        body = await _collect_body(receive)
        request_hash = hashlib.sha256(body).hexdigest()
        identity = _identity(headers, scope)                 # JWT sub or client IP
        scope_key = f"{identity}|{scope['method']}|{scope['path']}|{raw_key}"

        decision = await self._claim(scope_key, scope["path"], scope["method"],
                                     identity, request_hash)
        if decision.action == "reject":
            await _send_json(send, decision.status_code, decision.body,
                             decision.headers, decision.raw_body)
            return

        captured = {"status": None, "chunks": bytearray(), "content_type": None}

        async def send_wrapper(message): ...                 # capture response

        body_state = {"done": False}

        async def replay_receive():                          # re-feed the body
            if body_state["done"]:
                return {"type": "http.disconnect"}
            body_state["done"] = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, replay_receive, send_wrapper)

        status = captured["status"]
        payload = bytes(captured["chunks"])
        if status is not None and status < 500 and len(payload) <= MAX_REPLAY_BYTES:
            await self._store_response(scope_key, status, captured["content_type"],
                                       payload.decode("utf-8", "replace"))
        elif status is not None:
            await self._mark_failed(scope_key)
```

The two ASGI subtleties every reviewer should understand:

1. **Body consumption.** ASGI bodies are streams read via `receive()`. Having
   read the body to hash it, the middleware must hand the app a `receive`
   function that replays it (`replay_receive`). This is the kind of detail
   `BaseHTTPMiddleware` hides — and occasionally gets wrong.
2. **Response capture.** Responses arrive as `http.response.start` +
   `http.response.body` messages; buffering them requires wrapping `send`.
   TeamFlow caps replay storage at 1 MB.

The actual idempotency semantics live in `_claim`
(`app/core/idempotency.py`): unique-constraint claim row → in-flight 409,
hash-mismatch 422, completed replay, stale re-claim. Transaction correctness is
analyzed in `database/06-transactions.md`.

## 3. CORS

Configured with an explicit allow-list (`settings.cors_origins`), explicit
methods/headers, and `allow_credentials=True`. Why both credentials and an
origin list? Because `allow_origins=["*"]` + credentials is forbidden by
browsers and by security common sense; a list is mandatory. Exposing
`Idempotency-Replayed` and `X-Request-ID` is required for the browser to *read*
those headers.

## Middleware vs dependency — the decision table

| Need | Use |
| --- | --- |
| Runs before routing / needs raw ASGI | middleware |
| Per-route, typed inputs, usable return value | dependency |
| Global logging/IDs | middleware |
| Auth | dependency (route-dependent, needs OpenAPI docs) |
| Body/response transformation | middleware |
| Grouping of resources + resource loading | dependency |

## Django/DRF comparison 🔵

| Django | FastAPI |
| --- | --- |
| `MIDDLEWARE` list (top = outermost) | `add_middleware` (last = outermost ⚠️) |
| `process_request`/`process_response` | pure ASGI `__call__` |
| DRF `DEFAULT_PERMISSION_CLASSES` (global auth) | dependency per route |
| `request.id` set by middleware | contextvar + logging filter |
| Middleware for CSRF | (no direct analog; token API — see `production/07-security.md`) |

Django's middleware order intuition is *inverted* in FastAPI. This single fact
causes real production bugs (logging middleware that never sees errors because
it sits inside the exception handler, etc.).

## Production perspective

- Middleware runs for **every** request; a middleware that opens a DB session
  per request doubles connection usage. TeamFlow's middleware opens a session
  only for idempotent writes with a key (mostly a no-op path).
- Middleware exceptions bypass the `AppError` handlers (they run outside the
  exception-handling middleware FastAPI installs). TeamFlow's middleware
  therefore returns its own JSON responses for its own error cases (invalid
  key → 400).
- Logging middleware must never log bodies or Authorization headers — TeamFlow
  logs method/path/status/duration only.
- With multiple workers, middleware state is per-process — never use it for
  anything shared (that's what Redis is for).

## Common mistakes

1. **Using `BaseHTTPMiddleware` and losing WebSocket scopes** or breaking
   streaming — TeamFlow's pure ASGI style avoids the class entirely.
2. **Expecting middleware order = add order.** It is reversed.
3. **Putting auth in middleware.** You lose per-route control and OpenAPI
   security documentation.
4. **Forgetting to re-feed the body** after reading it (idempotency) — the route
   then sees an empty body and validation fails mysteriously.
5. **Returning a `Response` from pure ASGI middleware** — you must send ASGI
   messages yourself (see `_send_json`).

## Cheat sheet

```python
class MyMiddleware:
    def __init__(self, app): self.app = app
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        # wrap receive/send as needed, then:
        await self.app(scope, receive, send)

app.add_middleware(MyMiddleware)   # remember: last added = outermost
```

## Review questions

1. Why is CORS added last in `create_app` and what does that imply for error
   responses?
2. Where does the request id come from, and how does it end up in log records
   without being passed as a function argument?
3. Why must the idempotency middleware replay the request body?
4. Why are `AppError` handlers not applied to exceptions raised inside
   middleware?
