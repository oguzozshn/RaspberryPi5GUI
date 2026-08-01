from __future__ import annotations

import asyncio

import pytest
from PySide6.QtWidgets import QApplication

from desktop_app.app_state import AppState
from desktop_app.connection import ws_client as ws_client_module
from desktop_app.connection.ws_client import AuthResult, WsClient
from desktop_app.ui.main_window import MainWindow


class _FakeConnect:
    """Stands in for WsClient.connect: fails while the Pi is still booting,
    then succeeds."""

    def __init__(self, failures: int, result: AuthResult = AuthResult.OK) -> None:
        self.failures = failures
        self.result = result
        self.calls: list[tuple[str, int, str]] = []

    async def __call__(self, host: str, port: int, token: str) -> AuthResult:
        self.calls.append((host, port, token))
        if len(self.calls) <= self.failures:
            raise OSError("connection refused")
        return self.result


@pytest.fixture(autouse=True)
def _instant_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the retry schedule's shape but drop the waiting."""
    monkeypatch.setattr(ws_client_module, "_BACKOFF_SECONDS", (0, 0, 0, 0))
    monkeypatch.setattr(ws_client_module, "_BACKOFF_MAX_SECONDS", 0)


def _client(fake: _FakeConnect) -> WsClient:
    client = WsClient()
    client._credentials = ("192.168.0.42", 8765, "token")
    client.connect = fake  # type: ignore[method-assign]
    return client


# --- retry loop -------------------------------------------------------------


def test_reconnects_once_the_pi_comes_back() -> None:
    """The app's own reboot button guarantees a drop, so recovery cannot depend
    on the user restarting the application."""
    fake = _FakeConnect(failures=3)
    client = _client(fake)

    async def main() -> None:
        client._schedule_reconnect()
        await client._reconnect_task

    asyncio.run(main())
    assert len(fake.calls) == 4, "Pi acilana kadar denemeye devam etmeli"
    assert fake.calls[-1] == ("192.168.0.42", 8765, "token")


def test_every_attempt_is_reported(qapp: QApplication) -> None:
    fake = _FakeConnect(failures=2)
    client = _client(fake)
    attempts: list[int] = []
    client.reconnecting.connect(lambda attempt, delay: attempts.append(attempt))

    async def main() -> None:
        client._schedule_reconnect()
        await client._reconnect_task

    asyncio.run(main())
    assert attempts == [1, 2, 3], "her deneme arayuze bildirilmeli"


def test_a_rejected_token_stops_the_loop() -> None:
    """Retrying a wrong token forever would only feed the agent's rate limiter."""
    fake = _FakeConnect(failures=0, result=AuthResult.REJECTED)
    client = _client(fake)

    async def main() -> None:
        client._schedule_reconnect()
        await client._reconnect_task

    asyncio.run(main())
    assert len(fake.calls) == 1


def test_close_stops_the_retry_loop() -> None:
    fake = _FakeConnect(failures=1000)  # asla basarili olmaz
    client = _client(fake)

    async def main() -> tuple[int, int]:
        client._schedule_reconnect()
        await asyncio.sleep(0)
        await client.close()
        after_close = len(fake.calls)
        for _ in range(5):
            await asyncio.sleep(0)
        return after_close, len(fake.calls)

    after_close, later = asyncio.run(main())
    assert later == after_close, "kapatildiktan sonra yeni deneme yapilmamali"
    assert client._reconnect_task is None


def test_a_second_drop_does_not_start_a_parallel_loop() -> None:
    fake = _FakeConnect(failures=1)
    client = _client(fake)

    async def main() -> None:
        client._schedule_reconnect()
        first = client._reconnect_task
        client._schedule_reconnect()
        assert client._reconnect_task is first, "ikinci cagri yeni dongu acmamali"
        await first

    asyncio.run(main())
    assert len(fake.calls) == 2


# --- what the window shows --------------------------------------------------


def test_status_shows_retry_progress(app_state: AppState) -> None:
    window = MainWindow(app_state)
    window._on_connection_changed(False, "1006")
    assert "kesildi" in window._status_label.text()

    window._on_reconnecting(3, 4.0)
    assert "3. deneme" in window._status_label.text()
    assert "e67e22" in window._status_label.styleSheet()


def test_pages_refetch_after_a_reconnect(app_state: AppState, monkeypatch: pytest.MonkeyPatch) -> None:
    """Stale rows from before the reboot must not be left on screen."""
    window = MainWindow(app_state)
    started: list[int] = []
    monkeypatch.setattr(window, "start", lambda: started.append(1))

    window._on_connection_changed(True, "")
    assert started == [], "ilk baglantida sayfalari main.py zaten baslatiyor"

    window._on_connection_changed(False, "1006")
    window._on_connection_changed(True, "")
    assert started == [1], "kopmadan sonra geri donunce yeniden yuklenmeli"
