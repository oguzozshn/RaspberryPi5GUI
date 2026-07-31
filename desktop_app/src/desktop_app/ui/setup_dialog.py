from __future__ import annotations

import asyncio

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from desktop_app.connection.ws_client import AuthResult, WsClient


class SetupDialog(QDialog):
    """First-run screen: enter the Pi's IP + pairing token, verify before saving."""

    def __init__(self, ws_client: WsClient, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Raspberry Pi Baglantisi")
        self._ws_client = ws_client

        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("192.168.1.42")
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(8765)
        self.token_edit = QLineEdit()
        self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)

        form = QFormLayout()
        form.addRow("Pi IP adresi:", self.host_edit)
        form.addRow("Port:", self.port_spin)
        form.addRow("Pairing token:", self.token_edit)

        self.status_label = QLabel("")
        self.test_button = QPushButton("Baglantiyi Test Et")
        self.save_button = QPushButton("Kaydet ve Devam Et")
        self.save_button.setEnabled(False)

        self.test_button.clicked.connect(self._on_test_clicked)
        self.save_button.clicked.connect(self.accept)
        self.host_edit.textChanged.connect(self._invalidate)
        self.port_spin.valueChanged.connect(self._invalidate)
        self.token_edit.textChanged.connect(self._invalidate)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.status_label)
        layout.addWidget(self.test_button)
        layout.addWidget(self.save_button)

    def connection_info(self) -> tuple[str, int, str]:
        return self.host_edit.text().strip(), self.port_spin.value(), self.token_edit.text().strip()

    def _invalidate(self) -> None:
        self.save_button.setEnabled(False)
        self.status_label.setText("")

    def _on_test_clicked(self) -> None:
        asyncio.ensure_future(self._test_connection())

    async def _test_connection(self) -> None:
        host, port, token = self.connection_info()
        if not host or not token:
            self.status_label.setText("IP adresi ve token gerekli.")
            return

        self.test_button.setEnabled(False)
        self.status_label.setText("Baglaniliyor...")
        try:
            result = await self._ws_client.connect(host, port, token)
        except Exception as exc:  # noqa: BLE001 - surface any connect failure to the user
            self.status_label.setText(f"Baglanti hatasi: {exc}")
            self.test_button.setEnabled(True)
            return

        self.test_button.setEnabled(True)
        if result is AuthResult.OK:
            self.status_label.setText("Baglanti basarili.")
            self.save_button.setEnabled(True)
        else:
            self.status_label.setText("Token reddedildi.")
            self.save_button.setEnabled(False)
