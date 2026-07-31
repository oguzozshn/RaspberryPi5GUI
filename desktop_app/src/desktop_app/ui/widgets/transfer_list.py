from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QWidget,
)

from desktop_app.ui.format import bytes_human
from desktop_app.ui.theme import muted


class TransferRow(QWidget):
    def __init__(self, label: str) -> None:
        super().__init__()
        self._label = QLabel(label)
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setFixedWidth(160)
        self._status = QLabel("bekliyor")
        self._status.setStyleSheet(muted(self, size_px=12))
        self._status.setFixedWidth(150)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.addWidget(self._label, stretch=1)
        layout.addWidget(self._bar)
        layout.addWidget(self._status)

    def set_progress(self, transferred: int, total: int) -> None:
        if total > 0:
            self._bar.setValue(int(transferred / total * 100))
            self._status.setText(f"{bytes_human(transferred)} / {bytes_human(total)}")
        else:
            self._status.setText(bytes_human(transferred))

    def set_done(self, message: str = "tamamlandi") -> None:
        self._bar.setValue(100)
        self._status.setText(message)

    def set_failed(self, message: str) -> None:
        self._status.setText("hata")
        self._status.setToolTip(message)
        self._status.setStyleSheet("color: #c0392b;")


class TransferList(QListWidget):
    """Queue of in-flight and finished transfers. Rows are mutated directly from
    async progress callbacks, which is safe because qasync runs the asyncio loop
    on the Qt thread - there is no cross-thread widget access here."""

    def __init__(self) -> None:
        super().__init__()
        self.setMaximumHeight(150)

    def add_row(self, label: str) -> TransferRow:
        row = TransferRow(label)
        item = QListWidgetItem(self)
        item.setSizeHint(row.sizeHint())
        self.addItem(item)
        self.setItemWidget(item, row)
        self.scrollToBottom()
        return row
