from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QProgressBar, QVBoxLayout

from desktop_app.ui.theme import muted


class StatTile(QFrame):
    """One labelled metric: big value, optional bar, optional sub-caption."""

    def __init__(self, title: str, show_bar: bool = True) -> None:
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumWidth(170)

        self._title = QLabel(title)
        self._title.setStyleSheet(muted(self))

        self._value = QLabel("—")
        self._value.setStyleSheet("font-size: 22px; font-weight: 600;")

        self._caption = QLabel("")
        self._caption.setStyleSheet(muted(self))
        self._caption.setAlignment(Qt.AlignmentFlag.AlignLeft)

        layout = QVBoxLayout(self)
        layout.addWidget(self._title)
        layout.addWidget(self._value)

        self._bar: QProgressBar | None = None
        if show_bar:
            self._bar = QProgressBar()
            self._bar.setRange(0, 100)
            self._bar.setTextVisible(False)
            self._bar.setFixedHeight(6)
            layout.addWidget(self._bar)

        layout.addWidget(self._caption)

    def update_values(self, value: str, percent: float | None = None, caption: str = "") -> None:
        self._value.setText(value)
        self._caption.setText(caption)
        if self._bar is not None and percent is not None:
            self._bar.setValue(int(max(0, min(100, percent))))
