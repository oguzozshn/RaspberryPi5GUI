from __future__ import annotations

import asyncio
import json
import logging
from enum import Enum

import websockets
from PySide6.QtCore import QObject, Signal
from pydantic import BaseModel

from pi_protocol import AuthOkPayload, AuthRequestPayload, Capabilities, Envelope, MessageType

logger = logging.getLogger("desktop_app.ws_client")


class AuthResult(Enum):
    OK = "ok"
    REJECTED = "rejected"


class WsClient(QObject):
    """Transport only: owns the single persistent control-channel connection and
    re-emits raw envelopes. Parsing and domain state live in AppState."""

    message_received = Signal(dict)
    connected = Signal()
    auth_rejected = Signal(str)
    disconnected = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._socket = None
        self._recv_task: asyncio.Task | None = None
        # Filled from auth.ok; carried in the handshake rather than a separate
        # push so no consumer can observe the connection before it is known.
        self.capabilities = Capabilities()

    @property
    def is_connected(self) -> bool:
        return self._socket is not None

    async def connect(self, host: str, port: int, token: str) -> AuthResult:
        url = f"ws://{host}:{port}/ws"
        socket = await websockets.connect(url, open_timeout=5, max_size=8 * 1024 * 1024)

        request = Envelope(type=MessageType.AUTH_REQUEST, payload=AuthRequestPayload(token=token))
        await socket.send(request.model_dump_json())

        raw = await asyncio.wait_for(socket.recv(), timeout=5)
        data = json.loads(raw)
        msg_type = data.get("type")

        if msg_type != MessageType.AUTH_OK.value:
            reason = data.get("payload", {}).get("reason", f"unexpected reply: {msg_type}")
            await socket.close()
            self.auth_rejected.emit(reason)
            return AuthResult.REJECTED

        try:
            self.capabilities = Envelope[AuthOkPayload].model_validate(data).payload.capabilities
        except Exception:  # noqa: BLE001 - an older agent may omit capabilities
            logger.warning("auth.ok carried no usable capabilities; assuming none")
            self.capabilities = Capabilities()

        self._socket = socket
        self._recv_task = asyncio.ensure_future(self._listen())
        self.connected.emit()
        return AuthResult.OK

    async def send(self, msg_type: MessageType, payload: BaseModel) -> str:
        """Send a request and return its envelope id, so the caller can match the
        response that arrives later via message_received."""
        if self._socket is None:
            raise RuntimeError("not connected")
        envelope = Envelope(type=msg_type, payload=payload)
        await self._socket.send(envelope.model_dump_json())
        return envelope.id

    async def _listen(self) -> None:
        socket = self._socket
        assert socket is not None
        try:
            async for raw in socket:
                try:
                    self.message_received.emit(json.loads(raw))
                except json.JSONDecodeError:
                    logger.warning("dropping non-JSON frame")
        except websockets.ConnectionClosed as exc:
            self.disconnected.emit(str(exc))
        finally:
            if self._socket is socket:
                self._socket = None

    async def close(self) -> None:
        if self._socket is not None:
            await self._socket.close()
            self._socket = None
