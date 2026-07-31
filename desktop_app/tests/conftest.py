from __future__ import annotations

import os

# Must be set before the first QApplication is constructed, otherwise Qt tries
# to open real windows on a machine that may have no interactive session.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from pi_protocol import Capabilities

from desktop_app.app_state import AppState
from desktop_app.connection.ws_client import WsClient


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def app_state(qapp: QApplication) -> AppState:
    client = WsClient()
    client.capabilities = Capabilities(
        clipboard=True,
        clipboard_detail="wl-copy (Wayland)",
        systemd=True,
        gpio=True,
        gpio_detail="pinctrl-rp1 (/dev/gpiochip4)",
    )
    return AppState(client, "192.168.1.42", 8765, "token")


@pytest.fixture
def bare_app_state(qapp: QApplication) -> AppState:
    """A Pi with no graphical session, no systemd and no GPIO - the degraded case."""
    client = WsClient()
    client.capabilities = Capabilities(
        clipboard=False,
        clipboard_detail="Pi'de aktif bir grafik oturumu bulunamadi",
        systemd=False,
        gpio=False,
        gpio_detail="lgpio kullanilamiyor: No module named 'lgpio'",
    )
    return AppState(client, "192.168.1.42", 8765, "token")
