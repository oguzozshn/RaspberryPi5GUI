from __future__ import annotations

import asyncio
import logging

import psutil

logger = logging.getLogger("pi_agent.remote_desktop")

VNC_PORT = 5900

# Yoklama her kimlik dogrulamada calisiyor ve kapali bir portta baglanti hemen
# reddedilmedigi icin tam sureyi harciyor. Hedef yerel oldugundan calisan bir
# sunucu mikrosaniyelerde cevap verir; kisa tutmanin bedeli yok.
_TIMEOUT_SECONDS = 0.4

_WILDCARD = {"0.0.0.0", "::", ""}


def listening_address(port: int = VNC_PORT) -> str | None:
    """Port dinleniyorsa baglandigi adresi dondurur.

    Sadece 127.0.0.1'e baglanmayi denemek yetmiyor: sunucu belirli bir arabirime
    baglanmis olabilir (ornegin yalnizca VPN adresine), o zaman loopback sessiz
    kalir ve 'VNC yok' deriz - halbuki calisiyordur. Gercekte bunu yasadik.
    """
    try:
        connections = psutil.net_connections(kind="tcp")
    except (psutil.AccessDenied, PermissionError, OSError):
        return None

    for connection in connections:
        if connection.status == psutil.CONN_LISTEN and connection.laddr.port == port:
            return connection.laddr.ip
    return None


async def _read_banner(host: str, port: int) -> str | None:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=_TIMEOUT_SECONDS
        )
    except (OSError, asyncio.TimeoutError):
        return None

    try:
        banner = await asyncio.wait_for(reader.read(12), timeout=_TIMEOUT_SECONDS)
    except (OSError, asyncio.TimeoutError):
        banner = b""
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:  # pragma: no cover - karsi taraf zaten gitti
            pass

    return banner.decode(errors="replace").strip()


async def probe(port: int = VNC_PORT) -> tuple[bool, str]:
    """Bu Pi'nin masaustunu sunan bir VNC sunucusu var mi?

    systemd'ye sormak yerine RFB banner'i okunuyor: wayvnc, RealVNC ve x11vnc
    hepsi olasi ve istemcinin umursadigi tek sey karsi tarafin RFB konusmasi.
    """
    address = listening_address(port)
    if address is None:
        # psutil bakamadi ya da hicbir sey dinlemiyor: yine de loopback'i dene,
        # cevap verirse sunucu vardir.
        banner = await _read_banner("127.0.0.1", port)
        if banner is None:
            return False, f"port {port} dinlenmiyor (VNC sunucusu kapali olabilir)"
        if not banner.startswith("RFB"):
            return False, f"port {port} acik ama VNC gibi konusmuyor"
        return True, f"{banner} (:{port})"

    target = "127.0.0.1" if address in _WILDCARD else address
    banner = await _read_banner(target, port)
    if banner is None:
        return False, f"{address}:{port} dinleniyor ama cevap vermiyor"
    if not banner.startswith("RFB"):
        return False, f"{address}:{port} acik ama VNC gibi konusmuyor"
    return True, f"{banner} ({address}:{port})"
