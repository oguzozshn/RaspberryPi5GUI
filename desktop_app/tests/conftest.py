from __future__ import annotations

import os

# Must be set before the first QApplication is constructed, otherwise Qt tries
# to open real windows on a machine that may have no interactive session.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from desktop_app.app_state import AppState
from desktop_app.connection.ws_client import WsClient


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def app_state(qapp: QApplication) -> AppState:
    return AppState(WsClient(), "192.168.1.42", 8765, "token")
