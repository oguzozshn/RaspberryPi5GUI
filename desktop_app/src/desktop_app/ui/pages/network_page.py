from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pi_protocol import NetworkInfoResultPayload

from desktop_app.app_state import AppState
from desktop_app.async_utils import schedule
from desktop_app.ui.format import bytes_human
from desktop_app.ui.theme import muted

_COLUMNS = ["Arayuz", "Durum", "Adresler", "MAC", "Hiz", "Gonderilen", "Alinan"]


class NetworkPage(QWidget):
    """Read-only view of the Pi's addressing: which interface is up, what it is
    called on the LAN, and how the Wi-Fi link is holding up.

    Nothing here reconfigures the network - a mistake made over this connection
    would cut the very link used to fix it."""

    def __init__(self, app_state: AppState) -> None:
        super().__init__()
        self._app_state = app_state

        self._hostname = QLabel("—")
        self._gateway = QLabel("—")
        self._dns = QLabel("—")
        self._wifi = QLabel("—")

        summary = QGroupBox("Ozet")
        form = QFormLayout(summary)
        form.addRow("Hostname:", self._hostname)
        form.addRow("Varsayilan ag gecidi:", self._gateway)
        form.addRow("DNS:", self._dns)
        form.addRow("Wi-Fi:", self._wifi)

        refresh_button = QPushButton("Yenile")
        refresh_button.clicked.connect(self.refresh)
        toolbar = QHBoxLayout()
        toolbar.addStretch(1)
        toolbar.addWidget(refresh_button)

        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

        self._status = QLabel("")
        self._status.setStyleSheet(muted(self, size_px=12))

        layout = QVBoxLayout(self)
        layout.addWidget(summary)
        layout.addLayout(toolbar)
        layout.addWidget(self._table, stretch=1)
        layout.addWidget(self._status)

        app_state.network_info_received.connect(self._on_info)
        if app_state.latest_network is not None:
            self._on_info(app_state.latest_network)

    def start(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        self._set_status("Ag bilgisi getiriliyor...")
        schedule(
            self._app_state.request_network_info(),
            lambda exc: self._set_status(str(exc), warn=True),
        )

    def _set_status(self, text: str, warn: bool = False) -> None:
        self._status.setText(text)
        self._status.setStyleSheet("color: #e67e22;" if warn else muted(self, size_px=12))

    def _on_info(self, payload: NetworkInfoResultPayload) -> None:
        self._hostname.setText(payload.hostname)
        self._gateway.setText(payload.default_gateway or "—")
        self._dns.setText(", ".join(payload.dns_servers) or "—")
        self._wifi.setText(self._wifi_text(payload))

        self._table.setRowCount(len(payload.interfaces))
        for row, interface in enumerate(payload.interfaces):
            values = [
                interface.name,
                "up" if interface.is_up else "down",
                ", ".join(interface.addresses) or "—",
                interface.mac or "—",
                f"{interface.speed_mbps} Mb/s" if interface.speed_mbps else "—",
                bytes_human(interface.bytes_sent),
                bytes_human(interface.bytes_recv),
            ]
            for column, text in enumerate(values):
                self._table.setItem(row, column, QTableWidgetItem(text))

        self._table.resizeColumnsToContents()
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._set_status(f"{len(payload.interfaces)} arayuz")

    @staticmethod
    def _wifi_text(payload: NetworkInfoResultPayload) -> str:
        if not payload.wifi_interface:
            return "kablosuz arayuz yok"
        if not payload.wifi_ssid:
            return f"{payload.wifi_interface}: bagli degil"
        if payload.wifi_signal_dbm is None:
            return f"{payload.wifi_ssid} ({payload.wifi_interface})"
        # -50 dBm is a strong link, -70 is where a Pi starts dropping frames.
        quality = "iyi" if payload.wifi_signal_dbm >= -60 else (
            "zayif" if payload.wifi_signal_dbm >= -70 else "cok zayif"
        )
        return (
            f"{payload.wifi_ssid} ({payload.wifi_interface}) · "
            f"{payload.wifi_signal_dbm} dBm — {quality}"
        )
