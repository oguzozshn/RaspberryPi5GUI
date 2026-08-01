from __future__ import annotations

from pathlib import Path

import pytest

from pi_protocol import Capabilities

from desktop_app import vnc
from desktop_app.app_state import AppState
from desktop_app.connection.ws_client import WsClient
from desktop_app.ui.pages.dashboard_page import DashboardPage


# --- adres bicimi -----------------------------------------------------------


def test_standard_port_uses_the_display_form() -> None:
    """5900 = ekran 0. `host:5900` bazi istemcilerde 'ekran 5900' diye okunur ve
    59900. porta baglanmaya calisirlar."""
    assert vnc.address("100.83.133.94", 5900) == "100.83.133.94:0"


def test_other_ports_use_the_explicit_port_form() -> None:
    assert vnc.address("100.83.133.94", 5901) == "100.83.133.94::5901"


# --- istemci bulma ----------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_saved_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Testler gercek QSettings'e bakmasin."""
    monkeypatch.setattr(vnc, "saved_client", lambda: None)


def test_find_client_prefers_an_installed_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = tmp_path / "vncviewer.exe"
    fake.write_text("")
    monkeypatch.setattr(vnc, "_CANDIDATES", (tmp_path / "yok.exe", fake))

    assert vnc.find_client() == fake


def test_find_client_falls_back_to_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vnc, "_CANDIDATES", ())
    monkeypatch.setattr(vnc, "_search_roots", lambda: ())
    monkeypatch.setattr(vnc.shutil, "which", lambda name: r"C:\bin\vncviewer.exe")

    assert vnc.find_client() == Path(r"C:\bin\vncviewer.exe")


def test_find_client_searches_program_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Saticilar surumden surume klasor adini degistiriyor (RealVNC 7 'VNC
    Viewer', 8 'VNC Connect Viewer'), sabit yol listesi tek basina yetmez."""
    installed = tmp_path / "RealVNC" / "VNC Connect Viewer" / "vncviewer.exe"
    installed.parent.mkdir(parents=True)
    installed.write_text("")

    monkeypatch.setattr(vnc, "_CANDIDATES", ())
    monkeypatch.setattr(vnc, "_search_roots", lambda: (tmp_path,))
    monkeypatch.setattr(vnc.shutil, "which", lambda name: None)

    assert vnc.find_client() == installed


def test_a_remembered_client_wins_over_searching(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Kurulumsuz dagitilan istemciler herhangi bir klasorde olabilir; kullanici
    bir kez sectiginde arama devreye girmemeli."""
    chosen = tmp_path / "vncviewer64-1.16.2.exe"
    chosen.write_text("")
    monkeypatch.setattr(vnc, "saved_client", lambda: chosen)
    monkeypatch.setattr(vnc, "_CANDIDATES", ())
    monkeypatch.setattr(vnc, "_search_roots", lambda: ())

    assert vnc.find_client() == chosen


def test_a_remembered_client_that_vanished_is_ignored(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from desktop_app import settings as settings_module

    class _Settings:
        vnc_client_path = str(tmp_path / "silinmis.exe")

    monkeypatch.setattr(settings_module, "Settings", lambda: _Settings())
    assert vnc.saved_client() is None


def test_launch_without_a_client_explains_how_to_install(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vnc, "find_client", lambda: None)
    monkeypatch.setattr(vnc.QDesktopServices, "openUrl", staticmethod(lambda url: False))

    ok, detail = vnc.launch("100.83.133.94", 5900)
    assert not ok
    assert "winget install" in detail


def test_launch_passes_the_address_to_the_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = tmp_path / "vncviewer.exe"
    client.write_text("")
    calls: list[tuple] = []
    monkeypatch.setattr(vnc, "find_client", lambda: client)
    monkeypatch.setattr(
        vnc.QProcess, "startDetached", staticmethod(lambda exe, args: calls.append((exe, args)) or True)
    )

    ok, _ = vnc.launch("100.83.133.94", 5900)
    assert ok
    assert calls == [(str(client), ["100.83.133.94:0"])]


# --- dugme durumu -----------------------------------------------------------


def _state(qapp, **caps) -> AppState:
    client = WsClient()
    client.capabilities = Capabilities(**caps)
    return AppState(client, "100.83.133.94", 8765, "token")


def test_button_is_enabled_when_the_pi_serves_vnc(qapp) -> None:
    page = DashboardPage(_state(qapp, vnc=True, vnc_detail="RFB 003.008 (:5900)"))
    page._apply_vnc_capability()

    assert page._vnc_button.isEnabled()
    assert "RFB" in page._vnc_status.text()


def test_button_is_disabled_without_a_vnc_server(qapp) -> None:
    """Sunucu yokken dugmeyi acik birakmak, asla baglanamayan bir pencere acardi."""
    page = DashboardPage(_state(qapp, vnc=False, vnc_detail="port 5900 dinlenmiyor"))
    page._apply_vnc_capability()

    assert not page._vnc_button.isEnabled()
    assert "dinlenmiyor" in page._vnc_status.text()
