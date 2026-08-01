from __future__ import annotations

import asyncio
import logging
import sys

from PySide6.QtWidgets import QApplication, QDialog
from qasync import QEventLoop

from desktop_app.app_state import AppState
from desktop_app.connection.ws_client import AuthResult, WsClient
from desktop_app.settings import Settings
from desktop_app.ui.main_window import MainWindow
from desktop_app.ui.setup_dialog import SetupDialog


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    settings = Settings()
    ws_client = WsClient()

    with loop:
        loop.run_until_complete(_bootstrap(app, settings, ws_client))
        loop.run_forever()


async def _bootstrap(app: QApplication, settings: Settings, ws_client: WsClient) -> None:
    host, port, token = settings.host, settings.port, settings.token

    if host and token:
        reason = ""
        try:
            result = await ws_client.connect(host, port, token)
        except Exception as exc:  # noqa: BLE001 - Pi unreachable, or refusing
            result, reason = None, str(exc)
        if result is AuthResult.OK:
            _show_main_window(ws_client, host, port, token)
            return
        if result is None:
            # Settings are saved and the token was never rejected - the Pi is
            # just not answering, most likely switched off. Opening the setup
            # dialog would ask for details the user already gave; show the panel
            # disconnected instead, with its "Yeniden Baglan" button.
            window = _show_main_window(ws_client, host, port, token, connected=False)
            window._on_connection_changed(False, reason or "Pi'ye ulasilamadi")
            return

    dialog = SetupDialog(ws_client)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        host, port, token = dialog.connection_info()
        settings.host = host
        settings.port = port
        settings.token = token
        _show_main_window(ws_client, host, port, token)
    else:
        app.quit()


def _show_main_window(
    ws_client: WsClient, host: str, port: int, token: str, connected: bool = True
) -> MainWindow:
    app_state = AppState(ws_client, host, port, token)
    window = MainWindow(app_state)
    window.show()
    if connected:
        # Without a connection the pages' initial requests would only produce a
        # screenful of errors; they run once the user reconnects.
        window.start()
    # Keep references on the QApplication so neither the window nor the state
    # object is garbage collected once _bootstrap returns.
    instance = QApplication.instance()
    instance.main_window = window  # type: ignore[attr-defined]
    instance.app_state = app_state  # type: ignore[attr-defined]
    return window


if __name__ == "__main__":
    run()
