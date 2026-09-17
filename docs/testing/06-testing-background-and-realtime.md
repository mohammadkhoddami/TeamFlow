# Testing 06 — Testing Background Work and Realtime

## Concept

Celery tasks and WebSockets are hard to test because they run outside the
request/response cycle. TeamFlow tests them by **invoking the real functions in
controlled conditions**: a real local HTTP receiver for webhooks, `TestClient`
with lifespan for WebSockets.

## Webhook delivery — `tests/workers/test_webhook_delivery.py`

### The receiver fixture (real HTTP, ephemeral port)

```python
@pytest.fixture
def receiver_factory():
    servers: list[tuple[HTTPServer, threading.Thread]] = []

    def _make(status: int = 200):
        received: list[dict] = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("content-length", 0))
                body = self.rfile.read(length)
                received.append({"sig": self.headers.get("X-TeamFlow-Signature"),
                                 "ts": self.headers.get("X-TeamFlow-Timestamp"),
                                 "delivery": self.headers.get("X-TeamFlow-Delivery"),
                                 "event": self.headers.get("X-TeamFlow-Event"),
                                 "body": json.loads(body)})
                self.send_response(status)
                self.end_headers()
                self.wfile.write(b"ok")
        server = HTTPServer(("127.0.0.1", 0), Handler)     # port 0 = OS-assigned
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append((server, thread))
        return f"http://127.0.0.1:{server.server_address[1]}/hook", received

    yield _make
    for server, thread in servers:
        server.shutdown(); thread.join(timeout=2)
```

A real socket, real headers, real JSON body — and a configurable status code so
one fixture covers success, transient (500), and permanent (404) paths.

### Test 1 — success path verifies the signature independently

```python
def test_deliver_webhook_success_records_delivery(receiver_factory):
    url, received = receiver_factory(status=200)
    payload = {"id": None, "event": "task.created", "data": {"title": "Worker test"}}
    delivery_id = _seed_delivery(url, "worker-test-secret", payload)

    from app.workers.tasks import deliver_webhook
    result = deliver_webhook.run(delivery_id)          # sync call, no broker

    assert result["status"] == "delivered" and result["code"] == 200
    delivery = _delivery(delivery_id)
    assert delivery.status == "success" and delivery.attempts == 1
    assert delivery.delivered_at is not None

    hit = received[0]
    body = json.dumps(payload).encode()
    expected = "v1=" + hmac.new(b"worker-test-secret", f"{hit['ts']}.".encode() + body,
                                hashlib.sha256).hexdigest()
    assert hit["sig"] == expected and hit["delivery"] == delivery_id
```

Notes:

- `deliver_webhook.run(id)` executes the task body synchronously — no broker,
  no worker, but the real code path.
- The HMAC is recomputed from first principles — the receiver-proof property.
- `_seed_delivery` creates org + webhook + delivery with the sync `session_scope`
  (workers are sync; tests follow the same path).

### Test 2 — transient failure state

```python
def test_deliver_webhook_transient_5xx_persists_retryable_state(receiver_factory):
    # exhausted-retries path: _retry_or_fail marks failed without raising
    result = worker_tasks._retry_or_fail(FakeTask(), delivery_id, 1, "HTTP 500")
    assert result == {"status": "failed", "attempts": 1}
    delivery = _delivery(delivery_id)
    assert delivery.status == "failed" and delivery.last_error == "HTTP 500"
```

The Celery retry machinery (raising to schedule a retry) is stubbed at the
boundary via a `FakeTask` with `retries == max_retries`; the *bookkeeping* code
(attempts, status, last_error) is exercised for real. This is the right split:
Celery's scheduler is framework behavior; the state transitions are TeamFlow's.

### Test 3 — idempotent redelivery

```python
r1 = deliver_webhook.run(delivery_id)
assert r1["status"] == "delivered"
r2 = deliver_webhook.run(delivery_id)                  # duplicate enqueue
assert r2["status"] == "already_delivered"
assert len(received) == 1                              # exactly one HTTP hit
```

### Test 4 — permanent 4xx

```python
result = deliver_webhook.run(delivery_id)              # receiver returns 404
assert result["status"] == "failed_permanently"
assert _delivery(delivery_id).status == "failed"
```

## Cleanup task — `tests/workers/test_cleanup_email.py`

```python
def test_cleanup_purges_expired_idempotency_keys():
    with session_scope() as db:
        db.add(IdempotencyKey(key="old-key-00000001", ...))
        db.flush()
        db.execute(update(IdempotencyKey).where(...).values(
            created_at=datetime.now(UTC) - timedelta(hours=48)))
        db.add(IdempotencyKey(key="fresh-key-0000001", ...))

    removed = cleanup_expired_data.run()
    assert removed["idempotency_keys"] == 1
    with session_scope() as db:
        assert list(db.execute(select(IdempotencyKey.key)).scalars()) == ["fresh-key-0000001"]
```

Same seed-then-run-then-inspect pattern for stale attachments.

## Email — console backend test

```python
def test_send_email_console_backend_logs(monkeypatch, caplog):
    with caplog.at_level("INFO", logger="app.services.integrations.email"):
        result = send_email_task.apply(args=["to@example.com", "password_reset",
                                             {"reset_link": "http://x/r?t=abc"}]).get()
    assert result["status"] == "sent"
    assert "http://x/r?t=abc" in caplog.text        # rendered + dispatched
```

`task.apply()` = eager, synchronous execution with the real rendering code.

## WebSockets — `tests/integration/test_websockets.py`

Sync tests with `TestClient` (which **runs lifespan** — the Redis listener must
be alive, unlike ASGITransport):

```python
@pytest.fixture
def ws_client():
    _truncate_all()                                  # sync psycopg truncation
    with TestClient(app) as tc:                      # __enter__ runs lifespan
        yield tc
    _truncate_all()
```

```python
def test_task_created_event_reaches_connected_member(ws_client):
    alice, _, project = _seed(ws_client)
    with ws_client.websocket_connect(f"/ws/projects/{project['id']}?token={alice['token']}") as ws:
        assert ws.receive_json()["type"] == "connected"
        r = ws_client.post(f"/api/v1/projects/{project['id']}/tasks",
                           json={"title": "Realtime task"},
                           headers={"Authorization": f"Bearer {alice['token']}"})
        assert r.status_code == 201
        event = ws.receive_json()
        assert event["type"] == "task.created" and event["data"]["id"] == r.json()["id"]
```

This exercises the entire realtime path in-process: service → redis.publish →
listener task (running in TestClient's portal loop) → manager → socket.

Why these tests are sync: `TestClient` is sync, and sync tests don't run the
async truncation fixture — hence the explicit psycopg truncation. (This is a
documented wart of the test suite; the alternative — async tests with a
blocking TestClient — deadlocks.)

## Django/DRF comparison 🔵

| Django | TeamFlow |
| --- | --- |
| `@override_settings(CELERY_TASK_ALWAYS_EAGER=True)` | `task.run()`/`task.apply()` direct invocation |
| `requests_mock` / `responses` | real threaded HTTP receiver |
| Channels `WebsocketCommunicator` | `TestClient.websocket_connect` |
| `django-celery` test helpers | none needed — tasks are plain functions |

## Common mistakes

1. **Mocking httpx.post for webhook tests** — then signatures/headers/status
   classification go untested. A 20-line receiver is cheap and real.
2. **Testing Celery's retry scheduling itself** — that's framework behavior;
   test *your* bookkeeping (`attempts`, `last_error`, terminal states).
3. **Forgetting `TestClient` runs lifespan while `ASGITransport` doesn't** —
   WS tests silently fail to receive events if written with the async client.
4. **Leaving receiving servers un-shutdown** — leaked threads/ports across tests
   (the fixture tears them down).
5. **Eager-mode side effects leaking into other tests** — always truncate
   afterwards.

## Review questions

1. What is `deliver_webhook.run(id)` versus `.delay(id)`, and why does the test
   use the former?
2. How does the suite verify the HMAC without trusting `sign_payload`?
3. Why is `_retry_or_fail` invoked with a `FakeTask` instead of letting Celery
   retry for real?
4. Why must WebSocket tests use `TestClient` rather than `ASGITransport`?
