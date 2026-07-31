from __future__ import annotations

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QWidget


def muted(widget: QWidget, size_px: int = 11) -> str:
    """Stylesheet for secondary text that stays legible in both light and dark
    themes. `palette(mid)` resolves to near-background grey under a dark theme,
    which rendered tile captions effectively invisible - derive from the actual
    foreground colour with alpha instead."""
    colour = widget.palette().color(QPalette.ColorRole.WindowText)
    return (
        f"color: rgba({colour.red()}, {colour.green()}, {colour.blue()}, 170); "
        f"font-size: {size_px}px;"
    )
