from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem

from pi_protocol import ProcessListResultPayload

from desktop_app.ui.format import bytes_human

_COLUMNS = ["PID", "Ad", "Kullanici", "CPU %", "Bellek %", "RSS", "Durum"]


class ProcessTable(QTableWidget):
    def __init__(self) -> None:
        super().__init__(0, len(_COLUMNS))
        self.setHorizontalHeaderLabels(_COLUMNS)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

    def update_processes(self, payload: ProcessListResultPayload) -> None:
        # Preserve the selected PID across refreshes so the row the user clicked
        # doesn't jump out from under them every couple of seconds.
        selected_pid = self.selected_pid()

        self.setRowCount(len(payload.processes))
        for row, proc in enumerate(payload.processes):
            values = [
                str(proc.pid),
                proc.name,
                proc.username or "—",
                f"{proc.cpu_percent:.1f}",
                f"{proc.memory_percent:.1f}",
                bytes_human(proc.memory_rss_bytes),
                proc.status,
            ]
            for column, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setToolTip(proc.cmdline or proc.name)
                if column in (0, 3, 4, 5):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.setItem(row, column, item)

            if proc.pid == selected_pid:
                self.selectRow(row)

        self.resizeColumnsToContents()
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

    def selected_pid(self) -> int | None:
        rows = self.selectionModel().selectedRows() if self.selectionModel() else []
        if not rows:
            return None
        item = self.item(rows[0].row(), 0)
        return int(item.text()) if item else None

    def selected_name(self) -> str | None:
        rows = self.selectionModel().selectedRows() if self.selectionModel() else []
        if not rows:
            return None
        item = self.item(rows[0].row(), 1)
        return item.text() if item else None
