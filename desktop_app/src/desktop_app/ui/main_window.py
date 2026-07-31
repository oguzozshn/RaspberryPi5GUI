from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from desktop_app.app_state import AppState
from desktop_app.connection.file_client import FileClient
from desktop_app.ui.pages.dashboard_page import DashboardPage
from desktop_app.ui.pages.files_page import FilesPage


class MainWindow(QMainWindow):
    """Sidebar + stacked-pages shell. Chat, Services, Power/GPIO and
    Docker/Network sections arrive in later phases."""

    def __init__(self, app_state: AppState) -> None:
        super().__init__()
        self.setWindowTitle("Raspberry Pi 5 Kontrol Paneli")
        self.resize(1050, 700)

        self._app_state = app_state
        self._status_label = QLabel()
        self._set_connected(True)
        app_state.connection_changed.connect(self._set_connected)

        file_client = FileClient(app_state.host, app_state.port, app_state.token)
        self._dashboard = DashboardPage(app_state)
        self._files = FilesPage(app_state, file_client)

        pages = QStackedWidget()
        pages.addWidget(self._dashboard)
        pages.addWidget(self._files)

        sidebar = QListWidget()
        sidebar.addItems(["Dashboard", "Dosyalar"])
        sidebar.setCurrentRow(0)
        sidebar.setMaximumWidth(160)
        sidebar.currentRowChanged.connect(pages.setCurrentIndex)

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.addWidget(self._status_label)
        body = QHBoxLayout()
        body.addWidget(sidebar)
        body.addWidget(pages, stretch=1)
        outer.addLayout(body)
        self.setCentralWidget(central)

    def start(self) -> None:
        """Kick off the pages' initial requests once a running event loop exists."""
        self._dashboard.start()
        self._files.start()

    def _set_connected(self, connected: bool, reason: str = "") -> None:
        if connected:
            self._status_label.setText(f"● Baglandi: {self._app_state.host}:{self._app_state.port}")
            self._status_label.setStyleSheet("color: #27ae60;")
        else:
            self._status_label.setText(f"○ Baglanti kesildi ({reason or 'bilinmeyen sebep'})")
            self._status_label.setStyleSheet("color: #c0392b;")
