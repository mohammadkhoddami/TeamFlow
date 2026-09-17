# Production 05 — Health and Readiness

## Concept

Two probes with different jobs:

| Endpoint | Question | Cost |
| --- | --- | --- |
| `GET /health/live` | is the process alive? | zero I/O |
| `GET /health/ready` | can it serve traffic? (DB + Redis reachable) | one `SELECT 1` + one `PING` |

## Implementation — `app/api/routes/health.py`

```python
@router.get("/live", summary="Liveness probe")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}

@router.get("/ready")
async def readiness(redis_client: Annotated[Redis, Depends(get_redis_client)]) -> dict[str, str]:
    checks: dict[str, str] = {}
    healthy = True

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "error"
        healthy = False

    try:
        await redis_client.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "error"
        healthy = False

    if not healthy:
        return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        content='{"status": "unavailable"}',
                        media_type="application/json")

    return {"status": "ready", **checks}
```

Design points:

- **Liveness never checks dependencies.** If liveness checked the DB, a DB blip
  would make the orchestrator kill healthy API processes — an outage amplifier.
  Liveness answers only "is this process functioning".
- **Readiness checks both dependencies, cheaply.** `SELECT 1` through the pool
  (not a query over business tables) and `PING`. It is intentionally the only
  place the app reports dependency status.
- **503 with a tiny JSON body on failure** — orchestrators and load balancers
  only need the status code; the body serves humans.
- **The two endpoints are the same ones the Docker HEALTHCHECK and any LB
  target group should use** — image healthcheck hits `/live`
  (`Dockerfile`), LBs should hit `/ready`.
- **Health checks bypass rate limiting** (no auth/rate-limit dependencies) and
  the access log skips `/health*` to avoid noise
  (`app/core/middleware.py`).

## Who calls what (and why it matters)

| Caller | Probe | Consequence of failure |
| --- | --- | --- |
| Docker `HEALTHCHECK` (Dockerfile) | `/live` | container marked unhealthy (doesn't auto-restart by itself — orchestrator policy) |
| Compose `depends_on: service_healthy` (db/redis) | their own healthchecks | API starts only when deps are *actually* ready |
| Load balancer / k8s readinessProbe | `/ready` | traffic stops routing to a degraded process |
| k8s livenessProbe | `/live` | process restarted only if it is truly stuck |

Mixing these up is a classic production bug: readiness checks in liveness
probes cause restart storms during dependency outages; liveness checks in LB
targets keep sending traffic to a process whose DB pool is dead.

## What readiness does **not** verify (by design)

- **MinIO/S3**: presigning is local; a storage outage affects only attachment
  endpoints. Reporting 503 for the whole API would be too coarse.
- **Celery broker**: the API enqueues best-effort with a durable fallback
  (`infrastructure/09-webhooks.md`). A broker outage degrades background work,
  not API correctness.
- **Migrations applied**: an operational concern checked at deploy time
  (`production/08`).

Expanding readiness should follow the same question: "does a failure make *all
API traffic* incorrect?" If not, it doesn't belong here.

## Django/DRF comparison 🔵

| Django | TeamFlow |
| --- | --- |
| `django-health-check` package / custom view | two explicit endpoints |
| `manage.py check` at deploy | readiness at runtime |
| No standard probe conventions | liveness/readiness split is the k8s convention |
| Health view hitting the ORM | raw `SELECT 1` (no ORM, no models, no side effects) |

## Review questions

1. Why must liveness perform zero I/O?
2. What exact failure does `/ready` returning 503 cause in a load-balanced
   deployment, and what should it *not* cause?
3. Why is MinIO absent from readiness, and what would you add for an
   attachment-heavy SLA?
4. Which endpoint should the Docker HEALTHCHECK use, and which should an LB
   target group use? (Check `Dockerfile` and justify.)
