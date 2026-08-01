from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from pi_protocol import (
    PROTOCOL_VERSION,
    AuthOkPayload,
    AuthRejectedPayload,
    AuthRequestPayload,
    Capabilities,
    Envelope,
    MessageType,
)

from pi_agent.auth import is_rate_limited, record_failure, token_matches
from pi_agent.config import AgentConfig
from pi_agent.handlers import (
    clipboard,
    docker,
    files,
    gpio,
    network,
    power,
    processes,
    remote_desktop,
    services,
    stats,
    terminal,
)
from pi_agent.wire import Connection

logger = logging.getLogger("pi_agent.ws")

router = APIRouter()

Handler = Callable[[Connection, dict, AgentConfig], Awaitable[None]]

HANDLERS: dict[MessageType, Handler] = {
    MessageType.PROCESS_LIST: processes.handle,
    MessageType.PROCESS_KILL: processes.handle_kill,
    MessageType.FILES_LIST: files.handle_list,
    MessageType.FILES_CREATE: files.handle_create,
    MessageType.FILES_DELETE: files.handle_delete,
    MessageType.CHAT_SEND: clipboard.handle_send,
    MessageType.CLIPBOARD_PULL: clipboard.handle_pull,
    MessageType.SERVICE_LIST: services.handle_list,
    MessageType.SERVICE_ACTION: services.handle_action,
    MessageType.SERVICE_LOGS: services.handle_logs,
    MessageType.POWER_ACTION: power.handle,
    MessageType.GPIO_LIST: gpio.handle_list,
    MessageType.GPIO_WRITE: gpio.handle_write,
    MessageType.GPIO_RELEASE: gpio.handle_release,
    MessageType.DOCKER_LIST: docker.handle_list,
    MessageType.DOCKER_ACTION: docker.handle_action,
    MessageType.DOCKER_LOGS: docker.handle_logs,
    MessageType.NETWORK_INFO: network.handle,
    MessageType.TERMINAL_OPEN: terminal.handle_open,
    MessageType.TERMINAL_INPUT: terminal.handle_input,
    MessageType.TERMINAL_RESIZE: terminal.handle_resize,
    MessageType.TERMINAL_CLOSE: terminal.handle_close,
}


async def current_capabilities() -> Capabilities:
    """Probed per connection rather than cached at startup, so plugging in a
    display, logging into the desktop or starting the docker daemon takes effect
    on the next reconnect."""
    docker_ok, docker_detail = await docker.probe()
    vnc_ok, vnc_detail = await remote_desktop.probe()
    return Capabilities(
        clipboard=clipboard.detect() is not None,
        clipboard_detail=clipboard.describe(),
        systemd=services.is_available(),
        gpio=gpio.is_available(),
        gpio_detail=gpio.describe(),
        docker=docker_ok,
        docker_detail=docker_detail,
        terminal=terminal.is_available(),
        terminal_detail=terminal.describe(),
        vnc=vnc_ok,
        vnc_detail=vnc_detail,
        vnc_port=remote_desktop.VNC_PORT,
    )


async def _authenticate(websocket: WebSocket, conn: Connection, config: AgentConfig) -> bool:
    client_ip = conn.client_ip
    if is_rate_limited(client_ip):
        await websocket.close(code=4429, reason="too many auth failures")
        return False

    raw = await websocket.receive_json()
    try:
        envelope = Envelope[AuthRequestPayload].model_validate(raw)
    except ValidationError:
        record_failure(client_ip)
        await websocket.close(code=4400, reason="expected auth.request")
        return False

    if envelope.type != MessageType.AUTH_REQUEST:
        record_failure(client_ip)
        await websocket.close(code=4401, reason="auth.request must be first message")
        return False

    if not token_matches(config, envelope.payload.token):
        record_failure(client_ip)
        await conn.send(MessageType.AUTH_REJECTED, AuthRejectedPayload(reason="invalid token"))
        await websocket.close(code=4403, reason="invalid token")
        return False

    await conn.send(
        MessageType.AUTH_OK,
        AuthOkPayload(protocol_version=PROTOCOL_VERSION, capabilities=await current_capabilities()),
    )
    return True


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    config: AgentConfig = websocket.app.state.config
    await websocket.accept()
    conn = Connection(websocket)

    background: set[asyncio.Task] = set()
    try:
        if not await _authenticate(websocket, conn, config):
            return

        _spawn(background, stats.push_loop(conn, config.stats.interval_seconds))

        while True:
            raw = await websocket.receive_json()
            try:
                msg_type = MessageType(raw.get("type"))
            except ValueError:
                await conn.send_error(
                    "unknown_type", f"unrecognized message type: {raw.get('type')!r}", raw.get("id")
                )
                continue

            handler = HANDLERS.get(msg_type)
            if handler is None:
                await conn.send_error(
                    "not_implemented", f"no handler registered for {msg_type.value}", raw.get("id")
                )
                continue

            # Dispatch concurrently: collecting the process list takes on the
            # order of a second, and awaiting it inline would head-of-line block
            # every other request on this connection.
            _spawn(background, handler(conn, raw, config))
    except WebSocketDisconnect:
        logger.info("client disconnected: %s", conn.client_ip)
    finally:
        # The shell dies with the socket that opened it: a session left running
        # would keep the user's programs alive with nobody watching them.
        await terminal.close_for(conn)
        for task in background:
            task.cancel()


def _spawn(registry: set[asyncio.Task], coro) -> None:
    task = asyncio.create_task(coro)
    registry.add(task)
    task.add_done_callback(registry.discard)
    task.add_done_callback(_log_failure)


def _log_failure(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    if (error := task.exception()) is not None:
        logger.error("handler task failed: %r", error)
