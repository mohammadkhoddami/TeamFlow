"""FastAPI application factory and entrypoint.

Lifespan owns long-lived resources: the DB engine, the Redis client, the
object-storage bucket bootstrap, and the WebSocket Redis pub/sub listener
(one per worker process — that is what makes WS multi-worker safe).
Middleware order (outermost first): RequestContext (request ID + access log),
Idempotency, CORS.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.admin import setup_admin
from app.api.router import api_router
from app.core.config import settings
from app.core.db import engine
from app.core.exceptions import install_exception_handlers
from app.core.idempotency import IdempotencyMiddleware
from app.core.logging import setup_logging
from app.core.middleware import RequestContextMiddleware
from app.core.redis import close_redis_client
from app.services.integrations.storage import StorageClient
from app.websocket.router import router as ws_router
from app.websocket.router import run_redis_listener

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    stop = asyncio.Event()
    listener = asyncio.create_task(run_redis_listener(stop), name="ws-redis-listener")

    # The API provisions the bucket at startup (compose health-gates MinIO;
    # the retries also cover bare runs and races). Production may instead use
    # pre-provisioned buckets via IaC.
    if settings.environment != "testing":
        await StorageClient.from_settings().ensure_bucket(attempts=5, delay_seconds=1.0)

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
        description=(
            "TeamFlow API - multi-tenant project management and collaboration.\n\n"
            "**Auth:** OAuth2 password flow via `/api/v1/auth/login` (form-encoded), "
            "plus passwordless email OTP (`/auth/otp/*`) and Google OAuth "
            "(`/auth/google/start`). Registration (`/auth/register`) requires a "
            "code emailed by `/auth/otp/request`. Use the access token in "
            "`Authorization: Bearer <token>`."
        ),
        debug=settings.debug,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    install_exception_handlers(app)

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

    app.include_router(api_router, prefix=settings.api_v1_prefix)
    app.include_router(ws_router)  # /ws/projects/{project_id}

    # Server-rendered admin panel at settings.admin_base_url (superuser-only).
    setup_admin(app)

    return app


app = create_app()
