from __future__ import annotations

import posixpath
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pi_protocol import FileEntry, FilesListResultPayload

from desktop_app.app_state import AppState
from desktop_app.async_utils import schedule
from desktop_app.connection.file_client import FileClient, TransferError
from desktop_app.ui.format import bytes_human, timestamp_human
from desktop_app.ui.theme import muted
from desktop_app.ui.widgets.transfer_list import TransferList

DEFAULT_REMOTE_PATH = "/home"
_COLUMNS = ["Ad", "Boyut", "Degistirilme", "Izinler"]


class FilesPage(QWidget):
    """Remote browser plus a drop target. Dropping files from Explorer uploads
    them into whichever directory is currently open."""

    def __init__(self, app_state: AppState, file_client: FileClient) -> None:
        super().__init__()
        self._app_state = app_state
        self._file_client = file_client
        self._current_path = DEFAULT_REMOTE_PATH
        self._entries: list[FileEntry] = []

        self.setAcceptDrops(True)

        self._path_edit = QLineEdit(DEFAULT_REMOTE_PATH)
        self._path_edit.returnPressed.connect(lambda: self.navigate_to(self._path_edit.text().strip()))
        up_button = QPushButton("Yukari")
        up_button.clicked.connect(self._go_up)
        refresh_button = QPushButton("Yenile")
        refresh_button.clicked.connect(lambda: self.navigate_to(self._current_path))
        self._download_button = QPushButton("Indir")
        self._download_button.clicked.connect(self._download_selected)
        self._download_button.setEnabled(False)

        toolbar = QHBoxLayout()
        toolbar.addWidget(up_button)
        toolbar.addWidget(self._path_edit, stretch=1)
        toolbar.addWidget(refresh_button)
        toolbar.addWidget(self._download_button)

        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.cellDoubleClicked.connect(self._on_double_click)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)

        self._status = QLabel("Yuklemek icin dosyalari bu pencereye surukleyip birakin.")
        self._status.setStyleSheet(muted(self, size_px=12))

        self._transfers = TransferList()

        layout = QVBoxLayout(self)
        layout.addLayout(toolbar)
        layout.addWidget(self._table, stretch=1)
        layout.addWidget(self._status)
        layout.addWidget(QLabel("Transferler"))
        layout.addWidget(self._transfers)

        app_state.files_listed.connect(self._on_files_listed)
        app_state.error_received.connect(self._on_error)

    def start(self) -> None:
        """Load the initial listing. Kept out of __init__ so constructing the
        widget does no I/O and does not require a running event loop."""
        self.navigate_to(DEFAULT_REMOTE_PATH)

    # --- navigation --------------------------------------------------------

    def navigate_to(self, path: str) -> None:
        if not path:
            return
        self._status.setText(f"{path} listeleniyor...")
        schedule(self._app_state.request_files(path), lambda exc: self._status.setText(str(exc)))

    def _go_up(self) -> None:
        parent = posixpath.dirname(self._current_path.rstrip("/"))
        self.navigate_to(parent or "/")

    def _on_files_listed(self, payload: FilesListResultPayload) -> None:
        self._current_path = payload.path
        self._path_edit.setText(payload.path)
        self._entries = payload.entries

        self._table.setRowCount(len(payload.entries))
        for row, entry in enumerate(payload.entries):
            values = [
                ("📁 " if entry.is_dir else "") + entry.name,
                "" if entry.is_dir else bytes_human(entry.size_bytes),
                timestamp_human(entry.modified_ts),
                entry.permissions,
            ]
            for column, text in enumerate(values):
                item = QTableWidgetItem(text)
                if column == 1:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._table.setItem(row, column, item)

        self._status.setText(f"{len(payload.entries)} oge · surukleyip birakarak buraya yukleyin")
        self._on_selection_changed()

    def _on_double_click(self, row: int, _column: int) -> None:
        entry = self._entries[row]
        if entry.is_dir:
            self.navigate_to(entry.path)

    def _on_selection_changed(self) -> None:
        entry = self._selected_entry()
        self._download_button.setEnabled(entry is not None and not entry.is_dir)

    def _selected_entry(self) -> FileEntry | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        index = rows[0].row()
        return self._entries[index] if index < len(self._entries) else None

    def _on_error(self, code: str, message: str) -> None:
        self._status.setText(f"Hata ({code}): {message}")

    # --- drag & drop upload ------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        local_paths = [
            Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()
        ]
        files = [p for p in local_paths if p.is_file()]
        skipped = len(local_paths) - len(files)

        for local_path in files:
            schedule(self._upload(local_path))

        if skipped:
            self._status.setText(f"{skipped} klasor atlandi - su an sadece dosya yuklenebiliyor.")
        event.acceptProposedAction()

    async def _upload(self, local_path: Path) -> None:
        remote_path = posixpath.join(self._current_path, local_path.name)
        row = self._transfers.add_row(f"↑ {local_path.name} → {self._current_path}")
        try:
            await self._file_client.upload(local_path, remote_path, row.set_progress)
        except (TransferError, OSError) as exc:
            row.set_failed(str(exc))
            self._status.setText(f"Yukleme basarisiz: {exc}")
            return
        row.set_done()
        self.navigate_to(self._current_path)

    # --- download ----------------------------------------------------------

    def _download_selected(self) -> None:
        entry = self._selected_entry()
        if entry is None or entry.is_dir:
            return
        destination, _ = QFileDialog.getSaveFileName(self, "Kaydet", entry.name)
        if destination:
            schedule(self._download(entry, Path(destination)))

    async def _download(self, entry: FileEntry, destination: Path) -> None:
        row = self._transfers.add_row(f"↓ {entry.name} → {destination.parent}")
        try:
            await self._file_client.download(entry.path, destination, row.set_progress)
        except (TransferError, OSError) as exc:
            row.set_failed(str(exc))
            self._status.setText(f"Indirme basarisiz: {exc}")
            return
        row.set_done()
