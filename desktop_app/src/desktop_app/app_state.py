from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal
from pydantic import ValidationError

from pi_protocol import (
    Envelope,
    ErrorPayload,
    FilesListPayload,
    FilesListResultPayload,
    MessageType,
    ProcessListPayload,
    ProcessListResultPayload,
    StatsUpdatePayload,
)

from desktop_app.connection.ws_client import WsClient

logger = logging.getLogger("desktop_app.app_state")


class AppState(QObject):
    """Single source of domain truth for the UI. Parses envelopes off WsClient,
    keeps the latest values so a page opened mid-session can render immediately,
    and re-emits them as typed signals. Pages talk to this, never to the socket."""

    stats_updated = Signal(StatsUpdatePayload)
    processes_updated = Signal(ProcessListResultPayload)
    files_listed = Signal(FilesListResultPayload)
    error_received = Signal(str, str)
    connection_changed = Signal(bool, str)

    def __init__(self, ws_client: WsClient, host: str, port: int, token: str) -> None:
        super().__init__()
        self._ws_client = ws_client
        self.host = host
        self.port = port
        self.token = token

        self.latest_stats: StatsUpdatePayload | None = None
        self.latest_processes: ProcessListResultPayload | None = None

        ws_client.message_received.connect(self._on_message)
        ws_client.disconnected.connect(lambda reason: self.connection_changed.emit(False, reason))
        ws_client.connected.connect(lambda: self.connection_changed.emit(True, ""))

    # --- incoming ----------------------------------------------------------

    def _on_message(self, raw: dict) -> None:
        try:
            msg_type = MessageType(raw.get("type"))
        except ValueError:
            logger.warning("unknown message type from agent: %r", raw.get("type"))
            return

        try:
            if msg_type is MessageType.STATS_UPDATE:
                payload = Envelope[StatsUpdatePayload].model_validate(raw).payload
                self.latest_stats = payload
                self.stats_updated.emit(payload)
            elif msg_type is MessageType.PROCESS_LIST_RESULT:
                payload = Envelope[ProcessListResultPayload].model_validate(raw).payload
                self.latest_processes = payload
                self.processes_updated.emit(payload)
            elif msg_type is MessageType.FILES_LIST_RESULT:
                self.files_listed.emit(Envelope[FilesListResultPayload].model_validate(raw).payload)
            elif msg_type is MessageType.ERROR:
                payload = Envelope[ErrorPayload].model_validate(raw).payload
                self.error_received.emit(payload.code, payload.message)
        except ValidationError:
            logger.exception("agent sent a %s that does not match the schema", msg_type.value)

    # --- outgoing ----------------------------------------------------------

    async def request_processes(self, limit: int = 60, sort_by: str = "cpu") -> None:
        await self._ws_client.send(
            MessageType.PROCESS_LIST, ProcessListPayload(limit=limit, sort_by=sort_by)
        )

    async def request_files(self, path: str) -> None:
        await self._ws_client.send(MessageType.FILES_LIST, FilesListPayload(path=path))
