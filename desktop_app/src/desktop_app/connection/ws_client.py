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


# Retry schedule after a drop. A Pi reboot takes the better part of a minute,
# so the first attempts are quick (a dropped Wi-Fi frame recovers immediately)
# and then settle into a steady poll rather than giving up.
_BACKOFF_SECONDS = (1, 2, 4, 8)
_BACKOFF_MAX_SECONDS = 15


class WsClient(QObject):
    """Transport only: owns the single persistent control-channel connection and
    re-emits raw envelopes. Parsing and domain state live in AppState."""

    message_received = Signal(dict)
    connected = Signal()
    reconnecting = Signal(int, float)  # (attempt, seconds until next try)
    auth_rejected = Signal(str)
    disconnected = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._socket = None
        self._recv_task: asyncio.Task | None = None
        # Filled from auth.ok; carried in the handshake rather than a separate
        # push so no consumer can observe the connection before it is known.
        self.capabilities = Capabilities()

        # Credentials of the last successful connect, kept so the client can
        # come back on its own. Rebooting the Pi is a feature of this app, so a
        # drop is an expected event, not a fatal one.
        self._credentials: tuple[str, int, str] | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._closing = False

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
        self._credentials = (host, port, token)
        self._closing = False
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
            self._schedule_reconnect()
        finally:
            if self._socket is socket:
                self._socket = None

    # --- reconnection -------------------------------------------------------

    def _schedule_reconnect(self) -> None:
        if self._closing or self._credentials is None:
            return
        if self._reconnect_task is not None and not self._reconnect_task.done():
            return
        self._reconnect_task = asyncio.ensure_future(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        """Keep trying until the agent answers again or close() is called.

        Never gives up on its own: the usual reason to be here is a reboot this
        very application asked for, and an app that goes dead until manually
        restarted would make its own power buttons hostile.
        """
        assert self._credentials is not None
        host, port, token = self._credentials

        attempt = 0
        while not self._closing:
            attempt += 1
            delay = (
                _BACKOFF_SECONDS[attempt - 1]
                if attempt <= len(_BACKOFF_SECONDS)
                else _BACKOFF_MAX_SECONDS
            )
            self.reconnecting.emit(attempt, delay)
            await asyncio.sleep(delay)
            if self._closing:
                return

            try:
                result = await self.connect(host, port, token)
            except Exception as exc:  # noqa: BLE001 - Pi still down, keep waiting
                logger.debug("reconnect attempt %d failed: %s", attempt, exc)
                continue
            if result is AuthResult.OK:
                logger.info("reconnected after %d attempt(s)", attempt)
                return
            # A rejected token will not fix itself by retrying.
            return

    async def close(self) -> None:
        self._closing = True
        if self._reconnect_task is not None:
            self._reconnect_task.cancel()
            self._reconnect_task = None
        if self._socket is not None:
            await self._socket.close()
            self._socket = None
