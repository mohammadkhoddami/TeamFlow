# FastAPI 01 — The Application Object

## Concept

A FastAPI app is an ASGI application object. You create it once, configure it
(title, docs, lifespan, exception handlers), attach routers and middleware, and
hand it to an ASGI server (uvicorn/gunicorn).

## Why it exists

In Django, `settings.py` + `urls.py` + `wsgi.py` are separate conventions the
framework dictates. FastAPI has no project conventions — the app object *is*
the configuration surface. That freedom is why TeamFlow uses an **app factory**
(`create_app()`): the object is constructed by explicit code you can read top to
bottom.

## TeamFlow implementation

`app/main.py`:

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    stop = asyncio.Event()
    listener = asyncio.create_task(run_redis_listener(stop), name="ws-redis-listener")

    if settings.environment != "testing":
        await StorageClient.from_settings().ensure_bucket()

    yield

    stop.set()
    listener.cancel()
    try:
        await listener
    except asyncio.CancelledError:
        pass
    await close_redis_client()
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description="TeamFlow API - multi-tenant project management ...",
        debug=settings.debug,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    install_exception_handlers(app)

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(CORSMiddleware, ...)

    app.include_router(api_router, prefix=settings.api_v1_prefix)
    app.include_router(ws_router)  # /ws/projects/{project_id}

    return app


app = create_app()
```

### Walkthrough

- **`lifespan`** runs once per process: start the Redis pub/sub listener,
  ensure the S3 bucket exists (dev convenience), and on shutdown cancel the
  listener, close the Redis client, and dispose the DB engine. Details in
  `10-lifespan.md`.
- **`install_exception_handlers(app)`** registers the AppError → JSON handlers
  (`09-exception-handling.md`).
- **Middleware order**: Starlette wraps middleware in reverse registration
  order; the *last added* runs *first* for requests. So CORS is outermost,
  then idempotency, then request context. Rationale in `08-middleware.md`.
- **`include_router(api_router, prefix="/api/v1")`** — one prefix, applied once.
  WebSocket routes are included **without** the prefix because the channel URL
  is `/ws/projects/{id}`, not versioned API.
- **`app = create_app()`** at module scope so `uvicorn app.main:app` and
  gunicorn's import string work.

## Why an app factory instead of a module-level app only?

`create_app()` lets tests construct isolated apps with overridden settings, keeps
import order explicit, and avoids circular imports between routers and settings.
TeamFlow keeps `app = create_app()` as the deployment entrypoint.

## Django/DRF comparison 🔵

| Django | FastAPI |
| --- | --- |
| `myproject/wsgi.py` (implicit app) | `app = create_app()` (explicit) |
| `INSTALLED_APPS` registry | `include_router()` calls |
| `MIDDLEWARE` list in settings | `add_middleware()` in code (order = reverse add) |
| `ROOT_URLCONF` | routers with `prefix=` |
| `AppConfig.ready()` | `lifespan` startup |
| settings module (global mutable) | `lru_cache`d `Settings` object |

Django's `AppConfig.ready()` is a close analogue of lifespan startup — but
Django runs it per management command too; FastAPI's lifespan runs only when the
server actually serves traffic (and not at all under `ASGITransport` in tests,
which is exactly what TeamFlow's HTTP tests rely on).

## Production perspective

- One app object per **process**. `--workers 2` (see `Dockerfile`) means two
  processes, each with its own lifespan, engine, Redis client, and WS listener.
  Any shared state must live in Postgres/Redis — never in module globals.
- `debug=settings.debug` gates traceback responses. In production
  (`DEBUG=false`) even unhandled errors render generic JSON.
- `/docs` and `/redoc` are enabled everywhere here; production APIs often
  disable them or protect them behind auth (`production/07-security.md`).

## Common mistakes

1. **Putting startup work in module scope** (`engine.connect()` at import time).
   It runs for every process that imports the module — including Alembic and
   tests — and cannot be cleaned up. Use lifespan.
2. **Assuming middleware order = add order.** It's reversed (last added runs
   first).
3. **Forgot `app = create_app()`** and pointing the server at `create_app` — the
   server calls it, but then `--reload`/`--workers` semantics and `settings`
   timing get confusing.
4. Django devs often look for a `settings.py`-style global. TeamFlow's
   `app/core/config.py` *is* that global, but it's a typed, cached object with
   env-var parsing (`production/02-configuration.md`).

## Cheat sheet

```python
app = FastAPI(title=..., version=..., lifespan=lifespan, debug=...)
app.include_router(router, prefix="/api/v1", tags=[...])
app.add_middleware(MiddlewareCls, **kwargs)   # last added = outermost
app.exception_handler(ExcType)                # or app.add_exception_handler
app.state.<name> = ...                        # per-process state for lifespan resources
```

## Review questions

1. Why does the WS router *not* get the `/api/v1` prefix?
2. If you start uvicorn with two workers, how many Redis listeners exist? Does
   that break WS fan-out? (Check `06-websocket-scaling` in `infrastructure/`.)
3. Why is `app = create_app()` needed at module level for gunicorn's import
   string `app.main:app`?
