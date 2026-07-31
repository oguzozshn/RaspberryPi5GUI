from __future__ import annotations

from PySide6.QtWidgets import QApplication, QListWidget

from desktop_app.app_state import AppState
from desktop_app.connection.file_client import FileClient
from desktop_app.connection.ws_client import WsClient
from desktop_app.ui.main_window import MainWindow
from desktop_app.ui.pages.dashboard_page import DashboardPage
from desktop_app.ui.pages.files_page import FilesPage
from desktop_app.ui.setup_dialog import SetupDialog


def test_setup_dialog_constructs(qapp: QApplication) -> None:
    dialog = SetupDialog(WsClient())
    assert dialog.windowTitle() == "Raspberry Pi Baglantisi"
    assert dialog.save_button.isEnabled() is False


def test_main_window_constructs(app_state: AppState) -> None:
    window = MainWindow(app_state)
    assert "192.168.1.42:8765" in window._status_label.text()


def test_every_page_has_a_sidebar_entry(app_state: AppState) -> None:
    """Adding a page but forgetting its label leaves it unreachable, and the
    stack silently renders the wrong page for every row after it."""
    window = MainWindow(app_state)
    sidebar = window.findChild(QListWidget)
    assert sidebar.count() == len(window._pages)


def test_dashboard_page_constructs(app_state: AppState) -> None:
    DashboardPage(app_state)


def test_files_page_constructs(app_state: AppState) -> None:
    page = FilesPage(app_state, FileClient("192.168.1.42", 8765, "token"))
    assert page.acceptDrops(), "Explorer'dan surukle-birak icin drop kabul edilmeli"
