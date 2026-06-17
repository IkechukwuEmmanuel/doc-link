"""WebSocket endpoint bridging FastAPI to the pycrdt y-websocket server."""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services import slug as slug_service
from app.services.crdt import PadWebsocketServer

router = APIRouter(tags=["realtime"])

server = PadWebsocketServer()


class _FastAPIChannel:
    """Adapts a FastAPI WebSocket to the pycrdt ``Channel`` protocol.

    ``path`` is the room name (the pad slug); pycrdt's ``serve()`` reads it to
    pick the room. Messages are exchanged as raw bytes.
    """

    def __init__(self, websocket: WebSocket, path: str) -> None:
        self._ws = websocket
        self.path = path

    def __aiter__(self) -> "_FastAPIChannel":
        return self

    async def __anext__(self) -> bytes:
        try:
            return await self.recv()
        except WebSocketDisconnect:
            raise StopAsyncIteration

    async def send(self, message: bytes) -> None:
        await self._ws.send_bytes(message)

    async def recv(self) -> bytes:
        return await self._ws.receive_bytes()


@router.websocket("/api/pads/{slug}/ws")
async def pad_ws(websocket: WebSocket, slug: str) -> None:
    try:
        slug = slug_service.validate_custom_slug(slug)
    except slug_service.SlugError:
        await websocket.close(code=4404)
        return

    await websocket.accept()
    channel = _FastAPIChannel(websocket, slug)
    try:
        await server.serve(channel)
    except WebSocketDisconnect:
        pass
