"""Redis pub/sub listener + WebSocket endpoint.

Wiring: publish (any process) -> Redis channel `teamflow:ws` -> this listener
(one per API worker, started in the app lifespan) -> ConnectionManager ->
connected sockets. This is what makes `/ws/projects/{id}` work with multiple
uvicorn/gunicorn workers.
"""

import asyncio
import json
import logging
import uuid

import jwt as pyjwt
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import security
from app.core.db import AsyncSessionLocal
from app.core.redis import get_redis_client
from app.models import User
from app.repositories import MembershipRepository, ProjectRepository
from app.services.events import WS_CHANNEL
from app.websocket.manager import manager, parse_redis_event

logger = logging.getLogger(__name__)

router = APIRouter(tags=["realtime"])


async def run_redis_listener(stop: asyncio.Event) -> None:
    """Subscribes to the fan-out channel and forwards events to local sockets.
    Runs as a background task for the process lifetime; reconnects on failure.
    Malformed messages are dropped, never fatal."""
    while not stop.is_set():
        pubsub = None
        try:
            pubsub = get_redis_client().pubsub()
            await pubsub.subscribe(WS_CHANNEL)
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                parsed = parse_redis_event(message.get("data"))
                if parsed is None:
                    continue
                room, event = parsed
                await manager.send_to_room(room, event)
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("WS listener disconnected from Redis; retrying in 2s")
            await asyncio.sleep(2)
        finally:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe(WS_CHANNEL)
                    await pubsub.aclose()
                except Exception:
                    pass


async def authenticate_socket(token: str, db: AsyncSession) -> User:
    """WebSocket auth: access JWT via query parameter (browsers cannot set
    custom headers on WebSocket handshakes)."""
    try:
        payload = security.decode_token(token)
    except pyjwt.PyJWTError:
        raise PermissionError("invalid token") from None
    if payload.get("type") != security.TOKEN_TYPE_ACCESS:
        raise PermissionError("access token required")
    user = await db.get(User, uuid.UUID(payload["sub"]))
    if not user or not user.is_active:
        raise PermissionError("unknown user")
    return user


@router.websocket("/ws/projects/{project_id}")
async def project_socket(
    websocket: WebSocket,
    project_id: uuid.UUID,
    token: str = Query(default=""),
) -> None:
    """Project realtime channel.

    Auth via `?token=<access JWT>`. Join errors close the socket with codes:
    4401 (invalid token), 4404 (project not found or not a member).
    Client messages: only `{"type": "ping"}` is supported -> `{"type": "pong"}`.
    Anything else gets `{"type": "error"}` so clients fail fast; malformed
    JSON never crashes the socket.
    """
    await websocket.accept()

    async with AsyncSessionLocal() as db:
        try:
            if not token:
                raise PermissionError("missing token")
            user = await authenticate_socket(token, db)
            project = await ProjectRepository(db).get(project_id)
            if project is None:
                raise LookupError("not found")
            membership = await MembershipRepository(db).get_for_user(
                user.id, project.organization_id
            )
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
            await websocket.send_json(
                {"type": "connected", "data": {"project_id": str(project.id)}}
            )
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
                    await websocket.send_json(
                        {"type": "error", "detail": "unsupported message type"}
                    )
        except WebSocketDisconnect:
            pass
        finally:
            await manager.disconnect(websocket, room)
            await manager.disconnect(websocket, user_room)
