from __future__ import annotations

from datetime import datetime

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from pi_protocol import ChatMessagePayload

from desktop_app.app_state import AppState
from desktop_app.async_utils import schedule
from desktop_app.ui.theme import muted


class ChatPage(QWidget):
    """Text channel to the Pi. Sending places the text on the Pi's system
    clipboard so it can be pasted into whatever prompt is focused there - this
    is what replaces keeping an SSH session open just to paste a password.
    """

    def __init__(self, app_state: AppState) -> None:
        super().__init__()
        self._app_state = app_state

        self._banner = QLabel()
        self._banner.setWordWrap(True)

        self._history = QTextBrowser()
        self._history.setOpenExternalLinks(False)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Pi'nin panosuna gonderilecek metin...")
        self._input.returnPressed.connect(self._send)

        self._send_button = QPushButton("Gonder")
        self._send_button.clicked.connect(self._send)

        self._pull_button = QPushButton("Pi'nin panosunu oku")
        self._pull_button.clicked.connect(self._pull)

        self._mask_button = QPushButton("Gizle")
        self._mask_button.setCheckable(True)
        self._mask_button.setToolTip("Sifre yazarken girisi maskele")
        self._mask_button.toggled.connect(self._set_masked)

        entry = QHBoxLayout()
        entry.addWidget(self._input, stretch=1)
        entry.addWidget(self._mask_button)
        entry.addWidget(self._send_button)

        actions = QHBoxLayout()
        actions.addWidget(self._pull_button)
        actions.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(self._banner)
        layout.addWidget(self._history, stretch=1)
        layout.addLayout(entry)
        layout.addLayout(actions)

        app_state.chat_message_received.connect(self._on_message)
        self._apply_capabilities()

    def start(self) -> None:
        self._apply_capabilities()

    def _apply_capabilities(self) -> None:
        caps = self._app_state.capabilities
        if caps.clipboard:
            self._banner.setText(f"Pano baglantisi hazir: {caps.clipboard_detail}")
            self._banner.setStyleSheet(muted(self, size_px=12))
        else:
            # Not a transient error: a headless Pi has no clipboard at all, so
            # say why rather than letting every send fail silently.
            self._banner.setText(
                f"⚠ Pi'nin panosuna yazilamiyor — {caps.clipboard_detail}. "
                "Pano koprusu, Pi'de acik bir masaustu oturumu gerektirir."
            )
            self._banner.setStyleSheet("color: #e67e22;")
        self._send_button.setEnabled(caps.clipboard)
        self._pull_button.setEnabled(caps.clipboard)

    def _set_masked(self, masked: bool) -> None:
        self._input.setEchoMode(
            QLineEdit.EchoMode.Password if masked else QLineEdit.EchoMode.Normal
        )
        self._mask_button.setText("Goster" if masked else "Gizle")

    def _send(self) -> None:
        text = self._input.text()
        if not text or not self._app_state.capabilities.clipboard:
            return
        self._input.clear()
        schedule(self._app_state.send_chat(text), lambda exc: self._append("sistem", str(exc)))

    def _pull(self) -> None:
        schedule(self._app_state.pull_clipboard(), lambda exc: self._append("sistem", str(exc)))

    def _on_message(self, payload: ChatMessagePayload) -> None:
        if payload.source == "desktop":
            status = "panoya yazildi" if payload.delivered_to_clipboard else f"HATA: {payload.detail}"
            self._append("Ben → Pi", payload.text, status, masked=self._mask_button.isChecked())
            return

        if payload.detail:
            self._append("Pi", "", f"pano okunamadi: {payload.detail}")
            return

        self._append("Pi panosu", payload.text)
        QGuiApplication.clipboard().setText(payload.text)

    def _append(self, who: str, text: str, status: str = "", masked: bool = False) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        shown = "•" * len(text) if masked and text else text
        suffix = f"  <i>({status})</i>" if status else ""
        body = f"<b>{who}</b> <small>{stamp}</small>{suffix}"
        if shown:
            body += f"<br>{_escape(shown)}"
        self._history.append(body)


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br>")
    )
