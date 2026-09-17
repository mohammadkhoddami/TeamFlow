# Production 01 — Docker

## Concept

Two compose worlds: **development** (bind-mounted source, reload, all services)
and **production** (built image, gunicorn+uvicorn workers, nginx). One
multi-stage `Dockerfile` serves both.

## The Dockerfile — `Dockerfile`

```dockerfile
FROM python:3.12-slim AS builder
ENV UV_PYTHON=/usr/local/bin/python3.12 UV_LINK_MODE=copy
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project     # deps layer cached separately

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH="/app/.venv/bin:$PATH"
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --shell /usr/sbin/nologin appuser   # non-root
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY pyproject.toml uv.lock ./
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
USER appuser
EXPOSE 8000
CMD ["gunicorn", "app.main:app",
     "--worker-class", "uvicorn.workers.UvicornWorker",
     "--workers", "2", "--bind", "0.0.0.0:8000",
     "--timeout", "60", "--graceful-timeout", "30",
     "--access-logfile", "-", "--error-logfile", "-"]
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD curl -fsS http://localhost:8000/api/v1/health/live || exit 1
```

Why each choice:

| Choice | Reason |
| --- | --- |
| Multi-stage | runtime image carries no uv, no build context — smaller and safer |
| `uv sync --frozen` first | dependency layer caches; app code changes don't reinstall |
| `--no-dev` | test deps stay out of production images |
| Non-root `appuser` | container-escape blast radius; required by many platforms |
| `curl` for healthcheck | tiny, explicit; the `--start-period` covers migrations at boot |
| gunicorn + UvicornWorker | process manager (restarts, graceful drain) + ASGI |
| `--timeout 60` | request ceiling; covers slow DB moments without hanging forever |
| `--graceful-timeout 30` | in-flight requests finish on deploy/stop |
| `PYTHONUNBUFFERED` | logs flow immediately to the container runtime |

## Development compose — `docker-compose.yml`

Services: `db`, `redis`, `minio`, `minio-setup` (bucket bootstrap), `api`,
`worker`, `beat`. Highlights:

```yaml
api:
  build: { context: ., dockerfile: Dockerfile }
  volumes: ["./:/app"]                          # live source
  command: sh -c "uv sync --frozen && uv run alembic upgrade head &&
                  uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
  depends_on:
    db: { condition: service_healthy }
    redis: { condition: service_healthy }
    minio-setup: { condition: service_completed_successfully }
```

- **Health-gated dependencies** — the API starts only when Postgres/Redis are
  actually ready (not just started).
- **Migrations run at API startup** in dev (convenience); production runs them
  as an explicit step (below).
- **minio-setup** is a one-shot `mc` container that creates the bucket —
  `service_completed_successfully` makes the ordering a guarantee.
- **Only infra services expose ports** (`5432`, `6379`, `9000/9001`) — needed
  for local dev tools and tests.
- `restart: unless-stopped` on long-running services; one-shot jobs don't.

Compose gotchas found in this project:

- `minio/minio` images are no longer on Docker Hub; the compose references
  `quay.io/minio/minio` and `quay.io/minio/mc`.
- `minio-setup` uses `mc mb --ignore-existing local/teamflow-attachments` (the
  earlier `mc mb local teamflow-attachments` form failed — bucket name must be
  a single path argument).

## Production compose — `docker-compose.prod.yml`

```yaml
api:
  build: { context: ., dockerfile: Dockerfile }
  env_file: .env
  environment:
    ENVIRONMENT: production
    DEBUG: "false"
    LOG_JSON: "true"
    DATABASE_URL: postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}
    ...
  depends_on: { db: { condition: service_healthy }, redis: { condition: service_healthy } }
  restart: unless-stopped
  stop_grace_period: 40s

worker:
  command: ["celery", "-A", "app.workers.celery_app:celery_app", "worker",
            "-l", "info", "-Q", "default,emails,webhooks", "--concurrency", "4"]
beat:
  command: ["celery", "-A", "app.workers.celery_app:celery_app", "beat", "-l", "info"]
nginx:
  image: nginx:1.27-alpine
  ports: ["80:80"]
  volumes: ["./deploy/nginx.conf:/etc/nginx/conf.d/default.conf:ro"]
```

Differences from dev, and why:

| Aspect | Dev | Prod |
| --- | --- | --- |
| Source | bind mount + `--reload` | baked into the image |
| Server | uvicorn CLI | gunicorn + 2 UvicornWorkers (image CMD) |
| Migrations | automatic at API start | explicit deploy step (`alembic upgrade head`) |
| Secrets | `.env` everywhere | required env vars (`:?` guards) — no defaults |
| Logs | human format | `LOG_JSON=true` |
| Ports | every service | only nginx (80) |
| Stop handling | default | `stop_grace_period: 40s` for in-flight requests |
| Restart | `unless-stopped` | same (except one-shots) |

**The `:?` guards are deliberate**: `POSTGRES_PASSWORD:?set POSTGRES_PASSWORD`
makes compose refuse to start without secrets — a misconfiguration fails at boot,
not at 3 a.m.

## Django/DRF comparison 🔵

| Django | TeamFlow |
| --- | --- |
| `gunicorn myproject.wsgi` | `gunicorn app.main:app -k uvicorn.workers.UvicornWorker` |
| `manage.py migrate` at deploy | `alembic upgrade head` at deploy |
| Django dev server | uvicorn `--reload` |
| `python:3.12-slim` + pip | multi-stage uv image |
| Celery worker/beat services | identical concept |

## Production perspective

- **Image size**: slim base + wheel-installed deps; the builder stage's uv and
  caches don't ship.
- **Graceful deploys**: `stop_grace_period` + gunicorn `--graceful-timeout`
  drain in-flight requests; the lifespan shutdown closes the Redis listener and
  DB engine.
- **Worker concurrency vs DB pools**: 4 Celery processes × sync pool (5+5) = 40
  possible connections; add API (2 × 20) → ~80. Budget Postgres
  `max_connections` accordingly (`production/04-asgi-workers.md`).
- **Zero-downtime migrations**: add-nullable → backfill → add-constraint, in
  separate deploys (patterns in `production/08-deployment.md`).

## Common mistakes

1. **Running as root** because "it's a container" — non-root costs one line.
2. **`COPY . .`** — the build context leaks `.env`, `.git`, tests; explicit
   COPYs only.
3. **Dev `--reload` in production** — memory leaks and no graceful restarts.
4. **Putting secrets in the image** — env vars/secret stores only; the compose
   `:?` guards enforce presence.
5. **One worker with concurrency defaults and no pool math** — connections
   multiply per process; do the arithmetic.

## Review questions

1. Why is the dependency `COPY` + `uv sync` a separate layer from the source
   `COPY`?
2. Why does dev compose run migrations in the API command while prod doesn't?
3. What do the `:?` guards protect against, and what's the failure mode without
   them?
4. Compute the maximum Postgres connections for the prod compose as written,
   and say what you'd tune first if it exceeds `max_connections`.
