from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

from .store import RuntimeStore


class ConnectionManager:
    def __init__(self, store: RuntimeStore) -> None:
        self._store = store
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._device_connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(
        self,
        websocket: WebSocket,
        device_id: str,
        edge_id: str | None,
        *,
        track_device_session: bool = True,
    ) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[device_id].add(websocket)
            if track_device_session:
                self._device_connections[device_id].add(websocket)
                self._store.set_session_connected(device_id, edge_id, True)

    async def disconnect(
        self,
        websocket: WebSocket,
        device_id: str,
        edge_id: str | None,
        *,
        track_device_session: bool = True,
    ) -> None:
        async with self._lock:
            self._connections[device_id].discard(websocket)
            if not self._connections[device_id]:
                self._connections.pop(device_id, None)
            if track_device_session:
                self._device_connections[device_id].discard(websocket)
                if not self._device_connections[device_id]:
                    self._device_connections.pop(device_id, None)
                    self._store.set_session_connected(device_id, edge_id, False)
            elif not self._device_connections.get(device_id):
                self._device_connections.pop(device_id, None)

    async def broadcast(self, device_id: str, message: dict[str, Any]) -> int:
        async with self._lock:
            sockets = list(self._connections.get(device_id, set()))
        delivered = 0
        stale: list[WebSocket] = []
        for websocket in sockets:
            try:
                await websocket.send_json(message)
                delivered += 1
            except Exception:
                stale.append(websocket)
        if stale:
            async with self._lock:
                for websocket in stale:
                    self._connections[device_id].discard(websocket)
        return delivered

    async def send(self, websocket: WebSocket, message: dict[str, Any]) -> None:
        await websocket.send_json(message)

    def connection_count(self) -> int:
        return sum(len(sockets) for sockets in self._connections.values())

    def device_connection_count(self, device_id: str) -> int:
        return len(self._connections.get(device_id, set()))
