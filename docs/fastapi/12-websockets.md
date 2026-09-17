# FastAPI 12 — WebSockets

## Concept

A WebSocket is a long-lived, bidirectional connection upgraded from HTTP. In
FastAPI you declare `@router.websocket("/path")`; the handler receives a
`WebSocket` object and loops on `receive_*`/`send_*`.

## Why it exists

Polling a REST endpoint for project updates wastes bandwidth and adds latency.
WebSockets push server-side events instantly. The cost: connections are stateful,
which fights every stateless-scaling assumption — that tension is the whole
story of this lesson.

## TeamFlow's endpoint — `app/websocket/router.py`

```python
@router.websocket("/ws/projects/{project_id}")
async def project_socket(
    websocket: WebSocket,
    project_id: uuid.UUID,
    token: str = Query(default=""),
) -> None:
    await websocket.accept()

    async with AsyncSessionLocal() as db:
        try:
            if not token:
                raise PermissionError("missing token")
            user = await authenticate_socket(token, db)
            project = await ProjectRepository(db).get(project_id)
            if project is None:
                raise LookupError("not found")
            membership = await MembershipRepository(db).get_for_user(user.id, project.organization_id)
            if membership is None or not membership.is_active:
                raise LookupError("not found")
        except PermissionError:
            await websocket.close(code=4401, reason="invalid token")
            return
        except LookupError:
            await websocket.close(code=4404, reason="project not found or not a member")
            return

        room = f"project:{project.id}"
        user_room = f"user:{user.id}"
        await manager.connect(websocket, room)
        await manager.connect(websocket, user_room)
        try:
            await websocket.send_json({"type": "connected", "data": {"project_id": str(project.id)}})
            while True:
                raw = await websocket.receive_text()
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    await websocket.send_json({"type": "error", "detail": "invalid JSON"})
                    continue
                mtype = message.get("type") if isinstance(message, dict) else None
                if mtype == "ping":
                    await websocket.send_json({"type": "pong"})
                else:
                    await websocket.send_json({"type": "error", "detail": "unsupported message type"})
        except WebSocketDisconnect:
            pass
        finally:
            await manager.disconnect(websocket, room)
            await manager.disconnect(websocket, user_room)
```

### Design decisions, one by one

**Auth via query parameter.** Browsers cannot set custom headers on the
WebSocket handshake, so the access JWT arrives as `?token=...`. The server
decodes it with the same `security.decode_token` used for HTTP and rejects
non-access tokens (`authenticate_socket` checks `payload["type"]`).

**Accept-then-close with custom codes.** The handler accepts first and then
closes with application codes (`4401` invalid token, `4404` not found / not a
member) so clients can distinguish auth failure from "you don't belong here"
instead of seeing a generic handshake error.

**Membership is checked at connection time.** The project id comes from the
path — the same tenant-boundary discipline as HTTP: resolve the project, then
the caller's membership in *its* org. The endpoint never trusts a client-supplied
org id.

**Two rooms per socket.** `project:{id}` receives project events; `user:{id}`
receives personal notifications. One connection, two subscriptions — this is
why the `ConnectionManager` is keyed by *room string*, not by project.

**Client messages are minimal.** Only `{"type": "ping"}` is supported.
Anything else → `{"type": "error"}`; malformed JSON → error and *continue*.
Invalid input must never kill the connection or crash the worker.

**Disconnect handling is a `finally`.** Whether the client leaves cleanly
(`WebSocketDisconnect`), the server closes, or an exception fires, both rooms
are cleaned up. Forgetting the cleanup leaks sockets in the manager — a slow
memory leak under churn.

## The connection manager — `app/websocket/manager.py`

```python
class ConnectionManager:
    def __init__(self) -> None:
        self._rooms: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, room: str) -> None:
        async with self._lock:
            self._rooms.setdefault(room, set()).add(websocket)

    async def disconnect(self, websocket: WebSocket, room: str) -> None:
        async with self._lock:
            sockets = self._rooms.get(room)
            if sockets:
                sockets.discard(websocket)
                if not sockets:
                    self._rooms.pop(room, None)

    async def send_to_room(self, room: str, event: dict) -> None:
        sockets = list(self._rooms.get(room, ()))
        dead: list[WebSocket] = []
        for socket in sockets:
            try:
                await socket.send_json(event)
            except Exception:
                dead.append(socket)
        for socket in dead:
            await self.disconnect(socket, room)
```

- The lock protects the registry from concurrent connect/disconnect (two tasks
  can mutate it mid-await).
- `send_to_room` treats send failures as disconnects — dead sockets are pruned
  on first write failure instead of accumulating.
- `parse_redis_event` (same file) drops malformed pub/sub payloads instead of
  raising — the listener must never die from bad data.

## The complete event path

```
service (any worker)                 FastAPI worker process
    │                                     listener task (lifespan)
    │ events.publish_project_event            │
    ▼                                         │ pubsub.listen()
redis.publish("teamflow:ws", json)  ─────────►│ parse_redis_event()
                                              ▼
                                     manager.send_to_room("project:{id}", event)
                                              ▼
                                     socket.send_json(event)
```

`app/services/events.py`:

```python
WS_CHANNEL = "teamflow:ws"

async def publish(channel: str, event_type: str, data=None) -> None:
    payload = {"channel": channel, "event": {"type": event_type, "data": data or {}, "ts": now_iso()}}
    try:
        await get_redis_client().publish(WS_CHANNEL, json.dumps(payload))
    except Exception:
        logger.exception("Failed to publish realtime event %s", event_type)
```

One channel, room name inside the payload. Simpler than per-room channels and
fine at this scale; the trade-off (every worker parses every event) is noted in
`infrastructure/06-websocket-scaling.md`.

Events emitted by services include: `task.created`, `task.updated`,
`task.deleted`, `comment.created`, and `notification` (to `user:{id}`).

## Message protocol (what a client actually sees)

```json
{"type": "connected", "data": {"project_id": "..."}}
{"type": "task.created", "data": {"id": "...", "title": "...", ...}, "ts": "..."}
{"type": "pong"}
{"type": "error", "detail": "invalid JSON"}
```

## Django/DRF comparison 🔵

| Django | FastAPI |
| --- | --- |
| Django Channels (`consumers.py`, groups, channel layer) | `@router.websocket` + custom manager + Redis pub/sub |
| `channel_layer.group_send` | `redis.publish` + listener |
| `AuthMiddlewareStack` (session cookie) | query-param JWT + explicit membership check |
| `async_to_sync` bridges | natively async throughout |

Django Channels' "channel layer" concept maps 1:1 to TeamFlow's
publish→Redis→listener→manager path. The difference: Channels gives you the
abstraction; here you build it, which is precisely the learning value.

## Production perspective

- **Multi-worker correctness is by construction** (`infrastructure/06-websocket-scaling.md`):
  no worker assumes it holds all sockets.
- **Backpressure**: `send_json` awaits each socket; a slow client can delay a
  room broadcast. At scale you'd isolate sends with timeouts or per-socket
  queues. TeamFlow accepts the simple version (documented trade-off).
- **No lifecycle limits**: servers/proxies need WS-aware timeouts
  (`deploy/nginx.conf` sets `proxy_read_timeout`) and clients should ping to
  keep idle connections alive (the `ping`/`pong` protocol exists for that).
- **Scale-out**: `gunicorn`/uvicorn workers each hold their own sockets; sticky
  sessions are unnecessary thanks to pub/sub.

## Common mistakes

1. **In-process broadcast only** (`manager.broadcast` inside the service) —
   works on one worker, silently drops events on the second. TeamFlow publishes
   to Redis from the service and only *delivers* from the manager.
2. **Doing DB work in the receive loop without a session** — TeamFlow opens one
   short-lived session for the handshake, not for the connection lifetime.
3. **Forgetting `finally: disconnect`** — room registry leaks sockets.
4. **Trusting path `project_id` without a membership check** — the WS endpoint
   is an API surface too (IDOR applies).
5. **Serving WebSockets through proxies without upgrade headers** — nginx needs
   `Upgrade`/`Connection` headers (`deploy/nginx.conf`).

## Cheat sheet

```python
@router.websocket("/ws/projects/{project_id}")
async def ws_endpoint(websocket: WebSocket, project_id: UUID, token: str = Query("")):
    await websocket.accept()
    # authenticate + authorize BEFORE registering rooms
    await manager.connect(websocket, f"project:{project_id}")
    try:
        while True:
            msg = await websocket.receive_text()   # validate, never crash
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(websocket, f"project:{project_id}")
```

## Review questions

1. Why is the JWT sent as a query parameter instead of a header?
2. What are the two rooms a single project socket joins, and which events use
   each?
3. Trace the path of a `task.created` event from service to socket, naming every
   component.
4. Why do send failures remove sockets from the manager?
5. What would break if `manager` were module-global *and* the app ran with
   4 workers, with services calling `manager.broadcast` directly?
