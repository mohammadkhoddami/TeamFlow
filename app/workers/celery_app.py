"""Celery application.

API routes never import task bodies: they enqueue by name via
`celery_app.send_task("teamflow.<name>", ...)` (see app.services.events), so
the web process does not need worker-only imports.

Shared HTTP client: created once per worker process (worker_process_init),
not per task — connection pooling and keep-alive without per-request cost.
"""

import httpx
from celery import Celery
from celery.signals import worker_process_init, worker_process_shutdown

from app.core.config import settings

celery_app = Celery(
    "teamflow",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_default_queue="default",
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Webhook/email deliveries must survive worker restarts (visibility
    # timeout vs. task acks_late).
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    task_track_started=True,
    result_expires=3600,
    # Beat schedule: exactly one entry per recurring job.
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
)

# Queues: default (misc), emails, webhooks — workers can scale independently.
from kombu import Queue  # noqa: E402

celery_app.conf.task_queues = (
    Queue("default"),
    Queue("emails"),
    Queue("webhooks"),
)
celery_app.conf.task_routes = {
    "teamflow.send_email": {"queue": "emails"},
    "teamflow.deliver_webhook": {"queue": "webhooks"},
}

# Long-lived HTTP client for webhook delivery, one per worker process.
http_client: httpx.Client | None = None


@worker_process_init.connect
def init_worker(**kwargs: object) -> None:
    global http_client
    http_client = httpx.Client(
        timeout=settings.webhook_timeout_seconds,
        trust_env=settings.webhook_httpx_trust_env,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )


@worker_process_shutdown.connect
def shutdown_worker(**kwargs: object) -> None:
    global http_client
    if http_client is not None:
        http_client.close()
        http_client = None


# Task registration: Celery discovers these at import time.
from app.workers import tasks as worker_tasks  # noqa: E402,F401
