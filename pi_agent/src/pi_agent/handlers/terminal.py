from __future__ import annotations

import asyncio
import codecs
import logging
import os
import shutil
import signal

from pydantic import ValidationError

from pi_protocol import (
    Envelope,
    MessageType,
    TerminalExitPayload,
    TerminalInputPayload,
    TerminalOpenPayload,
    TerminalOutputPayload,
    TerminalResizePayload,
    TerminalScreenPayload,
)

from pi_agent.config import AgentConfig
from pi_agent.wire import Connection

logger = logging.getLogger("pi_agent.terminal")

# pty/termios are POSIX-only; the agent still has to import on a Windows dev box.
try:  # noqa: SIM105
    import fcntl
    import pty
    import struct
    import termios
except ImportError:  # pragma: no cover - only hit off-Linux
    fcntl = pty = struct = termios = None  # type: ignore[assignment]

_READ_BYTES = 8192
_MAX_COLS, _MAX_ROWS = 500, 200

# Cizim modunda kareler bu araliktan sik gonderilmez (saniyede ~20 kare).
_RENDER_INTERVAL_SECONDS = 0.05

# Bir baglantinin acabilecegi kabuk sayisi. Sekme acmak ucuz gorunur ama her biri
# Pi'de gercek bir surec; sinirsiz birakmak tek bir istemcinin makineyi
# doldurmasina izin vermek olurdu.
_MAX_SESSIONS = 8

# (baglanti, oturum kimligi) -> Session. Bir baglantida birden fazla kabuk
# olabilir (istemcideki sekmeler), ama hepsi o sokete bagli: soket dustugunde
# hicbiri arkada kalmaz.
_sessions: dict[tuple[int, str], "Session"] = {}


def is_available() -> bool:
    return pty is not None and shutil.which(_shell_path()) is not None


def describe() -> str:
    if pty is None:
        return "pty bu isletim sisteminde yok"
    shell = _shell_path()
    if shutil.which(shell) is None:
        return f"kabuk bulunamadi: {shell}"
    return shell


def _shell_path() -> str:
    """The account's own login shell, so the prompt and aliases match what the
    user gets over SSH."""
    shell = os.environ.get("SHELL")
    if not shell:
        try:
            import pwd

            shell = pwd.getpwuid(os.getuid()).pw_shell
        except Exception:  # noqa: BLE001 - fall through to a sane default
            shell = ""
    return shell or "/bin/bash"


def _clamp(cols: int, rows: int) -> tuple[int, int]:
    return max(1, min(cols, _MAX_COLS)), max(1, min(rows, _MAX_ROWS))


class Session:
    """A shell attached to a pseudo-terminal, streamed over the control channel."""

    def __init__(self, conn: Connection, rendered: bool = False, session_id: str = "") -> None:
        self._conn = conn
        self._session_id = session_id
        self._master_fd: int | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None
        # Output is bytes and a read can split a multi-byte character in half;
        # an incremental decoder holds the tail until the rest arrives.
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

        # Cizim modu: ekrani burada tutup hazir satirlar gonderiyoruz, boylece
        # tarayici istemcisinin bir ANSI yorumlayicisi tasimasi gerekmiyor.
        self._rendered = rendered
        self._screen = None
        self._stream = None
        self._flush_task: asyncio.Task | None = None

    async def start(self, cols: int, rows: int) -> None:
        assert pty is not None
        cols, rows = _clamp(cols, rows)
        if self._rendered:
            import pyte  # noqa: PLC0415 - yalnizca cizim modunda gerekli

            self._screen = pyte.Screen(cols, rows)
            self._stream = pyte.Stream(self._screen)
        master_fd, slave_fd = pty.openpty()
        self._master_fd = master_fd
        _set_winsize(master_fd, cols, rows)

        env = dict(os.environ)
        env["TERM"] = "xterm-256color"
        env["COLUMNS"], env["LINES"] = str(cols), str(rows)

        self._process = await asyncio.create_subprocess_exec(
            _shell_path(),
            "-l",
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=env,
            cwd=os.path.expanduser("~"),
            # Own session + controlling terminal, so job control works and
            # Ctrl+C reaches the foreground program instead of the agent.
            start_new_session=True,
        )
        os.close(slave_fd)
        self._reader_task = asyncio.create_task(self._pump())
        logger.info("terminal session started for %s", self._conn.client_ip)

    async def _pump(self) -> None:
        assert self._master_fd is not None
        loop = asyncio.get_running_loop()
        while True:
            try:
                data = await loop.run_in_executor(None, _read, self._master_fd)
            except OSError:
                break  # slave side closed - the shell is gone
            if not data:
                break
            text = self._decoder.decode(data)
            if not text:
                continue
            if self._rendered:
                self._stream.feed(text)
                self._schedule_flush()
            else:
                await self._conn.send(
                    MessageType.TERMINAL_OUTPUT,
                    TerminalOutputPayload(data=text, session_id=self._session_id),
                )

        code = None
        if self._process is not None:
            try:
                code = await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                code = None
        await self._safe_send_exit(code, "kabuk kapandi")

    def _schedule_flush(self) -> None:
        """Ekrani hemen degil, kisa bir gecikmeyle gonder.

        'cat buyukdosya' saniyede yuzlerce parca uretir; her parcada 24 satirlik
        ekrani yollamak telefonu da baglantiyi da bosuna yorar. Gecikme kadar
        biriktirip tek kare gondermek hem ucuz hem gozle ayni.
        """
        if self._flush_task is not None and not self._flush_task.done():
            return
        self._flush_task = asyncio.create_task(self._flush_after_delay())

    async def _flush_after_delay(self) -> None:
        await asyncio.sleep(_RENDER_INTERVAL_SECONDS)
        await self.send_screen()

    async def send_screen(self) -> None:
        if self._screen is None:
            return
        payload = TerminalScreenPayload(
            lines=[line.rstrip() for line in self._screen.display],
            cursor_row=self._screen.cursor.y,
            cursor_col=self._screen.cursor.x,
            session_id=self._session_id,
        )
        try:
            await self._conn.send(MessageType.TERMINAL_SCREEN, payload)
        except Exception:  # noqa: BLE001 - istemci gitmis olabilir
            pass

    async def _safe_send_exit(self, code: int | None, detail: str) -> None:
        try:
            await self._conn.send(
                MessageType.TERMINAL_EXIT,
                TerminalExitPayload(exit_code=code, detail=detail, session_id=self._session_id),
            )
        except Exception:  # noqa: BLE001 - client may already be gone
            pass

    def write(self, data: str) -> None:
        if self._master_fd is None:
            return
        try:
            os.write(self._master_fd, data.encode())
        except OSError as exc:
            logger.debug("terminal write failed: %s", exc)

    def resize(self, cols: int, rows: int) -> None:
        if self._master_fd is None:
            return
        cols, rows = _clamp(cols, rows)
        _set_winsize(self._master_fd, cols, rows)
        if self._screen is not None:
            self._screen.resize(rows, cols)

    async def close(self) -> None:
        if self._flush_task is not None:
            self._flush_task.cancel()
        if self._reader_task is not None:
            self._reader_task.cancel()
        if self._process is not None and self._process.returncode is None:
            try:
                # The whole process group: a shell that started `sleep` should
                # not leave it running after the tab closes.
                os.killpg(os.getpgid(self._process.pid), signal.SIGHUP)
            except (ProcessLookupError, PermissionError):
                pass
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None


def _read(fd: int) -> bytes:
    try:
        return os.read(fd, _READ_BYTES)
    except OSError:
        return b""


def _set_winsize(fd: int, cols: int, rows: int) -> None:
    if fcntl is None or termios is None or struct is None:
        return
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except OSError as exc:  # pragma: no cover - very unusual
        logger.debug("winsize failed: %s", exc)


# --- handlers ---------------------------------------------------------------


async def handle_open(conn: Connection, raw: dict, config: AgentConfig) -> None:
    try:
        envelope = Envelope[TerminalOpenPayload].model_validate(raw)
    except ValidationError as exc:
        await conn.send_error("bad_request", str(exc), raw.get("id"))
        return

    if not is_available():
        await conn.send_error("not_available", describe(), envelope.id)
        return

    session_id = envelope.payload.session_id
    # Ayni kimlikle tekrar acmak eskisini degistirir; farkli kimlik yeni sekme.
    await _close_session(conn, session_id)

    if _session_count(conn) >= _MAX_SESSIONS:
        await conn.send_error(
            "too_many_sessions", f"en fazla {_MAX_SESSIONS} terminal acilabilir", envelope.id
        )
        return

    session = Session(conn, rendered=envelope.payload.rendered, session_id=session_id)
    try:
        await session.start(envelope.payload.cols, envelope.payload.rows)
    except OSError as exc:
        await conn.send_error("terminal_failed", str(exc), envelope.id)
        return
    _sessions[(id(conn), session_id)] = session


async def handle_input(conn: Connection, raw: dict, config: AgentConfig) -> None:
    try:
        envelope = Envelope[TerminalInputPayload].model_validate(raw)
    except ValidationError as exc:
        await conn.send_error("bad_request", str(exc), raw.get("id"))
        return

    session = _sessions.get((id(conn), envelope.payload.session_id))
    if session is None:
        await conn.send_error("not_open", "terminal oturumu acik degil", envelope.id)
        return
    session.write(envelope.payload.data)


async def handle_resize(conn: Connection, raw: dict, config: AgentConfig) -> None:
    try:
        envelope = Envelope[TerminalResizePayload].model_validate(raw)
    except ValidationError as exc:
        await conn.send_error("bad_request", str(exc), raw.get("id"))
        return

    session = _sessions.get((id(conn), envelope.payload.session_id))
    if session is not None:
        session.resize(envelope.payload.cols, envelope.payload.rows)


async def handle_close(conn: Connection, raw: dict, config: AgentConfig) -> None:
    try:
        envelope = Envelope[TerminalClosePayload].model_validate(raw)
    except ValidationError:
        await close_for(conn)  # kimlik okunamadiysa en guvenlisi hepsini kapatmak
        return
    await _close_session(conn, envelope.payload.session_id)


def _session_count(conn: Connection) -> int:
    return sum(1 for conn_id, _ in _sessions if conn_id == id(conn))


async def _close_session(conn: Connection, session_id: str) -> None:
    session = _sessions.pop((id(conn), session_id), None)
    if session is not None:
        await session.close()


async def close_for(conn: Connection) -> None:
    """Soket dustugunde cagrilir: o baglantinin butun kabuklari kapanir,
    hicbiri arkada sahipsiz kalmaz."""
    for key in [key for key in _sessions if key[0] == id(conn)]:
        session = _sessions.pop(key, None)
        if session is not None:
            await session.close()
