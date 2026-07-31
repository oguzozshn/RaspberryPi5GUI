from __future__ import annotations

import asyncio
import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from pi_protocol import ChatMessagePayload, ChatSendPayload, Envelope, MessageType

from pi_agent.config import AgentConfig
from pi_agent.wire import Connection

logger = logging.getLogger("pi_agent.clipboard")

_TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class ClipboardTool:
    name: str
    write_cmd: list[str]
    read_cmd: list[str]


_WAYLAND = ClipboardTool(
    name="wl-copy (Wayland)",
    write_cmd=["wl-copy"],
    read_cmd=["wl-paste", "--no-newline"],
)
_X11 = ClipboardTool(
    name="xclip (X11)",
    write_cmd=["xclip", "-selection", "clipboard"],
    read_cmd=["xclip", "-selection", "clipboard", "-o"],
)


def detect() -> ClipboardTool | None:
    """Pick a clipboard backend, or None if this Pi has no graphical session.

    The agent runs as a systemd system service with a clean environment, so it
    only sees DISPLAY/WAYLAND_DISPLAY because install.sh puts them in the unit
    file. Raspberry Pi OS Bookworm on a Pi 5 defaults to Wayland, so that is
    checked first.
    """
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    wayland_display = os.environ.get("WAYLAND_DISPLAY")
    if runtime_dir and wayland_display and shutil.which("wl-copy"):
        socket = Path(runtime_dir) / wayland_display
        if socket.exists():
            return _WAYLAND

    if os.environ.get("DISPLAY") and shutil.which("xclip"):
        return _X11

    return None


def describe() -> str:
    tool = detect()
    if tool is not None:
        return tool.name
    if not shutil.which("wl-copy") and not shutil.which("xclip"):
        return "wl-clipboard/xclip kurulu degil"
    return "Pi'de aktif bir grafik oturumu bulunamadi"


async def write_text(text: str) -> tuple[bool, str]:
    tool = detect()
    if tool is None:
        return False, describe()

    try:
        process = await asyncio.create_subprocess_exec(
            *tool.write_cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(
            process.communicate(text.encode()), timeout=_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        return False, f"{tool.name} zaman asimina ugradi"
    except OSError as exc:
        return False, str(exc)

    if process.returncode != 0:
        return False, stderr.decode(errors="replace").strip() or f"{tool.name} hata dondu"
    return True, tool.name


async def read_text() -> tuple[bool, str]:
    tool = detect()
    if tool is None:
        return False, describe()

    try:
        process = await asyncio.create_subprocess_exec(
            *tool.read_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        return False, f"{tool.name} zaman asimina ugradi"
    except OSError as exc:
        return False, str(exc)

    if process.returncode != 0:
        # Both tools exit non-zero when the clipboard holds nothing pasteable.
        detail = stderr.decode(errors="replace").strip()
        return False, detail or "Pi'nin panosu bos"
    return True, stdout.decode(errors="replace")


# --- handlers ---------------------------------------------------------------


async def handle_send(conn: Connection, raw: dict, config: AgentConfig) -> None:
    try:
        envelope = Envelope[ChatSendPayload].model_validate(raw)
    except ValidationError as exc:
        await conn.send_error("bad_request", str(exc), raw.get("id"))
        return

    ok, detail = await write_text(envelope.payload.text)
    await conn.send(
        MessageType.CHAT_MESSAGE,
        ChatMessagePayload(
            text=envelope.payload.text,
            source="desktop",
            delivered_to_clipboard=ok,
            detail=detail,
        ),
        envelope.id,
    )


async def handle_pull(conn: Connection, raw: dict, config: AgentConfig) -> None:
    ok, result = await read_text()
    await conn.send(
        MessageType.CHAT_MESSAGE,
        ChatMessagePayload(
            text=result if ok else "",
            source="pi",
            delivered_to_clipboard=False,
            detail="" if ok else result,
        ),
        raw.get("id"),
    )
