"""Application configuration via pydantic-settings.

All configuration flows through this single typed object. It reads from
environment variables (12-factor style) with `.env` file support for local dev.
Secrets are never hardcoded; `SECRET_KEY` must be set in production.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Core ---
    app_name: str = "TeamFlow API"
    environment: str = "development"  # development | testing | production
    debug: bool = True
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"
    log_json: bool = False  # JSON logs for production log shippers

    # --- Database ---
    database_url: str = "postgresql+asyncpg://teamflow:teamflow@localhost:5432/teamflow"
    # Sync URL used by Celery workers (asyncpg has no meaning in sync tasks).
    database_url_sync: str = ""
    db_pool_size: int = 10
    db_max_overflow: int = 10

    # --- Security / JWT ---
    secret_key: str = "dev-secret-change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14

    # --- CORS ---
    cors_origins: list[str] = ["http://localhost:3000"]

    # --- Redis (rate limiting, token store, WS pub/sub, dashboard cache) ---
    redis_url: str = "redis://localhost:6379/0"

    # --- Celery ---
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/1"

    # --- Rate limiting (sliding window, seconds window / max hits) ---
    rate_limit_enabled: bool = True
    auth_rate_limit_max: int = 5
    auth_rate_limit_window: int = 60
    register_rate_limit_max: int = 3
    register_rate_limit_window: int = 3600
    password_reset_rate_limit_max: int = 3
    password_reset_rate_limit_window: int = 3600

    # --- File uploads / S3 (MinIO in development) ---
    s3_endpoint: str = "localhost:9000"
    s3_access_key: str = "teamflow"
    s3_secret_key: str = "teamflow-secret"
    s3_bucket: str = "teamflow-attachments"
    s3_secure: bool = True
    s3_presign_expiry_seconds: int = 900
    upload_max_bytes: int = 10 * 1024 * 1024  # 10 MB
    upload_allowed_content_types: list[str] = [
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "text/plain",
        "text/csv",
        "text/markdown",
        "application/pdf",
        "application/json",
        "application/zip",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ]

    # --- Email (console = log the email in dev, smtp = real delivery) ---
    email_backend: str = "console"  # console | smtp
    email_from: str = "teamflow@localhost"
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = False
    frontend_base_url: str = "http://localhost:3000"

    # --- Idempotency ---
    idempotency_ttl_hours: int = 24

    # --- Webhooks ---
    webhook_timeout_seconds: float = 5.0
    webhook_max_retries: int = 5
    # honor HTTP(S)_PROXY env vars for webhook delivery; set false on hosts
    # with a system proxy that cannot reach internal/receiver URLs.
    webhook_httpx_trust_env: bool = True

    # --- HTTP client ---
    http_timeout_seconds: float = 10.0

    @property
    def sync_database_url(self) -> str:
        return self.database_url_sync or self.database_url.replace(
            "postgresql+asyncpg", "postgresql+psycopg"
        )

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    """Cached so the .env file is only parsed once per process."""
    return Settings()


settings = get_settings()
