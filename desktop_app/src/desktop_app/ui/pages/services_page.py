from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor

from pi_protocol import (
    ServiceActionResultPayload,
    ServiceInfo,
    ServiceListResultPayload,
    ServiceLogsResultPayload,
)

from desktop_app.app_state import AppState
from desktop_app.async_utils import schedule
from desktop_app.ui.theme import muted

_COLUMNS = ["Servis", "Yuklu", "Durum", "Alt durum", "Aciklama"]
_ACTIVE_COLOURS = {"active": "#27ae60", "failed": "#c0392b", "inactive": "#7f8c8d"}


class ServicesPage(QWidget):
    """systemd units: browse, start/stop/restart, and tail journalctl."""

    def __init__(self, app_state: AppState) -> None:
        super().__init__()
        self._app_state = app_state
        self._services: list[ServiceInfo] = []

        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Servis adi veya aciklamaya gore filtrele...")
        self._filter.returnPressed.connect(self.refresh)

        refresh_button = QPushButton("Yenile")
        refresh_button.clicked.connect(self.refresh)

        self._start_button = QPushButton("Baslat")
        self._stop_button = QPushButton("Durdur")
        self._restart_button = QPushButton("Yeniden baslat")
        self._logs_button = QPushButton("Loglari getir")
        self._start_button.clicked.connect(lambda: self._action("start"))
        self._stop_button.clicked.connect(lambda: self._action("stop"))
        self._restart_button.clicked.connect(lambda: self._action("restart"))
        self._logs_button.clicked.connect(self._fetch_logs)

        toolbar = QHBoxLayout()
        toolbar.addWidget(self._filter, stretch=1)
        toolbar.addWidget(refresh_button)

        actions = QHBoxLayout()
        for button in (self._start_button, self._stop_button, self._restart_button, self._logs_button):
            button.setEnabled(False)
            actions.addWidget(button)
        actions.addStretch(1)

        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)

        self._logs = QPlainTextEdit()
        self._logs.setReadOnly(True)
        self._logs.setPlaceholderText("Bir servis secip 'Loglari getir' deyin.")

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self._table)
        splitter.addWidget(self._logs)
        splitter.setSizes([420, 220])

        self._status = QLabel("")
        self._status.setStyleSheet(muted(self, size_px=12))

        layout = QVBoxLayout(self)
        layout.addLayout(toolbar)
        layout.addLayout(actions)
        layout.addWidget(splitter, stretch=1)
        layout.addWidget(self._status)

        app_state.services_listed.connect(self._on_services)
        app_state.service_action_done.connect(self._on_action_done)
        app_state.service_logs_received.connect(self._on_logs)

    def start(self) -> None:
        if not self._app_state.capabilities.systemd:
            self._set_status("Bu sistemde systemd yok — servis yonetimi kullanilamiyor.", warn=True)
            self._filter.setEnabled(False)
            return
        self.refresh()

    def refresh(self) -> None:
        self._set_status("Servisler getiriliyor...")
        schedule(
            self._app_state.request_services(self._filter.text().strip()),
            lambda exc: self._set_status(str(exc), warn=True),
        )

    def _set_status(self, text: str, warn: bool = False) -> None:
        """Always restyle, never just setText - otherwise a one-off warning
        leaves every later message stuck in the warning colour."""
        self._status.setText(text)
        self._status.setStyleSheet("color: #e67e22;" if warn else muted(self, size_px=12))

    # --- incoming ----------------------------------------------------------

    def _on_services(self, payload: ServiceListResultPayload) -> None:
        self._services = payload.services
        self._table.setRowCount(len(payload.services))
        for row, service in enumerate(payload.services):
            values = [service.unit, service.load, service.active, service.sub, service.description]
            for column, text in enumerate(values):
                item = QTableWidgetItem(text)
                if column == 2 and (colour := _ACTIVE_COLOURS.get(service.active)):
                    item.setForeground(QBrush(QColor(colour)))
                self._table.setItem(row, column, item)

        self._table.resizeColumnsToContents()
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self._set_status(f"{len(payload.services)} servis")
        self._on_selection_changed()

    def _on_action_done(self, payload: ServiceActionResultPayload) -> None:
        verb = {"start": "baslatildi", "stop": "durduruldu", "restart": "yeniden baslatildi"}[payload.action]
        if payload.ok:
            self._set_status(f"{payload.unit} {verb}.")
            self.refresh()
        else:
            self._set_status(f"{payload.unit} {payload.action} basarisiz: {payload.detail}", warn=True)

    def _on_logs(self, payload: ServiceLogsResultPayload) -> None:
        self._logs.setPlainText("\n".join(payload.lines))
        self._logs.verticalScrollBar().setValue(self._logs.verticalScrollBar().maximum())
        self._set_status(f"{payload.unit}: {len(payload.lines)} satir log")

    # --- selection / actions -----------------------------------------------

    def _selected_unit(self) -> str | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        index = rows[0].row()
        return self._services[index].unit if index < len(self._services) else None

    def _on_selection_changed(self) -> None:
        enabled = self._selected_unit() is not None
        for button in (self._start_button, self._stop_button, self._restart_button, self._logs_button):
            button.setEnabled(enabled)

    def _action(self, action: str) -> None:
        unit = self._selected_unit()
        if unit is None:
            return
        self._set_status(f"{unit}: {action}...")
        schedule(
            self._app_state.service_action(unit, action),
            lambda exc: self._set_status(str(exc), warn=True),
        )

    def _fetch_logs(self) -> None:
        unit = self._selected_unit()
        if unit is None:
            return
        self._logs.setPlainText(f"{unit} loglari getiriliyor...")
        schedule(
            self._app_state.request_service_logs(unit),
            lambda exc: self._set_status(str(exc), warn=True),
        )
