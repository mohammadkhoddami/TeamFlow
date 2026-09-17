# Production 02 — Configuration

## Concept

All configuration flows through one typed object: `Settings` in
`app/core/config.py`, built by pydantic-settings from environment variables
with `.env` support for local dev. Nothing else in the codebase reads
`os.environ`.

## Why one settings object

- **Typed**: `settings.db_pool_size` is an `int` — bad values fail at startup,
  not mid-request.
- **Discoverable**: one file lists everything configurable.
- **Testable**: tests set env before import; `lru_cache` guarantees one parse
  per process.
- **Secret-safe**: defaults exist for dev only; production injects real values
  (`production/01-docker.md`).

## Implementation — `app/core/config.py`

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8",
                                      extra="ignore")

    environment: str = "development"          # development | testing | production
    debug: bool = True
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"
    log_json: bool = False

    database_url: str = "postgresql+asyncpg://teamflow:teamflow@localhost:5432/teamflow"
    database_url_sync: str = ""
    db_pool_size: int = 10
    db_max_overflow: int = 10

    secret_key: str = "dev-secret-change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14

    cors_origins: list[str] = ["http://localhost:3000"]
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"

    rate_limit_enabled: bool = True
    auth_rate_limit_max: int = 5
    ...
    s3_endpoint: str = "localhost:9000"
    upload_max_bytes: int = 10 * 1024 * 1024
    upload_allowed_content_types: list[str] = [...]

    @property
    def sync_database_url(self) -> str:
        return self.database_url_sync or self.database_url.replace(
            "postgresql+asyncpg", "postgresql+psycopg")

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
```

Points worth teaching:

- **`extra="ignore"`** — unrelated env vars (CI, shell exports) don't crash
  startup.
- **List parsing**: `CORS_ORIGINS=["http://localhost:3000"]` is JSON in the env
  var — `pydantic-settings` parses it.
- **Derived values as properties** (`sync_database_url`) — one env var to keep
  in sync, with a fallback derivation.
- **`lru_cache`** — `.env` parsed once per process; tests set env vars *before*
  importing (`testing/01`).

## The three environments

| Variable | development | testing | production |
| --- | --- | --- | --- |
| `DEBUG` | true | false | false |
| `LOG_JSON` | false | false | true |
| Pool | 10+10 | `NullPool` | 10+10 (tune) |
| Rate limits | on | off by default | on |
| MinIO ensure at boot | yes | skipped | skipped (pre-provisioned) |

`ENVIRONMENT` gates behavior in exactly these places:
`app/core/db.py` (pool class), `app/main.py` (bucket bootstrap),
`app/core/logging.py` (formatter choice).

## Secrets policy

| Secret | Dev | Production |
| --- | --- | --- |
| `SECRET_KEY` | committed default | injected (`:?` guard / secret store) |
| DB credentials | compose defaults | required env vars |
| S3 keys | MinIO defaults | required env vars |
| SMTP creds | empty (console backend) | required for `EMAIL_BACKEND=smtp` |

⚠️ Honest gap: the app does **not** refuse to boot when
`SECRET_KEY` is the default in production. The check is one line in
`Settings` (`model_validator`) and is listed in
`production/07-security.md`.

## Django/DRF comparison 🔵

| Django | TeamFlow |
| --- | --- |
| `settings.py` module + `django-environ`/`python-decouple` | `BaseSettings` + env parsing built in |
| `DEBUG`, `ALLOWED_HOSTS`, `DATABASES` dicts | typed fields |
| `from django.conf import settings` | `from app.core.config import settings` |
| `override_settings` in tests | mutate the cached object / set env before import |
| 12-factor via add-ons | 12-factor by default |

pydantic-settings is the FastAPI ecosystem's standard replacement for
django-environ — same idea, typed and validated at startup.

## Production perspective

- **Fail fast on bad config**: `db_pool_size: int` means `"ten"` aborts boot
  with a clear error — far better than a runtime `TypeError`.
- **`.env` is for dev only.** Production uses real environment variables
  (compose `environment:`, Kubernetes secrets, systemd units). `.env` is
  git-ignored; `.env.example` is the template.
- **Changing settings requires a restart** — no hot reload of config. That is a
  feature: config changes are deploys.
- **Never log settings.** The object contains secrets; the access log and
  exception handlers print only sanitized context.

## Common mistakes

1. **`os.getenv` scattered through the code** — untyped, undiscoverable, and
   every call site is a new parsing bug.
2. **Reading `.env` in production** — deploy-time env vars should win; the file
   may not even exist in the image.
3. **Committed real secrets in `.env.example`.** The file ships placeholders
   and generation instructions only.
4. **Deriving values at import in multiple modules** — TeamFlow centralizes
   derivations as properties.
5. **Forgetting `lru_cache`** and re-parsing `.env` (and re-validating) on
   every access.

## Cheat sheet

```python
settings.environment, settings.debug, settings.api_v1_prefix
settings.database_url / settings.sync_database_url
settings.redis_url / settings.celery_broker_url
settings.rate_limit_enabled, settings.auth_rate_limit_max
settings.s3_endpoint / s3_bucket / s3_presign_expiry_seconds
settings.upload_max_bytes / upload_allowed_content_types
settings.webhook_timeout_seconds / webhook_max_retries / webhook_httpx_trust_env
```

## Review questions

1. Why is `lru_cache` on `get_settings` important for tests specifically?
2. Where would you add a startup check that forbids the default `SECRET_KEY`
   when `environment == "production"`?
3. Why does `sync_database_url` have a derivation fallback?
4. List the places `ENVIRONMENT` changes behavior, and why each choice is
   environment-specific.
