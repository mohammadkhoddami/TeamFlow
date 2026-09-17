"""Pure-ASGI middleware: request ID propagation + structured access log.

Pure ASGI (not BaseHTTPMiddleware) avoids its known problems with streaming,
background tasks, and WebSocket scopes. Assigns/propagates X-Request-ID,
binds it into the logging contextvars, and logs one line per request with
duration and status. Bodies are never logged; Authorization is never read.
"""

import time
import uuid

from starlette.datastructures import Headers, MutableHeaders

from app.core.logging import request_id_ctx


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

        import logging

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            path = scope.get("path", "-")
            if not path.startswith("/health"):  # health probes spam the log
                logging.getLogger("app.access").info(
                    '%s %s -> %s (%.1fms)',
                    scope.get("method", "-"),
                    path,
                    status_holder["status"],
                    duration_ms,
                    extra={"status_code": status_holder["status"], "duration_ms": duration_ms},
                )
            request_id_ctx.reset(token)
