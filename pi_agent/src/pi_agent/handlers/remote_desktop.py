from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("pi_agent.remote_desktop")

VNC_PORT = 5900

# Yoklama her kimlik dogrulamada calisiyor ve sunucu yoksa tam sureyi harciyor
# (kapali bir portta baglanti hemen reddedilmiyor). Hedef 127.0.0.1 oldugu icin
# calisan bir sunucu mikrosaniyelerde cevap verir; kisa tutmanin bedeli yok.
_TIMEOUT_SECONDS = 0.4


async def probe(port: int = VNC_PORT) -> tuple[bool, str]:
    """Is a VNC server actually serving this Pi's desktop?

    Checked by opening the port and reading the RFB banner rather than by asking
    systemd: wayvnc, RealVNC's server and x11vnc are all plausible here and the
    only thing the client cares about is that something speaks RFB.
    """
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", port), timeout=_TIMEOUT_SECONDS
        )
    except (OSError, asyncio.TimeoutError):
        return False, f"port {port} dinlenmiyor (VNC sunucusu kapali olabilir)"

    try:
        banner = await asyncio.wait_for(reader.read(12), timeout=_TIMEOUT_SECONDS)
    except (OSError, asyncio.TimeoutError):
        banner = b""
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:  # pragma: no cover - peer already gone
            pass

    text = banner.decode(errors="replace").strip()
    if not text.startswith("RFB"):
        return False, f"port {port} acik ama VNC gibi konusmuyor"
    return True, f"{text} (:{port})"
