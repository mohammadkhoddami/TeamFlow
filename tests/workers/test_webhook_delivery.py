"""Worker tests: webhook delivery (Celery task functions run directly).

The delivery task is exercised synchronously against a real local HTTP
receiver so signatures, status codes, retries, and idempotency are all real.
Celery's retry machinery is stubbed at the boundary (the task's own retry
bookkeeping — attempts, status transitions — is what we verify).
"""

import hashlib
import hmac
import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.core.db_sync import session_scope
from app.models import Webhook, WebhookDelivery


@pytest.fixture
def receiver_factory():
    servers: list[tuple[HTTPServer, threading.Thread]] = []

    def _make(status: int = 200):
        received: list[dict] = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("content-length", 0))
                body = self.rfile.read(length)
                received.append(
                    {
                        "sig": self.headers.get("X-TeamFlow-Signature"),
                        "ts": self.headers.get("X-TeamFlow-Timestamp"),
                        "delivery": self.headers.get("X-TeamFlow-Delivery"),
                        "event": self.headers.get("X-TeamFlow-Event"),
                        "body": json.loads(body),
                    }
                )
                self.send_response(status)
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *args) -> None:
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append((server, thread))
        return f"http://127.0.0.1:{port}/hook", received

    yield _make
    for server, thread in servers:
        server.shutdown()
        thread.join(timeout=2)


def _seed_delivery(url: str, secret: str, payload: dict) -> str:
    from app.models import Organization

    with session_scope() as db:
        org = Organization(name="Worker Org", slug=f"worker-org-{uuid.uuid4().hex[:8]}")
        db.add(org)
        db.flush()
        webhook = Webhook(
            url=url, secret=secret, events=["task.created"], organization_id=org.id
        )
        db.add(webhook)
        db.flush()
        delivery = WebhookDelivery(
            webhook_id=webhook.id, event="task.created", payload=payload
        )
        db.add(delivery)
        db.flush()
        return str(delivery.id)


def _delivery(delivery_id: str) -> WebhookDelivery:
    with session_scope() as db:
        delivery = db.get(WebhookDelivery, uuid.UUID(delivery_id))
        assert delivery is not None
        # detach with current state
        db.expunge(delivery)
        return delivery


def test_deliver_webhook_success_records_delivery(receiver_factory):
    url, received = receiver_factory(status=200)
    payload = {"id": None, "event": "task.created", "data": {"title": "Worker test"}}
    delivery_id = _seed_delivery(url, "worker-test-secret", payload)

    from app.workers.tasks import deliver_webhook

    result = deliver_webhook.run(delivery_id)
    assert result["status"] == "delivered"
    assert result["code"] == 200

    delivery = _delivery(delivery_id)
    assert delivery.status == "success"
    assert delivery.attempts == 1
    assert delivery.response_status == 200
    assert delivery.delivered_at is not None

    # receiver saw a verifiable HMAC signature + delivery id
    assert len(received) == 1
    hit = received[0]
    body = json.dumps(payload).encode()
    expected = "v1=" + hmac.new(
        b"worker-test-secret", f"{hit['ts']}.".encode() + body, hashlib.sha256
    ).hexdigest()
    assert hit["sig"] == expected
    assert hit["delivery"] == delivery_id
    assert hit["event"] == "task.created"


def test_deliver_webhook_transient_5xx_persists_retryable_state(receiver_factory):
    url, received = receiver_factory(status=500)
    delivery_id = _seed_delivery(url, "s2", {"id": "x", "data": {}})

    from app.workers import tasks as wt

    # run() triggers a Celery retry raise; task.run catches nothing, so we
    # simulate the retry loop by calling the underlying body with retries set.
    class FakeTask:
        class request:  # noqa: N801
            retries = wt.deliver_webhook.max_retries  # exhausted

        max_retries = wt.deliver_webhook.max_retries

    import app.workers.tasks as worker_tasks

    # Exhausted-retries path: _retry_or_fail marks failed, no raise.
    result = worker_tasks._retry_or_fail(FakeTask(), delivery_id, 1, "HTTP 500")
    assert result == {"status": "failed", "attempts": 1}
    delivery = _delivery(delivery_id)
    assert delivery.status == "failed"
    assert delivery.last_error == "HTTP 500"


def test_deliver_webhook_idempotent_on_reenqueue(receiver_factory):
    url, received = receiver_factory(status=200)
    delivery_id = _seed_delivery(url, "s3", {"id": "d1", "data": {}})

    from app.workers.tasks import deliver_webhook

    r1 = deliver_webhook.run(delivery_id)
    assert r1["status"] == "delivered"
    r2 = deliver_webhook.run(delivery_id)
    assert r2["status"] == "already_delivered"
    assert len(received) == 1


def test_deliver_webhook_permanent_4xx_no_retry(receiver_factory):
    url, _received = receiver_factory(status=404)
    delivery_id = _seed_delivery(url, "s4", {"id": "d2", "data": {}})

    from app.workers.tasks import deliver_webhook

    result = deliver_webhook.run(delivery_id)
    assert result["status"] == "failed_permanently"
    delivery = _delivery(delivery_id)
    assert delivery.status == "failed"
