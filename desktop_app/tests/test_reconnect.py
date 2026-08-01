from __future__ import annotations

import asyncio

import pytest

from desktop_app.app_state import AppState
from desktop_app.connection.ws_client import AuthResult, WsClient
from desktop_app.ui.main_window import MainWindow


class _FakeConnect:
    def __init__(self, failures: int = 0, result: AuthResult = AuthResult.OK) -> None:
        self.failures = failures
        self.result = result
        self.calls: list[tuple[str, int, str]] = []

    async def __call__(self, host: str, port: int, token: str) -> AuthResult:
        self.calls.append((host, port, token))
        if len(self.calls) <= self.failures:
            raise OSError("connection refused")
        return self.result


def _client(fake: _FakeConnect) -> WsClient:
    client = WsClient()
    client._credentials = ("192.168.0.42", 8765, "token")
    client.connect = fake  # type: ignore[method-assign]
    return client


# --- client -----------------------------------------------------------------


def test_a_drop_never_retries_by_itself() -> None:
    """Yeniden baglanma kullanicinin karari: Pi genelde biri gidip guc dugmesine
    bastigi icin geri geliyor, kendi takvimiyle baglanan bir istemci ekrani
    kullanicinin secmedigi bir anda degistirirdi."""
    fake = _FakeConnect()
    client = _client(fake)
    dropped: list[str] = []
    client.disconnected.connect(dropped.append)

    async def main() -> None:
        client.disconnected.emit("1006")
        for _ in range(5):
            await asyncio.sleep(0)

    asyncio.run(main())
    assert dropped == ["1006"], "kopma bildirilmeli"
    assert fake.calls == [], "kendiliginden deneme olmamali"


def test_reconnect_reuses_the_last_good_credentials() -> None:
    fake = _FakeConnect()
    client = _client(fake)

    assert asyncio.run(client.reconnect()) is AuthResult.OK
    assert fake.calls == [("192.168.0.42", 8765, "token")], "kurulum ekrani tekrar sorulmamali"


def test_reconnect_propagates_the_failure() -> None:
    """Pi hala kapaliysa sebep cagirana ulasmali, sessizce yutulmamali."""
    fake = _FakeConnect(failures=1)
    client = _client(fake)

    with pytest.raises(OSError):
        asyncio.run(client.reconnect())
    assert len(fake.calls) == 1, "tek deneme"


def test_reconnect_without_a_previous_connection_is_an_error() -> None:
    client = WsClient()
    with pytest.raises(RuntimeError):
        asyncio.run(client.reconnect())


def test_app_state_reconnect_raises_on_a_rejected_token(app_state: AppState, monkeypatch: pytest.MonkeyPatch) -> None:
    async def rejected() -> AuthResult:
        return AuthResult.REJECTED

    monkeypatch.setattr(app_state._ws_client, "reconnect", rejected)
    with pytest.raises(RuntimeError):
        asyncio.run(app_state.reconnect())


# --- window -----------------------------------------------------------------


def test_button_appears_only_while_disconnected(app_state: AppState) -> None:
    window = MainWindow(app_state)
    assert window._reconnect_button.isHidden()

    window._on_connection_changed(False, "1006")
    assert not window._reconnect_button.isHidden()
    assert window._reconnect_button.isEnabled()
    assert "kesildi" in window._status_label.text()

    window._on_connection_changed(True, "")
    assert window._reconnect_button.isHidden()


def test_failed_attempt_leaves_the_button_usable(app_state: AppState) -> None:
    window = MainWindow(app_state)
    window._on_connection_changed(False, "1006")

    window._reconnect()  # calisan event loop yok; schedule() coroutine'i birakir
    assert not window._reconnect_button.isEnabled(), "deneme sirasinda tekrar basilamamali"

    window._on_reconnect_failed(OSError("Pi hala kapali"))
    assert "Baglanilamadi" in window._status_label.text()
    assert "Pi hala kapali" in window._status_label.text()
    assert window._reconnect_button.isEnabled(), "tekrar denenebilmeli"


def test_pages_refetch_after_a_successful_reconnect(app_state: AppState, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pi gidip gelirken ekranda kalanlar bayat; capabilities de el sikismada
    yeniden okundu."""
    window = MainWindow(app_state)
    started: list[int] = []
    monkeypatch.setattr(window, "start", lambda: started.append(1))

    window._on_connection_changed(True, "")
    assert started == [], "ilk baglantida sayfalari main.py zaten baslatiyor"

    window._on_connection_changed(False, "1006")
    window._on_connection_changed(True, "")
    assert started == [1]
