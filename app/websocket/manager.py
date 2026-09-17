"""ConnectionManager: process-local registry of live WebSocket connections.

Because fan-out goes through Redis pub/sub (see events.py and the listener
below), any worker can publish an event and every worker forwards it to its
own local sockets — the design is multi-worker safe by construction.
"""

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


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

    def room_size(self, room: str) -> int:
        return len(self._rooms.get(room, ()))

    async def send_to_room(self, room: str, event: dict[str, Any]) -> None:
        sockets = list(self._rooms.get(room, ()))
        dead: list[WebSocket] = []
        for socket in sockets:
            try:
                await socket.send_json(event)
            except Exception:
                dead.append(socket)
        for socket in dead:
            await self.disconnect(socket, room)

    async def broadcast(self, event: dict[str, Any]) -> None:
        for room in list(self._rooms.keys()):
            await self.send_to_room(room, event)


manager = ConnectionManager()


def parse_redis_event(raw: str | bytes) -> tuple[str, dict[str, Any]] | None:
    """Returns (room, event) or None for malformed payloads (invalid messages
    must never crash the listener)."""
    try:
        payload = json.loads(raw)
        room = payload["channel"]
        event = payload["event"]
        if not isinstance(room, str) or not isinstance(event, dict):
            return None
        return room, event
    except (json.JSONDecodeError, KeyError, TypeError, UnicodeDecodeError):
        logger.warning("Discarding malformed realtime event")
        return None
