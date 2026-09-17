"""Structured logging with request context.

Uses stdlib logging + contextvars (no extra dependency). Every request gets a
request id; a logging filter stamps `request_id`/`user_id`/`org_id` into every
record so log shippers can correlate lines. JSON format is available for
production pipelines.

Sensitive data (passwords, tokens) is never passed to loggers; the access log
redacts the Authorization header and omits bodies entirely.
"""

import json
import logging
import sys
from contextvars import ContextVar
from typing import Any

from app.core.config import settings

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")
user_id_ctx: ContextVar[str] = ContextVar("user_id", default="-")
org_id_ctx: ContextVar[str] = ContextVar("org_id", default="-")


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        record.user_id = user_id_ctx.get()
        record.org_id = org_id_ctx.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            "user_id": getattr(record, "user_id", "-"),
            "org_id": getattr(record, "org_id", "-"),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging() -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(ContextFilter())
    if settings.log_json or settings.is_production:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "[%(levelname).1s %(asctime)s %(request_id)s] %(name)s: %(message)s"
            )
        )
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())

    # Uvicorn noise: route their logs through the same handlers/level.
    for noisy in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        logger = logging.getLogger(noisy)
        logger.handlers.clear()
        logger.propagate = True
