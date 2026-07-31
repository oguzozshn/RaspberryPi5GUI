from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
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

from pi_protocol import (
    ContainerInfo,
    DockerActionResultPayload,
    DockerListResultPayload,
    DockerLogsResultPayload,
)

from desktop_app.app_state import AppState
from desktop_app.async_utils import schedule
from desktop_app.ui.theme import muted

_COLUMNS = ["Container", "Imaj", "Durum", "Detay", "Portlar"]
_STATE_COLOURS = {"running": "#27ae60", "exited": "#7f8c8d", "restarting": "#e67e22",
                  "paused": "#e67e22", "dead": "#c0392b"}


class DockerPage(QWidget):
    """Containers: browse, start/stop/restart, and tail `docker logs`.

    Deliberately read-and-control only: no image pulls, no `docker run`, no
    compose. Those need arguments this GUI has no safe way to collect over a
    LAN-only pairing token."""

    def __init__(self, app_state: AppState) -> None:
        super().__init__()
        self._app_state = app_state
        self._containers: list[ContainerInfo] = []

        self._banner = QLabel("")
        self._banner.setWordWrap(True)
        self._banner.setStyleSheet(muted(self, size_px=12))

        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Container adi veya imaja gore filtrele...")
        self._filter.textChanged.connect(self._apply_filter)

        self._show_stopped = QCheckBox("Durmus olanlari da goster")
        self._show_stopped.setChecked(True)
        self._show_stopped.toggled.connect(lambda _checked: self.refresh())

        refresh_button = QPushButton("Yenile")
        refresh_button.clicked.connect(self.refresh)

        toolbar = QHBoxLayout()
        toolbar.addWidget(self._filter, stretch=1)
        toolbar.addWidget(self._show_stopped)
        toolbar.addWidget(refresh_button)

        self._start_button = QPushButton("Baslat")
        self._stop_button = QPushButton("Durdur")
        self._restart_button = QPushButton("Yeniden baslat")
        self._logs_button = QPushButton("Loglari getir")
        self._start_button.clicked.connect(lambda: self._action("start"))
        self._stop_button.clicked.connect(lambda: self._action("stop"))
        self._restart_button.clicked.connect(lambda: self._action("restart"))
        self._logs_button.clicked.connect(self._fetch_logs)

        actions = QHBoxLayout()
        self._buttons = (self._start_button, self._stop_button, self._restart_button, self._logs_button)
        for button in self._buttons:
            button.setEnabled(False)
            actions.addWidget(button)
        actions.addStretch(1)

        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)

        self._logs = QPlainTextEdit()
        self._logs.setReadOnly(True)
        self._logs.setPlaceholderText("Bir container secip 'Loglari getir' deyin.")

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self._table)
        splitter.addWidget(self._logs)
        splitter.setSizes([420, 220])

        self._status = QLabel("")
        self._status.setStyleSheet(muted(self, size_px=12))

        layout = QVBoxLayout(self)
        layout.addWidget(self._banner)
        layout.addLayout(toolbar)
        layout.addLayout(actions)
        layout.addWidget(splitter, stretch=1)
        layout.addWidget(self._status)

        app_state.containers_listed.connect(self._on_containers)
        app_state.container_action_done.connect(self._on_action_done)
        app_state.container_logs_received.connect(self._on_logs)

    def start(self) -> None:
        capabilities = self._app_state.capabilities
        if not capabilities.docker:
            detail = capabilities.docker_detail or "sebep bildirilmedi"
            self._banner.setText(f"Docker kullanilamiyor: {detail}")
            self._banner.setStyleSheet("color: #e67e22;")
            self._filter.setEnabled(False)
            self._show_stopped.setEnabled(False)
            return

        self._banner.setText(capabilities.docker_detail)
        self.refresh()

    def refresh(self) -> None:
        self._set_status("Container'lar getiriliyor...")
        schedule(
            self._app_state.request_containers(self._show_stopped.isChecked()),
            lambda exc: self._set_status(str(exc), warn=True),
        )

    def _set_status(self, text: str, warn: bool = False) -> None:
        self._status.setText(text)
        self._status.setStyleSheet("color: #e67e22;" if warn else muted(self, size_px=12))

    # --- incoming ----------------------------------------------------------

    def _on_containers(self, payload: DockerListResultPayload) -> None:
        self._containers = payload.containers
        self._render()
        running = sum(1 for c in self._containers if c.state == "running")
        self._set_status(f"{len(self._containers)} container · {running} calisiyor")

    def _visible_containers(self) -> list[ContainerInfo]:
        """Filtering happens here rather than in the agent: the list is small
        and re-querying docker on every keystroke would be wasteful."""
        needle = self._filter.text().strip().lower()
        if not needle:
            return self._containers
        return [
            c for c in self._containers if needle in c.name.lower() or needle in c.image.lower()
        ]

    def _apply_filter(self) -> None:
        self._render()

    def _render(self) -> None:
        containers = self._visible_containers()
        self._table.setRowCount(len(containers))
        for row, container in enumerate(containers):
            values = [container.name, container.image, container.state, container.status,
                      container.ports]
            for column, text in enumerate(values):
                item = QTableWidgetItem(text)
                if column == 2 and (colour := _STATE_COLOURS.get(container.state)):
                    item.setForeground(QBrush(QColor(colour)))
                if column == 0:
                    item.setToolTip(f"id {container.id}\nolusturuldu {container.created}")
                self._table.setItem(row, column, item)

        self._table.resizeColumnsToContents()
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._on_selection_changed()

    def _on_action_done(self, payload: DockerActionResultPayload) -> None:
        verb = {"start": "baslatildi", "stop": "durduruldu", "restart": "yeniden baslatildi"}[
            payload.action
        ]
        if payload.ok:
            self._set_status(f"{payload.container} {verb}.")
            self.refresh()
        else:
            self._set_status(
                f"{payload.container} {payload.action} basarisiz: {payload.detail}", warn=True
            )

    def _on_logs(self, payload: DockerLogsResultPayload) -> None:
        self._logs.setPlainText("\n".join(payload.lines))
        self._logs.verticalScrollBar().setValue(self._logs.verticalScrollBar().maximum())
        self._set_status(f"{payload.container}: {len(payload.lines)} satir log")

    # --- selection / actions -----------------------------------------------

    def _selected_container(self) -> ContainerInfo | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        containers = self._visible_containers()
        index = rows[0].row()
        return containers[index] if index < len(containers) else None

    def _on_selection_changed(self) -> None:
        container = self._selected_container()
        running = container is not None and container.state == "running"
        # Offering "Baslat" on a running container only produces an error from
        # the daemon, so mirror the container's actual state in the buttons.
        self._start_button.setEnabled(container is not None and not running)
        self._stop_button.setEnabled(running)
        self._restart_button.setEnabled(running)
        self._logs_button.setEnabled(container is not None)

    def _action(self, action: str) -> None:
        container = self._selected_container()
        if container is None:
            return
        self._set_status(f"{container.name}: {action}...")
        schedule(
            self._app_state.container_action(container.name, action),
            lambda exc: self._set_status(str(exc), warn=True),
        )

    def _fetch_logs(self) -> None:
        container = self._selected_container()
        if container is None:
            return
        self._logs.setPlainText(f"{container.name} loglari getiriliyor...")
        schedule(
            self._app_state.request_container_logs(container.name),
            lambda exc: self._set_status(str(exc), warn=True),
        )
