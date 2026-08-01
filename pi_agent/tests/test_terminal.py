from __future__ import annotations

import asyncio
import sys

import pytest

from pi_agent.handlers import terminal

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="pty POSIX'e ozgu")


class _FakeConnection:
    """Toplar, gondermez: oturumun ciktisini incelemek icin."""

    client_ip = "test"

    def __init__(self) -> None:
        self.output: list[str] = []
        self.exits: list[tuple] = []

    async def send(self, msg_type, payload, reply_to=None) -> None:
        from pi_protocol import MessageType

        if msg_type is MessageType.TERMINAL_OUTPUT:
            self.output.append(payload.data)
        elif msg_type is MessageType.TERMINAL_EXIT:
            self.exits.append((payload.exit_code, payload.detail))

    async def send_error(self, code, message, reply_to=None) -> None:
        self.exits.append((code, message))


async def _wait_for(predicate, timeout: float = 10.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return False


def test_availability_is_reported_with_a_reason() -> None:
    assert terminal.is_available() is True
    assert terminal.describe().startswith("/"), "kabuk yolu gosterilmeli"


def test_shell_runs_a_command_and_streams_output() -> None:
    async def main() -> str:
        conn = _FakeConnection()
        session = terminal.Session(conn)  # type: ignore[arg-type]
        await session.start(cols=80, rows=24)
        try:
            session.write("echo PI_AGENT_TESTI\r")
            assert await _wait_for(lambda: "PI_AGENT_TESTI" in "".join(conn.output))
            return "".join(conn.output)
        finally:
            await session.close()

    output = asyncio.run(main())
    # Kabuk girdiyi yankiladigi icin metin iki kez gecer: komut satiri ve ciktisi.
    assert output.count("PI_AGENT_TESTI") >= 2


def test_exit_is_reported_when_the_shell_ends() -> None:
    async def main() -> list[tuple]:
        conn = _FakeConnection()
        session = terminal.Session(conn)  # type: ignore[arg-type]
        await session.start(cols=80, rows=24)
        try:
            session.write("exit\r")
            await _wait_for(lambda: bool(conn.exits))
            return conn.exits
        finally:
            await session.close()

    exits = asyncio.run(main())
    assert exits, "kabuk kapaninca terminal.exit gitmeli"
    assert "kabuk kapandi" in exits[0][1]


def test_resize_is_visible_to_the_shell() -> None:
    """Onemli: htop gibi programlar pencere boyutunu buradan ogreniyor."""

    async def main() -> str:
        conn = _FakeConnection()
        session = terminal.Session(conn)  # type: ignore[arg-type]
        await session.start(cols=80, rows=24)
        try:
            session.resize(cols=132, rows=40)
            await asyncio.sleep(0.3)
            conn.output.clear()
            session.write("tput cols\r")
            await _wait_for(lambda: "132" in "".join(conn.output))
            return "".join(conn.output)
        finally:
            await session.close()

    assert "132" in asyncio.run(main())


def test_close_kills_the_child_process_group() -> None:
    """Sekme kapaninca kabugun baslattigi programlar da gitmeli."""

    async def main() -> bool:
        conn = _FakeConnection()
        session = terminal.Session(conn)  # type: ignore[arg-type]
        await session.start(cols=80, rows=24)
        session.write("sleep 300 & echo BASLADI\r")
        await _wait_for(lambda: "BASLADI" in "".join(conn.output))
        pid = session._process.pid  # type: ignore[union-attr]

        await session.close()
        await asyncio.sleep(0.5)

        import subprocess

        remaining = subprocess.run(
            ["pgrep", "-g", str(pid)], capture_output=True, text=True
        ).stdout.strip()
        return remaining == ""

    assert asyncio.run(main()), "surec grubunda calisan bir sey kalmamali"
