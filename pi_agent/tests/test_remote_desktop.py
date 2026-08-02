"""VNC yoklamasi.

Gercek kullanimda ortaya cikti: wayvnc yalnizca VPN adresine baglanmisken
arayuz 'port 5900 dinlenmiyor' diyordu - sunucu calisiyor oldugu halde. Sebep,
yoklamanin yalnizca 127.0.0.1'i denemesiydi.
"""
from __future__ import annotations

import asyncio
from collections import namedtuple

import psutil
import pytest

from pi_agent.handlers import remote_desktop

_Addr = namedtuple("_Addr", "ip port")
_Conn = namedtuple("_Conn", "status laddr")


def _connections(*entries):
    return lambda kind="tcp": [
        _Conn(status=psutil.CONN_LISTEN, laddr=_Addr(ip=ip, port=port)) for ip, port in entries
    ]


def _banner(expected_host: str | None, value: str | None):
    """Sadece beklenen adrese baglanildiginda banner dondurur."""

    async def fake(host: str, port: int) -> str | None:
        if expected_host is not None and host != expected_host:
            return None
        return value

    return fake


# --- dinleyen adresin bulunmasi ---------------------------------------------


def test_finds_the_bound_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(psutil, "net_connections", _connections(("100.83.133.94", 5900)))
    assert remote_desktop.listening_address(5900) == "100.83.133.94"


def test_returns_none_when_nothing_listens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(psutil, "net_connections", _connections(("0.0.0.0", 22)))
    assert remote_desktop.listening_address(5900) is None


def test_permission_errors_degrade_quietly(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_denied(kind="tcp"):
        raise psutil.AccessDenied()

    monkeypatch.setattr(psutil, "net_connections", raise_denied)
    assert remote_desktop.listening_address(5900) is None


# --- yoklama ----------------------------------------------------------------


def test_server_bound_to_one_interface_is_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """Asil regresyon: loopback sessizken bile sunucu bulunmali."""
    monkeypatch.setattr(psutil, "net_connections", _connections(("100.83.133.94", 5900)))
    monkeypatch.setattr(remote_desktop, "_read_banner", _banner("100.83.133.94", "RFB 003.008"))

    ok, detail = asyncio.run(remote_desktop.probe())
    assert ok
    assert "100.83.133.94:5900" in detail


def test_wildcard_binding_is_probed_over_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(psutil, "net_connections", _connections(("0.0.0.0", 5900)))
    monkeypatch.setattr(remote_desktop, "_read_banner", _banner("127.0.0.1", "RFB 003.008"))

    ok, detail = asyncio.run(remote_desktop.probe())
    assert ok
    assert "RFB 003.008" in detail


def test_nothing_listening_reports_the_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(psutil, "net_connections", _connections())
    monkeypatch.setattr(remote_desktop, "_read_banner", _banner(None, None))

    ok, detail = asyncio.run(remote_desktop.probe())
    assert not ok
    assert "dinlenmiyor" in detail


def test_a_non_vnc_service_on_the_port_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(psutil, "net_connections", _connections(("0.0.0.0", 5900)))
    monkeypatch.setattr(remote_desktop, "_read_banner", _banner("127.0.0.1", "HTTP/1.1 400"))

    ok, detail = asyncio.run(remote_desktop.probe())
    assert not ok
    assert "VNC gibi konusmuyor" in detail


def test_listening_but_silent_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(psutil, "net_connections", _connections(("0.0.0.0", 5900)))
    monkeypatch.setattr(remote_desktop, "_read_banner", _banner(None, None))

    ok, detail = asyncio.run(remote_desktop.probe())
    assert not ok
    assert "cevap vermiyor" in detail


def test_falls_back_to_loopback_when_psutil_is_blind(monkeypatch: pytest.MonkeyPatch) -> None:
    """psutil bakamazsa yoklama tamamen vazgecmemeli."""
    monkeypatch.setattr(remote_desktop, "listening_address", lambda port=5900: None)
    monkeypatch.setattr(remote_desktop, "_read_banner", _banner("127.0.0.1", "RFB 003.008"))

    ok, detail = asyncio.run(remote_desktop.probe())
    assert ok
    assert "RFB 003.008" in detail
