"""Uygulama acilisi: kayitli ayar varken Pi'ye ulasilamazsa ne olmali.

Gercek kullanimda ortaya cikti: Pi arayuzden kapatildiktan sonra uygulamayi
yeniden baslatinca kurulum ekrani geliyordu - ayarlar kayitli oldugu hâlde, ve
'Yeniden Baglan' dugmesine ulasmanin yolu yoktu.
"""
from __future__ import annotations

import asyncio

import pytest
from PySide6.QtWidgets import QApplication

from desktop_app import main as main_module
from desktop_app.connection.ws_client import AuthResult, WsClient


class _Settings:
    def __init__(self, host: str = "192.168.0.42", token: str | None = "token") -> None:
        self.host = host
        self.port = 8765
        self.token = token


class _NoDialog:
    """Kurulum ekrani acilirsa test patlasin."""

    def __init__(self, *args, **kwargs) -> None:
        raise AssertionError("kurulum ekrani acilmamaliydi")


def _run(monkeypatch: pytest.MonkeyPatch, connect, settings: _Settings, qapp: QApplication):
    shown: list[dict] = []

    def fake_show(ws_client, host, port, token, connected=True):
        window = main_module.MainWindow(main_module.AppState(ws_client, host, port, token))
        shown.append({"connected": connected, "window": window})
        return window

    client = WsClient()
    monkeypatch.setattr(client, "connect", connect)
    monkeypatch.setattr(main_module, "_show_main_window", fake_show)
    monkeypatch.setattr(main_module, "SetupDialog", _NoDialog)

    asyncio.run(main_module._bootstrap(qapp, settings, client))
    return shown


def test_unreachable_pi_opens_the_panel_disconnected(monkeypatch: pytest.MonkeyPatch, qapp: QApplication) -> None:
    async def refused(host, port, token):
        raise OSError("[WinError 1225] uzak bilgisayar reddetti")

    shown = _run(monkeypatch, refused, _Settings(), qapp)

    assert len(shown) == 1
    assert shown[0]["connected"] is False, "sayfalar baglanti yokken istek atmamali"
    window = shown[0]["window"]
    assert not window._reconnect_button.isHidden(), "dugme erisilebilir olmali"
    assert "reddetti" in window._status_label.text(), "sebep gosterilmeli"


def test_reachable_pi_opens_the_panel_connected(monkeypatch: pytest.MonkeyPatch, qapp: QApplication) -> None:
    async def ok(host, port, token):
        return AuthResult.OK

    shown = _run(monkeypatch, ok, _Settings(), qapp)
    assert shown[0]["connected"] is True


def test_a_rejected_token_still_opens_the_setup_dialog(monkeypatch: pytest.MonkeyPatch, qapp: QApplication) -> None:
    """Yanlis token kendi kendine duzelmez; orada kurulum ekrani dogru cevap."""

    async def rejected(host, port, token):
        return AuthResult.REJECTED

    with pytest.raises(AssertionError, match="kurulum ekrani acilmamaliydi"):
        _run(monkeypatch, rejected, _Settings(), qapp)


def test_first_run_without_settings_opens_the_setup_dialog(monkeypatch: pytest.MonkeyPatch, qapp: QApplication) -> None:
    async def never_called(host, port, token):
        raise AssertionError("ayar yokken baglanmaya calisilmamali")

    with pytest.raises(AssertionError, match="kurulum ekrani acilmamaliydi"):
        _run(monkeypatch, never_called, _Settings(host="", token=None), qapp)
