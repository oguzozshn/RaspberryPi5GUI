from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from desktop_app.app_state import AppState
from desktop_app.async_utils import schedule
from desktop_app.connection.file_client import FileClient
from desktop_app.ui.pages.chat_page import ChatPage
from desktop_app.ui.pages.dashboard_page import DashboardPage
from desktop_app.ui.pages.docker_page import DockerPage
from desktop_app.ui.pages.files_page import FilesPage
from desktop_app.ui.pages.network_page import NetworkPage
from desktop_app.ui.pages.power_page import PowerPage
from desktop_app.ui.pages.services_page import ServicesPage

_SIDEBAR = ["Dashboard", "Sohbet", "Dosyalar", "Servisler", "Guc & GPIO", "Docker", "Ag"]


class MainWindow(QMainWindow):
    """Sidebar + stacked-pages shell."""

    def __init__(self, app_state: AppState) -> None:
        super().__init__()
        self.setWindowTitle("Raspberry Pi 5 Kontrol Paneli")
        self.resize(1050, 700)

        self._app_state = app_state
        self._status_label = QLabel()
        self._was_disconnected = False

        # Retrying is explicit: the Pi usually comes back because someone walked
        # over and pressed its power button, and a client reconnecting on its own
        # schedule would redraw the screen at a moment the user did not choose.
        self._reconnect_button = QPushButton("Yeniden Baglan")
        self._reconnect_button.clicked.connect(self._reconnect)
        self._reconnect_button.hide()

        self._set_connected(True)
        app_state.connection_changed.connect(self._on_connection_changed)

        file_client = FileClient(app_state.host, app_state.port, app_state.token)
        self._dashboard = DashboardPage(app_state)
        self._chat = ChatPage(app_state)
        self._files = FilesPage(app_state, file_client)
        self._services = ServicesPage(app_state)
        self._power = PowerPage(app_state)
        self._docker = DockerPage(app_state)
        self._network = NetworkPage(app_state)
        self._pages = [
            self._dashboard,
            self._chat,
            self._files,
            self._services,
            self._power,
            self._docker,
            self._network,
        ]

        pages = QStackedWidget()
        for page in self._pages:
            pages.addWidget(page)

        sidebar = QListWidget()
        sidebar.addItems(_SIDEBAR)
        sidebar.setCurrentRow(0)
        sidebar.setMaximumWidth(160)
        sidebar.currentRowChanged.connect(pages.setCurrentIndex)

        status_row = QHBoxLayout()
        status_row.addWidget(self._status_label)
        status_row.addWidget(self._reconnect_button)
        status_row.addStretch(1)

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.addLayout(status_row)
        body = QHBoxLayout()
        body.addWidget(sidebar)
        body.addWidget(pages, stretch=1)
        outer.addLayout(body)
        self.setCentralWidget(central)

    def start(self) -> None:
        """Kick off the pages' initial requests once a running event loop exists."""
        for page in self._pages:
            page.start()

    def _reconnect(self) -> None:
        self._reconnect_button.setEnabled(False)
        self._status_label.setText("… Yeniden baglaniliyor")
        self._status_label.setStyleSheet("color: #e67e22;")
        schedule(self._app_state.reconnect(), self._on_reconnect_failed)

    def _on_reconnect_failed(self, error: BaseException) -> None:
        self._status_label.setText(f"○ Baglanilamadi ({error})")
        self._status_label.setStyleSheet("color: #c0392b;")
        self._reconnect_button.setEnabled(True)

    def _on_connection_changed(self, connected: bool, reason: str = "") -> None:
        self._set_connected(connected, reason)
        self._reconnect_button.setVisible(not connected)
        self._reconnect_button.setEnabled(not connected)
        if not connected:
            self._was_disconnected = True
            return
        if self._was_disconnected:
            # Back after a drop - typically a reboot this app asked for. Every
            # page is holding data from before the Pi went away, and the
            # handshake has just re-read capabilities, so redo the initial
            # fetches instead of leaving a screen full of stale rows.
            self._was_disconnected = False
            self.start()

    def _set_connected(self, connected: bool, reason: str = "") -> None:
        if connected:
            self._status_label.setText(f"● Baglandi: {self._app_state.host}:{self._app_state.port}")
            self._status_label.setStyleSheet("color: #27ae60;")
        else:
            self._status_label.setText(f"○ Baglanti kesildi ({reason or 'bilinmeyen sebep'})")
            self._status_label.setStyleSheet("color: #c0392b;")
