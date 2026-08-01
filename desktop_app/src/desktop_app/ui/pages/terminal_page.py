from __future__ import annotations

import pyte
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication, QKeyEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pi_protocol import TerminalExitPayload, TerminalOutputPayload

from desktop_app.app_state import AppState
from desktop_app.async_utils import schedule
from desktop_app.ui.theme import muted

DEFAULT_COLS, DEFAULT_ROWS = 100, 30

# Keys with no printable character: what the shell expects to receive instead.
_SPECIAL_KEYS: dict[int, str] = {
    Qt.Key.Key_Return.value: "\r",
    Qt.Key.Key_Enter.value: "\r",
    Qt.Key.Key_Backspace.value: "\x7f",
    Qt.Key.Key_Tab.value: "\t",
    Qt.Key.Key_Escape.value: "\x1b",
    Qt.Key.Key_Up.value: "\x1b[A",
    Qt.Key.Key_Down.value: "\x1b[B",
    Qt.Key.Key_Right.value: "\x1b[C",
    Qt.Key.Key_Left.value: "\x1b[D",
    Qt.Key.Key_Home.value: "\x1b[H",
    Qt.Key.Key_End.value: "\x1b[F",
    Qt.Key.Key_PageUp.value: "\x1b[5~",
    Qt.Key.Key_PageDown.value: "\x1b[6~",
    Qt.Key.Key_Delete.value: "\x1b[3~",
    Qt.Key.Key_Insert.value: "\x1b[2~",
}


def is_paste(event: QKeyEvent) -> bool:
    """Ctrl+V, Ctrl+Shift+V ve Shift+Insert.

    Terminal geleneginde yapistirma Ctrl+Shift+V'dir, cunku Ctrl+V kabukta
    'quoted insert' (0x16) anlamina gelir. Ama bu bir Windows masaustu
    uygulamasi ve kullanicinin refleksi Ctrl+V; ikisini de kabul ediyoruz.
    """
    modifiers = event.modifiers()
    if modifiers & Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_V.value:
        return True
    return bool(
        modifiers & Qt.KeyboardModifier.ShiftModifier and event.key() == Qt.Key.Key_Insert.value
    )


def is_copy(event: QKeyEvent) -> bool:
    """Ctrl+Shift+C: Ctrl+C burada kopyalama degil, SIGINT gonderir."""
    modifiers = event.modifiers()
    return bool(
        modifiers & Qt.KeyboardModifier.ControlModifier
        and modifiers & Qt.KeyboardModifier.ShiftModifier
        and event.key() == Qt.Key.Key_C.value
    )


def paste_payload(text: str) -> str:
    """Panodaki metni kabugun bekledigi hale getir.

    Satir sonlari \\r olmali: kabuk \\n'i satir sonu saymaz, cok satirli bir
    yapistirma tek satira yapisir ya da hic calismaz.
    """
    return text.replace("\r\n", "\r").replace("\n", "\r")


def key_to_bytes(event: QKeyEvent) -> str:
    """Translate a Qt key event into what a terminal would send.

    Control combinations are computed rather than tabulated: Ctrl+A..Ctrl+Z map
    to 0x01..0x1a, which is how Ctrl+C reaches the foreground process as SIGINT.
    """
    if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
        key = event.key()
        if Qt.Key.Key_A.value <= key <= Qt.Key.Key_Z.value:
            return chr(key - Qt.Key.Key_A.value + 1)
        if key == Qt.Key.Key_BracketLeft.value:
            return "\x1b"
        if key == Qt.Key.Key_Backslash.value:
            return "\x1c"

    if (special := _SPECIAL_KEYS.get(event.key())) is not None:
        return special
    return event.text()


class TerminalView(QPlainTextEdit):
    """Read-only surface: every keystroke goes to the Pi, none edits the widget."""

    def __init__(self, on_key) -> None:
        super().__init__()
        self._on_key = on_key
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)
        self.setReadOnly(True)
        self.setUndoRedoEnabled(False)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setPointSize(10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(font)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt override
        if is_paste(event):
            self.paste_clipboard()
            event.accept()
            return
        if is_copy(event):
            self.copy()
            event.accept()
            return

        data = key_to_bytes(event)
        if data:
            self._on_key(data)
        event.accept()

    def paste_clipboard(self) -> None:
        text = QGuiApplication.clipboard().text()
        if text:
            self._on_key(paste_payload(text))

    def _show_menu(self, position) -> None:
        """Sag tik menusu: kisayolu bilmeyen icin kesfedilebilir yol."""
        menu = QMenu(self)
        copy_action = menu.addAction("Kopyala (Ctrl+Shift+C)")
        copy_action.setEnabled(self.textCursor().hasSelection())
        copy_action.triggered.connect(self.copy)
        menu.addAction("Yapistir (Ctrl+V)").triggered.connect(self.paste_clipboard)
        menu.exec(self.mapToGlobal(position))


class TerminalPage(QWidget):
    """A real shell on the Pi, driven over the control channel.

    The agent runs it on a pseudo-terminal, so interactive programs (htop, nano,
    a sudo password prompt) work; pyte turns the escape sequences back into a
    screen here."""

    def __init__(self, app_state: AppState) -> None:
        super().__init__()
        self._app_state = app_state
        self._open = False
        self._screen = pyte.Screen(DEFAULT_COLS, DEFAULT_ROWS)
        self._stream = pyte.Stream(self._screen)

        self._banner = QLabel("")
        self._banner.setWordWrap(True)
        self._banner.setStyleSheet(muted(self, size_px=12))

        self._view = TerminalView(self._send_input)

        self._open_button = QPushButton("Baslat")
        self._close_button = QPushButton("Kapat")
        self._open_button.clicked.connect(self.open_session)
        self._close_button.clicked.connect(self.close_session)
        self._close_button.setEnabled(False)

        toolbar = QHBoxLayout()
        toolbar.addWidget(self._open_button)
        toolbar.addWidget(self._close_button)
        toolbar.addStretch(1)

        self._status = QLabel("")
        self._status.setStyleSheet(muted(self, size_px=12))

        layout = QVBoxLayout(self)
        layout.addWidget(self._banner)
        layout.addLayout(toolbar)
        layout.addWidget(self._view, stretch=1)
        layout.addWidget(self._status)

        app_state.terminal_output.connect(self._on_output)
        app_state.terminal_exited.connect(self._on_exit)

    # --- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        capabilities = self._app_state.capabilities
        if not capabilities.terminal:
            detail = capabilities.terminal_detail or "sebep bildirilmedi"
            self._banner.setText(f"Terminal kullanilamiyor: {detail}")
            self._banner.setStyleSheet("color: #e67e22;")
            self._open_button.setEnabled(False)
            return

        self._banner.setText(
            f"Kabuk: {capabilities.terminal_detail} · Bu sekme Pi'de tam yetkili bir "
            "kabuk acar; SSH ile ayni seyleri yapabilirsiniz."
        )
        # Opening a shell is not free (a process on the Pi), so it waits for the
        # user rather than starting with the application.

    def open_session(self) -> None:
        self._reset_screen()
        self._set_status("Kabuk baslatiliyor...")
        schedule(
            self._app_state.open_terminal(DEFAULT_COLS, DEFAULT_ROWS),
            lambda exc: self._set_status(str(exc), warn=True),
        )
        self._open = True
        self._open_button.setEnabled(False)
        self._close_button.setEnabled(True)
        self._view.setFocus()

    def close_session(self) -> None:
        schedule(
            self._app_state.close_terminal(),
            lambda exc: self._set_status(str(exc), warn=True),
        )
        self._on_closed("oturum kapatildi")

    def _on_closed(self, detail: str) -> None:
        self._open = False
        self._open_button.setEnabled(True)
        self._close_button.setEnabled(False)
        self._set_status(detail)

    # --- data ---------------------------------------------------------------

    def _send_input(self, data: str) -> None:
        if not self._open:
            return
        schedule(
            self._app_state.send_terminal_input(data),
            lambda exc: self._set_status(str(exc), warn=True),
        )

    def _on_output(self, payload: TerminalOutputPayload) -> None:
        self._stream.feed(payload.data)
        self._render()

    def _on_exit(self, payload: TerminalExitPayload) -> None:
        code = "?" if payload.exit_code is None else payload.exit_code
        self._on_closed(f"{payload.detail} (cikis kodu {code})")

    def _reset_screen(self) -> None:
        self._screen.reset()
        self._view.clear()

    def _render(self) -> None:
        """Repaint from pyte's screen buffer rather than appending text: the
        shell moves the cursor around, and appending would turn a redrawn line
        (or htop's whole screen) into a scrolling mess."""
        lines = [line.rstrip() for line in self._screen.display]
        while lines and not lines[-1]:
            lines.pop()
        self._view.setPlainText("\n".join(lines))
        scrollbar = self._view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _set_status(self, text: str, warn: bool = False) -> None:
        self._status.setText(text)
        self._status.setStyleSheet("color: #e67e22;" if warn else muted(self, size_px=12))
