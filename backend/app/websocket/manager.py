from collections import defaultdict
from typing import Any

from fastapi import WebSocket


class WebSocketManager:
    """가게별 WebSocket 연결 목록을 관리하고 메시지를 브로드캐스트합니다."""

    def __init__(self) -> None:
        """가게 id를 기준으로 연결된 WebSocket 목록을 초기화합니다."""

        self._connections: dict[int, list[WebSocket]] = defaultdict(list)

    async def connect(self, store_id: int, websocket: WebSocket) -> None:
        """클라이언트 WebSocket을 수락하고 가게 채널에 등록합니다."""

        await websocket.accept()
        self._connections[store_id].append(websocket)

    def disconnect(self, store_id: int, websocket: WebSocket) -> None:
        """끊긴 WebSocket을 가게 채널에서 제거합니다."""

        connections = self._connections.get(store_id, [])
        if websocket in connections:
            connections.remove(websocket)
        if not connections and store_id in self._connections:
            del self._connections[store_id]

    async def broadcast(self, store_id: int, message: dict[str, Any]) -> None:
        """가게 채널에 연결된 모든 클라이언트에게 JSON 메시지를 보냅니다."""

        disconnected: list[WebSocket] = []
        for websocket in list(self._connections.get(store_id, [])):
            try:
                await websocket.send_json(message)
            except RuntimeError:
                disconnected.append(websocket)
        for websocket in disconnected:
            self.disconnect(store_id, websocket)


manager = WebSocketManager()
