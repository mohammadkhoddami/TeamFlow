# FastAPI 09 — Exception Handling

## Concept

FastAPI lets you register exception handlers per exception class. Handlers
receive the exception and return a `Response`. They are the single place where
domain errors become HTTP responses.

## Why it exists

Without handlers you get one of two failure modes:

- try/except in every route (copy-paste drift, HTTP leaking into services), or
- unhandled exceptions → 500 + stack traces (information disclosure).

FastAPI's default is the second for anything unexpected, and its built-in
`HTTPException` mechanism for the first. TeamFlow goes one step further: business
code raises **domain exceptions** that have no HTTP dependency at all.

## TeamFlow implementation

### The exception hierarchy — `app/core/exceptions.py`

```python
class AppError(Exception):
    status_code: int = 500
    detail: str = "Internal server error"
    headers: dict[str, str] | None = None

    def __init__(self, detail: str | None = None) -> None:
        if detail:
            self.detail = detail
        super().__init__(self.detail)

class NotFoundError(AppError):         status_code = 404
class PermissionDeniedError(AppError): status_code = 403
class ConflictError(AppError):         status_code = 409
class UnauthorizedError(AppError):
    status_code = 401
    headers = {"WWW-Authenticate": "Bearer"}
class ValidationFailedError(AppError): status_code = 422
class RateLimitError(AppError):
    status_code = 429
    def __init__(self, detail=None, retry_after=None):
        super().__init__(detail)
        if retry_after is not None:
            self.headers = {"Retry-After": str(retry_after)}
class ServiceUnavailableError(AppError): status_code = 503
class ExternalServiceError(AppError):    status_code = 502
```

Design notes:

- **Services raise these; routers never see them.** `app/services/tasks.py`
  raises `ValidationFailedError("Cannot move task from 'todo' to 'done'")` —
  that message is the API's message, but the service has no idea HTTP exists.
- **`headers` on the exception** solves the "401 needs WWW-Authenticate" and
  "429 needs Retry-After" problems without special-casing in handlers.
- Any `AppError` subclass with a new status code becomes a new HTTP error with
  no handler changes.

### The handlers — same file

```python
def install_exception_handlers(app) -> None:
    from fastapi import Request
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse
    from sqlalchemy.exc import SQLAlchemyError

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code,
                            content={"detail": exc.detail},
                            headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request, exc):
        errors = [
            {"loc": ".".join(str(part) for part in err.get("loc", [])),
             "msg": err.get("msg", "invalid"),
             "type": err.get("type", "value_error")}
            for err in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": errors})

    @app.exception_handler(SQLAlchemyError)
    async def db_error_handler(request, exc):
        logger.exception("Database error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request, exc):
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})
```

What each handler buys you:

| Handler | Problem solved |
| --- | --- |
| `AppError` | domain→HTTP, one shape `{"detail": ...}` for all expected errors |
| `RequestValidationError` | stable 422 shape, no Pydantic internals leaked |
| `SQLAlchemyError` | DB failures logged with context, generic body returned |
| `Exception` | last-resort: log + generic 500 (when `DEBUG=false`; with debug the dev traceback page is kept for debugging) |

`logger.exception` includes the stack trace **in the logs**, never in the
response.

## The error taxonomy in practice

```
401 UnauthorizedError      missing/invalid/expired token, wrong refresh type
403 PermissionDeniedError  authenticated member, insufficient role rank
404 NotFoundError          resource missing OR caller not a member of its org
409 ConflictError          duplicate email/slug/label/invitation; idempotency in flight
422 ValidationFailedError  business-rule violations (illegal transition, bad assignee)
429 RateLimitError         sliding-window exceeded (with Retry-After)
```

The 404-vs-403 rule (from `auth/05-authorization.md`): **if revealing the
resource's existence would leak tenant data → 404; if the caller is already
authorized to know it exists but lacks rank → 403.**

## Where exceptions are raised (grep map)

| Exception | Examples |
| --- | --- |
| `UnauthorizedError` | `app/api/deps.py` (token), `app/services/auth.py` (login, refresh, reset) |
| `NotFoundError` | all `*Access` deps; services for missing rows; invitation email mismatch |
| `PermissionDeniedError` | service role checks (`tasks.py`, `organizations.py`, `attachments.py` route) |
| `ConflictError` | registration, org slug, label name, duplicate membership/invite |
| `ValidationFailedError` | transition whitelist, assignee membership, attachment validation |
| `RateLimitError` | `app/core/rate_limit.py` |

## Client-visible behavior (verified in tests)

- `tests/integration/test_tasks.py` asserts an illegal transition is a **422**,
  not a 500: `Cannot move task from 'todo' to 'done'`.
- `tests/integration/test_organizations_rbac.py` asserts non-members get 404 and
  members without rank get 403.
- `tests/integration/test_rate_limiting.py` asserts 429 + `Retry-After`.

## Django/DRF comparison 🔵

| DRF | FastAPI |
| --- | --- |
| `raise ValidationError` (400) | `raise ValidationFailedError` (422 by convention) |
| `raise PermissionDenied` (403) | `PermissionDeniedError` |
| `raise NotFound` / `get_object_or_404` | `NotFoundError` |
| `raise APIException` subclasses | `AppError` subclasses |
| `EXCEPTION_HANDLER` setting (single global) | `@app.exception_handler(Type)` (per type) |
| Django's `Http404`/`PermissionDenied` in views | not used — services stay framework-agnostic |

The key architectural difference: DRF's exceptions come from `rest_framework`
and are inherently HTTP; TeamFlow's come from `app.core.exceptions` and are
HTTP-agnostic until a handler maps them.

## Production perspective

- **Never leak internals**: the 500 handlers return a constant message. Stack
  traces go to logs with the request id (`fastapi/08-middleware.md`).
- **A raise costs nothing extra**: exceptions are exceptional, not control flow
  for expected paths — but note TeamFlow uses them *deliberately* for expected
  errors (a 404 for a non-member is expected). Python exceptions for expected
  outcomes are acceptable here because they cross exactly one boundary
  (service → handler) and produce a response. If they were used for loop
  control, that would be a smell.
- **Handler order**: FastAPI matches the most specific registered class walking
  the MRO; `AppError` catches all subclasses, `Exception` catches the rest.
- If you add Sentry/OpenTelemetry, hook it into the `Exception` and
  `SQLAlchemyError` handlers — that is your single instrumentation point.

## Common mistakes

1. **`raise HTTPException` inside services.** Now services import FastAPI and
   can't be unit-tested or used from Celery without dragging HTTP along.
2. **Raising `ValueError` for domain errors.** It falls into the generic 500
   handler — a user mistake becomes a server error.
3. **Returning 400 for validation in custom handlers** while FastAPI's built-in
   validation returns 422 — inconsistent API. Pick 422 (TeamFlow does).
4. **Including `str(exc)` in 500 responses.** Leaks internals (connection
   strings, SQL fragments).
5. **Forgetting `from None` on re-raised exceptions** (`raise UnauthorizedError(...) from None`)
   — otherwise the traceback chains and logs show "During handling of the above
   exception..." noise. TeamFlow uses `from None` where the original is
   uninteresting (invalid token), and `from exc` where the cause matters
   (attachment confirm).

## Cheat sheet

```python
class AppError(Exception):
    status_code = 500; detail = "..."; headers = None

@app.exception_handler(AppError)
async def h(request, exc): return JSONResponse(exc.status_code, {"detail": exc.detail}, headers=exc.headers)
```

## Review questions

1. Why does the service layer never import FastAPI?
2. A non-member requests `GET /tasks/{id}` for a task in another org. Which
   exception class fires, and why not `PermissionDeniedError`?
3. How does a 429 response get its `Retry-After` header without a dedicated
   handler?
4. What would you check in review if a new endpoint returns 400 instead of 422
   for a bad enum value?
