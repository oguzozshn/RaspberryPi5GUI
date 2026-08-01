from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal
from pydantic import BaseModel, ValidationError

from pi_protocol import (
    Capabilities,
    ChatMessagePayload,
    ChatSendPayload,
    ClipboardPullPayload,
    DockerActionPayload,
    DockerActionResultPayload,
    DockerListPayload,
    DockerListResultPayload,
    DockerLogsPayload,
    DockerLogsResultPayload,
    Envelope,
    ErrorPayload,
    FilesListPayload,
    FilesListResultPayload,
    GpioListPayload,
    GpioListResultPayload,
    GpioReleasePayload,
    GpioReleaseResultPayload,
    GpioWritePayload,
    GpioWriteResultPayload,
    MessageType,
    NetworkInfoPayload,
    NetworkInfoResultPayload,
    PowerActionPayload,
    PowerActionResultPayload,
    ProcessKillPayload,
    ProcessKillResultPayload,
    ProcessListPayload,
    ProcessListResultPayload,
    ServiceActionPayload,
    ServiceActionResultPayload,
    ServiceListPayload,
    ServiceListResultPayload,
    ServiceLogsPayload,
    ServiceLogsResultPayload,
    StatsUpdatePayload,
)

from desktop_app.connection.ws_client import WsClient

logger = logging.getLogger("desktop_app.app_state")

# Incoming type -> (payload model, signal attribute, cache attribute or None)
_ROUTES: list[tuple[MessageType, type[BaseModel], str, str | None]] = [
    (MessageType.STATS_UPDATE, StatsUpdatePayload, "stats_updated", "latest_stats"),
    (MessageType.PROCESS_LIST_RESULT, ProcessListResultPayload, "processes_updated", "latest_processes"),
    (MessageType.PROCESS_KILL_RESULT, ProcessKillResultPayload, "process_killed", None),
    (MessageType.FILES_LIST_RESULT, FilesListResultPayload, "files_listed", None),
    (MessageType.CHAT_MESSAGE, ChatMessagePayload, "chat_message_received", None),
    (MessageType.SERVICE_LIST_RESULT, ServiceListResultPayload, "services_listed", None),
    (MessageType.SERVICE_ACTION_RESULT, ServiceActionResultPayload, "service_action_done", None),
    (MessageType.SERVICE_LOGS_RESULT, ServiceLogsResultPayload, "service_logs_received", None),
    (MessageType.POWER_ACTION_RESULT, PowerActionResultPayload, "power_action_done", None),
    (MessageType.GPIO_LIST_RESULT, GpioListResultPayload, "gpio_listed", "latest_gpio"),
    (MessageType.GPIO_WRITE_RESULT, GpioWriteResultPayload, "gpio_write_done", None),
    (MessageType.GPIO_RELEASE_RESULT, GpioReleaseResultPayload, "gpio_release_done", None),
    (MessageType.DOCKER_LIST_RESULT, DockerListResultPayload, "containers_listed", None),
    (MessageType.DOCKER_ACTION_RESULT, DockerActionResultPayload, "container_action_done", None),
    (MessageType.DOCKER_LOGS_RESULT, DockerLogsResultPayload, "container_logs_received", None),
    (MessageType.NETWORK_INFO_RESULT, NetworkInfoResultPayload, "network_info_received", "latest_network"),
]


class AppState(QObject):
    """Single source of domain truth for the UI. Parses envelopes off WsClient,
    keeps the latest values so a page opened mid-session can render immediately,
    and re-emits them as typed signals. Pages talk to this, never to the socket."""

    stats_updated = Signal(StatsUpdatePayload)
    processes_updated = Signal(ProcessListResultPayload)
    process_killed = Signal(ProcessKillResultPayload)
    files_listed = Signal(FilesListResultPayload)
    chat_message_received = Signal(ChatMessagePayload)
    services_listed = Signal(ServiceListResultPayload)
    service_action_done = Signal(ServiceActionResultPayload)
    service_logs_received = Signal(ServiceLogsResultPayload)
    power_action_done = Signal(PowerActionResultPayload)
    gpio_listed = Signal(GpioListResultPayload)
    gpio_write_done = Signal(GpioWriteResultPayload)
    gpio_release_done = Signal(GpioReleaseResultPayload)
    containers_listed = Signal(DockerListResultPayload)
    container_action_done = Signal(DockerActionResultPayload)
    container_logs_received = Signal(DockerLogsResultPayload)
    network_info_received = Signal(NetworkInfoResultPayload)
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
        self.latest_gpio: GpioListResultPayload | None = None
        self.latest_network: NetworkInfoResultPayload | None = None

        ws_client.message_received.connect(self._on_message)
        ws_client.disconnected.connect(lambda reason: self.connection_changed.emit(False, reason))
        ws_client.connected.connect(lambda: self.connection_changed.emit(True, ""))

    @property
    def capabilities(self) -> Capabilities:
        return self._ws_client.capabilities

    # --- incoming ----------------------------------------------------------

    def _on_message(self, raw: dict) -> None:
        try:
            msg_type = MessageType(raw.get("type"))
        except ValueError:
            logger.warning("unknown message type from agent: %r", raw.get("type"))
            return

        if msg_type is MessageType.ERROR:
            try:
                error = Envelope[ErrorPayload].model_validate(raw).payload
            except ValidationError:
                logger.exception("malformed error envelope")
                return
            self.error_received.emit(error.code, error.message)
            return

        for route_type, model, signal_name, cache_name in _ROUTES:
            if route_type is not msg_type:
                continue
            try:
                payload = Envelope[model].model_validate(raw).payload
            except ValidationError:
                logger.exception("agent sent a %s that does not match the schema", msg_type.value)
                return
            if cache_name is not None:
                setattr(self, cache_name, payload)
            getattr(self, signal_name).emit(payload)
            return

    # --- outgoing ----------------------------------------------------------

    async def request_processes(self, limit: int = 60, sort_by: str = "cpu") -> None:
        await self._ws_client.send(
            MessageType.PROCESS_LIST, ProcessListPayload(limit=limit, sort_by=sort_by)
        )

    async def kill_process(self, pid: int, force: bool = False) -> None:
        await self._ws_client.send(MessageType.PROCESS_KILL, ProcessKillPayload(pid=pid, force=force))

    async def request_files(self, path: str) -> None:
        await self._ws_client.send(MessageType.FILES_LIST, FilesListPayload(path=path))

    async def send_chat(self, text: str) -> None:
        await self._ws_client.send(MessageType.CHAT_SEND, ChatSendPayload(text=text))

    async def pull_clipboard(self) -> None:
        await self._ws_client.send(MessageType.CLIPBOARD_PULL, ClipboardPullPayload())

    async def request_services(self, pattern: str = "") -> None:
        await self._ws_client.send(MessageType.SERVICE_LIST, ServiceListPayload(pattern=pattern))

    async def service_action(self, unit: str, action: str) -> None:
        await self._ws_client.send(
            MessageType.SERVICE_ACTION, ServiceActionPayload(unit=unit, action=action)
        )

    async def request_service_logs(self, unit: str, lines: int = 200) -> None:
        await self._ws_client.send(
            MessageType.SERVICE_LOGS, ServiceLogsPayload(unit=unit, lines=lines)
        )

    async def power_action(self, action: str) -> None:
        await self._ws_client.send(MessageType.POWER_ACTION, PowerActionPayload(action=action))

    async def request_gpio(self) -> None:
        await self._ws_client.send(MessageType.GPIO_LIST, GpioListPayload())

    async def write_gpio(self, bcm: int, value: int) -> None:
        await self._ws_client.send(MessageType.GPIO_WRITE, GpioWritePayload(bcm=bcm, value=value))

    async def release_gpio(self, bcm: int) -> None:
        await self._ws_client.send(MessageType.GPIO_RELEASE, GpioReleasePayload(bcm=bcm))

    async def request_containers(self, include_stopped: bool = True) -> None:
        await self._ws_client.send(
            MessageType.DOCKER_LIST, DockerListPayload(include_stopped=include_stopped)
        )

    async def container_action(self, container: str, action: str) -> None:
        await self._ws_client.send(
            MessageType.DOCKER_ACTION, DockerActionPayload(container=container, action=action)
        )

    async def request_container_logs(self, container: str, lines: int = 200) -> None:
        await self._ws_client.send(
            MessageType.DOCKER_LOGS, DockerLogsPayload(container=container, lines=lines)
        )

    async def request_network_info(self) -> None:
        await self._ws_client.send(MessageType.NETWORK_INFO, NetworkInfoPayload())
