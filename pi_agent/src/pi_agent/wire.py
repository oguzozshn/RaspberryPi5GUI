from __future__ import annotations

import asyncio

from fastapi import WebSocket
from pydantic import BaseModel

from pi_protocol import Envelope, ErrorPayload, MessageType


class Connection:
    """One authenticated client. Serialises sends behind a lock because handlers
    run as concurrent tasks - two of them writing to the same socket at once
    would interleave frames."""

    def __init__(self, websocket: WebSocket) -> None:
        self._websocket = websocket
        self._lock = asyncio.Lock()

    @property
    def client_ip(self) -> str:
        client = self._websocket.client
        return client.host if client else "unknown"

    async def send(
        self, msg_type: MessageType, payload: BaseModel, reply_to: str | None = None
    ) -> None:
        """Send one envelope. `reply_to` echoes the request's id so the client can
        correlate a response with the request that produced it."""
        envelope = Envelope(type=msg_type, payload=payload)
        if reply_to is not None:
            envelope.id = reply_to
        async with self._lock:
            await self._websocket.send_json(envelope.model_dump(mode="json"))

    async def send_error(self, code: str, message: str, reply_to: str | None = None) -> None:
        await self.send(MessageType.ERROR, ErrorPayload(code=code, message=message), reply_to)
