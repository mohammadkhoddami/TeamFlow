"""HTTP transport helpers for the shared (remote) MCP deployment.

The stdio server owns one identity: credentials come from the environment or
the workspace `.env`. A remote server cannot work that way, because one process
serves every caller. Instead each request carries the caller's TeamFlow personal
access token as an ``Authorization: Bearer tf_...`` header; the middleware below
binds it to a context variable and the API client forwards it for that request
only.

When the deployment is configured with its own credentials (``TEAMFLOW_TOKEN``
or ``TEAMFLOW_EMAIL`` + ``TEAMFLOW_PASSWORD``), requests without a bearer header
fall back to those, which keeps single-identity/internal deployments simple.
"""

from __future__ import annotations

import contextvars

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

_request_token: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "teamflow_request_token", default=None
)


def current_request_token() -> str | None:
    """The caller's TeamFlow token for the request being handled, if any."""
    return _request_token.get()


class BearerTokenMiddleware:
    """Require (and propagate) a TeamFlow personal access token per request."""

    def __init__(self, app: ASGIApp, *, allow_without_token: bool = False) -> None:
        self.app = app
        self.allow_without_token = allow_without_token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") == "/health":
            await self.app(scope, receive, send)
            return

        header = Headers(scope=scope).get("authorization", "")
        scheme, _, value = header.partition(" ")
        token = value.strip() if scheme.lower() == "bearer" else ""

        if not token:
            if self.allow_without_token:
                await self.app(scope, receive, send)
                return
            response = JSONResponse(
                {
                    "detail": (
                        "Authentication required: send a TeamFlow personal access "
                        "token as 'Authorization: Bearer tf_...'."
                    )
                },
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        reset = _request_token.set(token)
        try:
            await self.app(scope, receive, send)
        finally:
            _request_token.reset(reset)
