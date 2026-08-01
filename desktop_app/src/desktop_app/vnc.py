from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QProcess, QUrl
from PySide6.QtGui import QDesktopServices

# Windows'ta yaygin VNC istemcileri. Kurulum yollari sabit oldugu icin PATH'e
# guvenmek yetmiyor: hicbiri kendini PATH'e eklemiyor.
_CANDIDATES = (
    Path(r"C:\Program Files\RealVNC\VNC Viewer\vncviewer.exe"),
    Path(r"C:\Program Files (x86)\RealVNC\VNC Viewer\vncviewer.exe"),
    Path(r"C:\Program Files\TigerVNC\vncviewer.exe"),
    Path(r"C:\Program Files\uvnc bvba\UltraVNC\vncviewer.exe"),
    Path(r"C:\Program Files (x86)\TightVNC\tvnviewer.exe"),
)

INSTALL_HINT = "VNC istemcisi bulunamadi. Kurmak icin: winget install RealVNC.VNCViewer"


def find_client() -> Path | None:
    for candidate in _CANDIDATES:
        if candidate.is_file():
            return candidate
    for name in ("vncviewer", "tvnviewer"):
        if (found := shutil.which(name)) is not None:
            return Path(found)
    return None


def address(host: str, port: int) -> str:
    """VNC istemcilerinin ortak adres bicimi.

    5900, ekran 0 demek ve `host:0` her istemcide ayni sekilde anlasiliyor.
    Farkli bir portta ise iki nokta ust uste iki kez yazmak gerekiyor, cunku
    `host:5901` bazi istemcilerde 'ekran 5901' diye okunur.
    """
    return f"{host}:0" if port == 5900 else f"{host}::{port}"


def launch(host: str, port: int = 5900) -> tuple[bool, str]:
    target = address(host, port)

    client = find_client()
    if client is not None:
        if QProcess.startDetached(str(client), [target]):
            return True, f"{client.name} baslatildi: {target}"
        return False, f"{client.name} baslatilamadi"

    # Kurulu istemci bulunamadi: bazi istemciler vnc:// semasini kaydeder,
    # son care olarak isletim sistemine devret.
    if QDesktopServices.openUrl(QUrl(f"vnc://{host}:{port}")):
        return True, f"vnc://{host}:{port} sistem uzerinden acildi"
    return False, INSTALL_HINT
