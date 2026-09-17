"""Idempotency middleware for `Idempotency-Key`-guarded write requests.

Design (transaction-correct, not post-hoc):
  1. Before the route runs, the middleware INSERTs a row keyed by
     (identity, method, path, key) with status `in_progress`. The unique
     constraint on `key` makes the claim the race arbiter: concurrent
     duplicates hit the DB constraint, not a check-then-act gap.
  2. `completed` records replay the stored response (with
     `Idempotency-Replayed: true`) while within the TTL; a body-hash mismatch
     on the same key -> 422.
  3. An `in_progress` record younger than the grace window -> 409 with
     `Retry-After: 1` (another worker is processing it right now).
  4. `failed` or stale claims are re-claimed and the request proceeds.
  5. After the response, 2xx-4xx responses are persisted for replay; 5xx
     marks the record `failed` so the client can safely retry.

Identity = JWT subject (best-effort decode) or client IP for anonymous
requests. Rows expire after settings.idempotency_ttl_hours (Celery cleanup).
"""

import hashlib
import json
import re
import time
import uuid
from datetime import UTC, datetime

import jwt as pyjwt
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from starlette.datastructures import Headers, MutableHeaders

from app.core import security
from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.models import IdempotencyKey
from app.repositories import IdempotencyRepository

VALID_KEY = re.compile(r"^[A-Za-z0-9_.-]{8,128}$")
IDEMPOTENT_METHODS = frozenset({"POST", "PATCH", "DELETE"})
IN_FLIGHT_GRACE_SECONDS = 30
MAX_REPLAY_BYTES = 1_000_000


class IdempotencyMiddleware:
    HEADER = "idempotency-key"

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope.get("method") not in IDEMPOTENT_METHODS:
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        raw_key = headers.get(self.HEADER)
        if not raw_key:
            await self.app(scope, receive, send)
            return
        if not VALID_KEY.match(raw_key):
            await _send_json(send, 400, {"detail": "Invalid Idempotency-Key"})
            return

        body = await _collect_body(receive)
        request_hash = hashlib.sha256(body).hexdigest()
        identity = _identity(headers, scope)
        scope_key = f"{identity}|{scope['method']}|{scope['path']}|{raw_key}"

        decision = await self._claim(
            scope_key, scope["path"], scope["method"], identity, request_hash
        )
        if decision.action == "reject":
            await _send_json(
                send,
                decision.status_code,
                decision.body,
                decision.headers,
                decision.raw_body,
            )
            return

        captured = {"status": None, "chunks": bytearray(), "content_type": None}
        original_send = send

        async def send_wrapper(message) -> None:
            if message["type"] == "http.response.start":
                captured["status"] = message["status"]
                captured["content_type"] = _content_type(message)
            elif message["type"] == "http.response.body":
                captured["chunks"].extend(message.get("body", b""))
            await original_send(message)

        body_state = {"done": False}

        async def replay_receive():
            if body_state["done"]:
                return {"type": "http.disconnect"}
            body_state["done"] = True
            return {"type": "http.request", "body": body, "more_body": False}

        try:
            await self.app(scope, replay_receive, send_wrapper)
        except Exception:
            await self._mark_failed(scope_key)
            raise

        status = captured["status"]
        payload = bytes(captured["chunks"])
        if status is not None and status < 500 and len(payload) <= MAX_REPLAY_BYTES:
            await self._store_response(
                scope_key, status, captured["content_type"],
                payload.decode("utf-8", "replace"),
            )
        elif status is not None:
            await self._mark_failed(scope_key)

    async def _claim(self, key, path, method, identity, request_hash):
        try:
            async with AsyncSessionLocal() as db:
                record = IdempotencyKey(
                    key=key,
                    user_id=_user_id(identity),
                    method=method,
                    path=path,
                    request_hash=request_hash,
                )
                db.add(record)
                await db.commit()
                return _Claim(action="proceed")
        except IntegrityError:
            return await self._handle_conflict(key, request_hash)

    async def _handle_conflict(self, key: str, request_hash: str):
        async with AsyncSessionLocal() as db:
            existing = (
                await db.execute(select(IdempotencyKey).where(IdempotencyKey.key == key))
            ).scalar_one_or_none()
            if existing is None:
                # Vanishingly rare: concurrent cleanup of an expired key.
                return _Claim(action="proceed")

            age = time.time() - _epoch(existing.created_at)
            if existing.request_hash != request_hash:
                return _Claim(
                    action="reject", status_code=422,
                    body={"detail": "Idempotency-Key was already used with a different request body"},
                )
            if existing.status == "completed" and age <= settings.idempotency_ttl_hours * 3600:
                return _Claim(
                    action="reject", status_code=existing.response_status or 200,
                    body=existing.response_body or "",
                    headers={
                        "content-type": existing.content_type or "application/json",
                        "idempotency-replayed": "true",
                    },
                    raw_body=True,
                )
            if existing.status == "in_progress" and age < IN_FLIGHT_GRACE_SECONDS:
                return _Claim(
                    action="reject", status_code=409,
                    body={"detail": "Request with this Idempotency-Key is already in progress"},
                    headers={"retry-after": "1"},
                )
            # failed, or stale in_progress: re-claim and proceed.
            existing.status = "in_progress"
            existing.request_hash = request_hash
            existing.response_status = None
            existing.response_body = None
            db.add(existing)
            await db.commit()
            return _Claim(action="proceed")

    async def _store_response(self, key, status, content_type, body) -> None:
        async with AsyncSessionLocal() as db:
            await IdempotencyRepository(db).complete(key, status, content_type, body)

    async def _mark_failed(self, key) -> None:
        async with AsyncSessionLocal() as db:
            await IdempotencyRepository(db).fail(key)


class _Claim:
    def __init__(self, action, status_code=None, body=None, headers=None, raw_body=False):
        self.action = action
        self.status_code = status_code
        self.body = body
        self.headers = headers or {}
        self.raw_body = raw_body


async def _collect_body(receive) -> bytes:
    chunks = bytearray()
    while True:
        message = await receive()
        chunks.extend(message.get("body", b""))
        if not message.get("more_body"):
            return bytes(chunks)


def _identity(headers: Headers, scope) -> str:
    auth = headers.get("authorization", "")
    if auth.startswith("Bearer "):
        try:
            payload = security.decode_token(auth[7:])
            sub = payload.get("sub")
            if sub:
                uuid.UUID(sub)
                return f"u-{sub}"
        except (pyjwt.PyJWTError, ValueError):
            pass
    client = scope.get("client")
    return f"ip-{client[0] if client else 'unknown'}"


def _user_id(identity: str) -> uuid.UUID | None:
    if identity.startswith("u-"):
        try:
            return uuid.UUID(identity[2:])
        except ValueError:
            return None
    return None


def _epoch(dt: datetime) -> float:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC).timestamp()
    return dt.timestamp()


def _content_type(message) -> str | None:
    return next(
        (v for k, v in MutableHeaders(scope=message).items() if k == "content-type"),
        None,
    )


async def _send_json(send, status_code: int, body, headers=None, raw_body=False) -> None:
    payload = body if isinstance(body, str) else json.dumps(body)
    encoded = payload.encode()
    response_headers = dict(headers or {})
    response_headers.setdefault("content-type", "application/json")
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (k.encode(), v.encode()) for k, v in response_headers.items()
            ],
        }
    )
    await send({"type": "http.response.body", "body": encoded})
