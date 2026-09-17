# Infrastructure 05 — Celery Beat (Scheduled Work)

## Concept

Celery Beat is a separate process that enqueues tasks on a schedule. It is the
cron of the Celery world, with one critical difference: the schedule is code
(`beat_schedule`), not a crontab, and the beat process must be a singleton.

## Why a separate process

Putting periodic work inside the API process (an `asyncio` loop in lifespan, or
a thread) fails on three counts:

1. **Multiplicity** — every API worker would run its own timer; N workers = N
   executions per period.
2. **Lifecycle** — deploys restart processes at arbitrary times; a `sleep(3600)`
   loop resets and may never fire.
3. **Observability** — no execution history, no retry semantics, no queue.

Beat solves all three: one process, durable schedule, tasks land in the same
broker/worker pipeline as everything else (with the same retry/visibility
story).

## TeamFlow's schedule — `app/workers/celery_app.py`

```python
beat_schedule={
    "cleanup-expired-data-daily": {
        "task": "teamflow.cleanup_expired_data",
        "schedule": 6 * 3600,
    },
    "warm-dashboard-caches-hourly": {
        "task": "teamflow.warm_dashboard_caches",
        "schedule": 3600,
    },
    "notify-due-tasks-daily": {
        "task": "teamflow.notify_due_tasks",
        "schedule": 24 * 3600,
    },
},
```

| Job | Cadence | What it does |
| --- | --- | --- |
| `cleanup_expired_data` | every 6h | purge idempotency keys (TTL), stale pending attachments (+ S3 objects), re-enqueue stranded webhook deliveries |
| `warm_dashboard_caches` | hourly | precompute stats for every active org into Redis |
| `notify_due_tasks` | daily | notify watchers of tasks due within 24h |

## Job anatomy (they are ordinary tasks)

```python
@shared_task(name="teamflow.notify_due_tasks")
def notify_due_tasks() -> dict:
    from app.models import Notification, Task, TaskStatus

    cutoff = datetime.now(UTC) + timedelta(hours=24)
    notified = 0
    with session_scope() as db:
        tasks = list(db.execute(
            select(Task).where(Task.due_date.is_not(None),
                               Task.due_date <= cutoff,
                               Task.status != TaskStatus.DONE)
        ).scalars())
        for task in tasks:
            for watcher in task.watchers:
                db.add(Notification(user_id=watcher.id, ...
                                    type="task_due_soon", ...))
                notified += 1
    return {"notified": notified}
```

Notes for review:

- Uses the same sync `session_scope` as every task.
- Returns a summary dict — Celery's result backend keeps it for an hour
  (`result_expires=3600`), so `celery result` shows what happened.
- **Idempotency**: the due-task job creates notifications by reading state; if
  it ran twice it would create duplicates. Beat runs it on a fixed cadence, and
  a missed run self-heals next day — acceptable for reminders. (A production
  refinement: a `(user, task, window)` dedupe key. Documented as a trade-off.)

## The cache-warming job

```python
@shared_task(name="teamflow.warm_dashboard_caches")
def warm_dashboard_caches() -> dict:
    cache_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    ...
    for org_id in org_ids:
        stats = _compute_stats_sync(db, org_id)
        cache_client.set(dashboard_service.dashboard_key(org_id), json.dumps(stats, default=str),
                         ex=dashboard_service.DASHBOARD_TTL_SECONDS)
```

`_compute_stats_sync` is a **sync twin** of `dashboard.compute_stats`
(`app/services/dashboard.py`) — the same five aggregates, executed with a sync
session. This duplication is deliberate and documented in the module
docstring ("kept small; factor out if it grows"). The alternative (running the
async service from a sync worker via `asyncio.run`) would create an event loop
per task for no benefit.

Honest assessment: two implementations of the same aggregates *can* drift. The
dashboard service is the source of truth; if you add a metric, add it to both
and keep them adjacent in review. Listed in `mastery/10-what-i-actually-master.md`
as a known cost.

## Why these cadences

| Cadence | Reasoning |
| --- | --- |
| 6h cleanup | TTLs are 24h; 4 passes/day bounds table size while keeping query load trivial |
| 1h cache warm | TTL is 60s, but warming hourly keeps *most* reads warm after deploys; the TTL still self-heals |
| 24h reminders | "due within 24h" would spam if run more often without dedupe |

## Operations

- **Exactly one beat process.** Two beat processes double-schedule everything.
  Compose runs `celery ... beat -l info` as its own service
  (`docker-compose.yml`, prod variant identical).
- **Beat writes its schedule state** (`celerybeat-schedule` file) if configured;
  TeamFlow uses a pure in-code schedule, so no state file is needed.
- **Timezone**: `timezone="UTC", enable_utc=True` — schedules are interval-based
  here, so no cron tz semantics to reason about.

## Django/DRF comparison 🔵

| Django | TeamFlow |
| --- | --- |
| `crontab()` management command | `celery ... beat` process |
| `celery.py` beat_schedule | same concept, in `celery_app.py` |
| `CELERY_BEAT_SCHEDULE` setting | `beat_schedule=` dict |
| Management command crons | Celery tasks (same retry/monitoring pipeline) |

Identical concept; the point of the lesson is the *reason* beat exists
(singleton, durable, observable) and the discipline around it (tasks must be
idempotent/re-runnable).

## Common mistakes

1. **Running beat per worker** (`-B` flag in production) — duplicate schedules,
   classic double-email bug.
2. **Long-running jobs in beat's own process** — beat only enqueues; the work
   must be a task.
3. **Scheduling without idempotency** — a restart mid-job or manual re-run can
   duplicate side effects.
4. **Using server-local time** — `enable_utc=True` keeps schedules sane across
   regions.
5. **Forgetting that a Redis outage pauses beat** — broker unavailability
   retries on startup (`broker_connection_retry_on_startup=True`) but the
   missed window is lost; jobs are designed to self-heal on next run.

## Cheat sheet

```python
beat_schedule = {
    "job-name": {"task": "teamflow.task_name", "schedule": seconds},
}
# run: celery -A app.workers.celery_app:celery_app beat -l info   (ONE process)
```

## Review questions

1. Why can't cache warming live in the API's lifespan as an `asyncio` loop?
2. What are the three purges in `cleanup_expired_data`, and which one is a
   compensating action for a failure elsewhere?
3. Why is `_compute_stats_sync` duplicated from `dashboard.compute_stats`, and
   what is the maintenance risk?
4. Which of the three scheduled jobs is *not* idempotent, and what bounds the
   damage?
