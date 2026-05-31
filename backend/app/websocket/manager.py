from collections import defaultdict
from typing import Any

from fastapi import WebSocket


class WebSocketManager:
    def __init__(self) -> None:
        self._connections: dict[int, list[WebSocket]] = defaultdict(list)

    async def connect(self, store_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[store_id].append(websocket)

    def disconnect(self, store_id: int, websocket: WebSocket) -> None:
        connections = self._connections.get(store_id, [])
        if websocket in connections:
            connections.remove(websocket)
        if not connections and store_id in self._connections:
            del self._connections[store_id]

    async def broadcast(self, store_id: int, message: dict[str, Any]) -> None:
        disconnected: list[WebSocket] = []
        for websocket in list(self._connections.get(store_id, [])):
            try:
                await websocket.send_json(message)
            except RuntimeError:
                disconnected.append(websocket)
        for websocket in disconnected:
            self.disconnect(store_id, websocket)


manager = WebSocketManager()

