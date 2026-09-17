"""Domain-specific exceptions and global exception handlers.

Services raise these; `install_exception_handlers` turns them into consistent
JSON responses so routers stay thin and business logic never touches HTTP.
Every handler sanitizes output: clients never see stack traces or internals.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base class for all expected application errors."""

    status_code: int = 500
    detail: str = "Internal server error"
    headers: dict[str, str] | None = None

    def __init__(self, detail: str | None = None) -> None:
        if detail:
            self.detail = detail
        super().__init__(self.detail)


class NotFoundError(AppError):
    status_code = 404
    detail = "Resource not found"


class PermissionDeniedError(AppError):
    status_code = 403
    detail = "Not enough permissions"


class ConflictError(AppError):
    status_code = 409
    detail = "Resource conflict"


class UnauthorizedError(AppError):
    status_code = 401
    detail = "Not authenticated"
    headers = {"WWW-Authenticate": "Bearer"}


class ValidationFailedError(AppError):
    status_code = 422
    detail = "Validation failed"


class RateLimitError(AppError):
    status_code = 429
    detail = "Too many requests"

    def __init__(self, detail: str | None = None, retry_after: int | None = None) -> None:
        super().__init__(detail)
        if retry_after is not None:
            self.headers = {"Retry-After": str(retry_after)}


class ServiceUnavailableError(AppError):
    status_code = 503
    detail = "Service temporarily unavailable"


class ExternalServiceError(AppError):
    status_code = 502
    detail = "Upstream service error"


def install_exception_handlers(app: Any) -> None:
    """Register handlers that turn expected/unexpected errors into JSON."""
    from fastapi import Request
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse
    from sqlalchemy.exc import SQLAlchemyError

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Same shape FastAPI uses by default, minus noisy internals.
        errors = [
            {
                "loc": ".".join(str(part) for part in err.get("loc", [])),
                "msg": err.get("msg", "invalid"),
                "type": err.get("type", "value_error"),
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={"detail": errors},
        )

    @app.exception_handler(SQLAlchemyError)
    async def db_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.exception("Database error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )
