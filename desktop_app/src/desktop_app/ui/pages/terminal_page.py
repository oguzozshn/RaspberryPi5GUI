from __future__ import annotations

import uuid

import pyte
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication, QKeyEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pi_protocol import TerminalExitPayload, TerminalOutputPayload

from desktop_app.app_state import AppState
from desktop_app.async_utils import schedule
from desktop_app.ui.theme import muted

DEFAULT_COLS, DEFAULT_ROWS = 100, 30
# Geriye dogru saklanan satir sayisi. Ekrandan kayan satirlar buraya dusuyor;
# bu olmadan kaydiracak bir sey yok, cunku pyte yalnizca gorunen ekrani tutar.
SCROLLBACK_LINES = 2000
MAX_TABS = 8

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


def history_lines(screen: pyte.HistoryScreen) -> list[str]:
    """Ekrandan yukari kayan satirlar.

    pyte bunlari hucre sozlugu olarak tutuyor; goruntulemek icin metne
    ceviriyoruz. Ekranin kendisi (screen.display) ayri gelir.
    """
    lines: list[str] = []
    for row in screen.history.top:
        text = "".join(row[column].data for column in range(screen.columns))
        lines.append(text.rstrip())
    return lines


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
        self.setMaximumBlockCount(SCROLLBACK_LINES + DEFAULT_ROWS + 50)

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


class TerminalTab(QWidget):
    """Tek bir kabuk: kendi ekrani, kendi gecmisi, kendi oturum kimligi."""

    def __init__(self, app_state: AppState, session_id: str) -> None:
        super().__init__()
        self._app_state = app_state
        self.session_id = session_id
        self.open = False
        self.awaiting_first_output = False

        self._screen = pyte.HistoryScreen(DEFAULT_COLS, DEFAULT_ROWS, history=SCROLLBACK_LINES)
        self._stream = pyte.Stream(self._screen)

        self.view = TerminalView(self.send_input)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)

    # --- oturum -------------------------------------------------------------

    def start(self) -> None:
        self._screen.reset()
        self.view.clear()
        self.open = True
        self.awaiting_first_output = True
        schedule(
            self._app_state.open_terminal(DEFAULT_COLS, DEFAULT_ROWS, self.session_id),
            lambda exc: self.feed(f"\r\n[baglanti hatasi: {exc}]\r\n"),
        )
        self.view.setFocus()

    def close_session(self) -> None:
        if not self.open:
            return
        self.open = False
        schedule(self._app_state.close_terminal(self.session_id), lambda _exc: None)

    def send_input(self, data: str) -> None:
        if not self.open:
            return
        schedule(
            self._app_state.send_terminal_input(data, self.session_id),
            lambda exc: self.feed(f"\r\n[gonderilemedi: {exc}]\r\n"),
        )

    # --- cizim --------------------------------------------------------------

    def feed(self, text: str) -> None:
        self.awaiting_first_output = False
        self._stream.feed(text)
        self.render()

    def render(self) -> None:
        """Gecmis + gorunen ekrani birlikte yaz.

        Bunlar ayri ayri tutuluyor: pyte'in ekrani sabit yukseklikte, yukari
        kayan satirlar history.top'a dusuyor. Ikisini birlestirmeden kaydirilacak
        bir metin olusmuyor.
        """
        lines = history_lines(self._screen) + [line.rstrip() for line in self._screen.display]
        while lines and not lines[-1]:
            lines.pop()

        bar = self.view.verticalScrollBar()
        # Kullanici yukari kaydirdiysa onu asagi zorlamiyoruz - sadece zaten
        # dipteyken takip etmeye devam ediyoruz.
        at_bottom = bar.value() >= bar.maximum() - 4
        position = bar.value()

        self.view.setPlainText("\n".join(lines))
        bar.setValue(bar.maximum() if at_bottom else min(position, bar.maximum()))


class TerminalPage(QWidget):
    """Pi'de gercek kabuklar, sekmeler halinde.

    Ajan her sekme icin ayri bir pseudo-terminal aciyor; etkilesimli programlar
    (htop, nano, sudo parola sorgusu) calisir, pyte kacis dizilerini burada
    ekrana cevirir."""

    def __init__(self, app_state: AppState) -> None:
        super().__init__()
        self._app_state = app_state

        self._banner = QLabel("")
        self._banner.setWordWrap(True)
        self._banner.setStyleSheet(muted(self, size_px=12))

        self._tabs = QTabWidget()
        self._tabs.setTabsClosable(True)
        self._tabs.setMovable(True)
        self._tabs.tabCloseRequested.connect(self._close_tab)

        self._new_button = QPushButton("Yeni sekme")
        self._new_button.clicked.connect(self.new_tab)
        self._restart_button = QPushButton("Bu sekmeyi yeniden baslat")
        self._restart_button.clicked.connect(self._restart_current)

        toolbar = QHBoxLayout()
        toolbar.addWidget(self._new_button)
        toolbar.addWidget(self._restart_button)
        toolbar.addStretch(1)

        self._status = QLabel("")
        self._status.setStyleSheet(muted(self, size_px=12))

        layout = QVBoxLayout(self)
        layout.addWidget(self._banner)
        layout.addLayout(toolbar)
        layout.addWidget(self._tabs, stretch=1)
        layout.addWidget(self._status)

        app_state.terminal_output.connect(self._on_output)
        app_state.terminal_exited.connect(self._on_exit)
        app_state.error_received.connect(self._on_error)

    # --- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        capabilities = self._app_state.capabilities
        if not capabilities.terminal:
            detail = capabilities.terminal_detail or "sebep bildirilmedi"
            self._banner.setText(f"Terminal kullanilamiyor: {detail}")
            self._banner.setStyleSheet("color: #e67e22;")
            self._new_button.setEnabled(False)
            self._restart_button.setEnabled(False)
            return

        self._banner.setText(
            f"Kabuk: {capabilities.terminal_detail} · Her sekme Pi'de ayri bir kabuk acar; "
            "SSH ile ayni seyleri yapabilirsiniz."
        )
        if self._tabs.count() == 0:
            self.new_tab()

    def new_tab(self) -> TerminalTab | None:
        if self._tabs.count() >= MAX_TABS:
            self._set_status(f"en fazla {MAX_TABS} sekme", warn=True)
            return None

        tab = TerminalTab(self._app_state, uuid.uuid4().hex)
        index = self._tabs.addTab(tab, f"Kabuk {self._tabs.count() + 1}")
        self._tabs.setCurrentIndex(index)
        tab.start()
        self._set_status("kabuk baslatiliyor...")
        return tab

    def _close_tab(self, index: int) -> None:
        tab = self._tabs.widget(index)
        if isinstance(tab, TerminalTab):
            tab.close_session()
        self._tabs.removeTab(index)
        if self._tabs.count() == 0:
            self._set_status("acik kabuk yok — 'Yeni sekme' ile baslatin")

    def _restart_current(self) -> None:
        tab = self._current_tab()
        if tab is None:
            return
        tab.close_session()
        tab.start()
        self._set_status("kabuk baslatiliyor...")

    def _current_tab(self) -> TerminalTab | None:
        widget = self._tabs.currentWidget()
        return widget if isinstance(widget, TerminalTab) else None

    def _tab_for(self, session_id: str) -> TerminalTab | None:
        for index in range(self._tabs.count()):
            tab = self._tabs.widget(index)
            if isinstance(tab, TerminalTab) and tab.session_id == session_id:
                return tab
        return None

    # --- gelen --------------------------------------------------------------

    def _on_output(self, payload: TerminalOutputPayload) -> None:
        tab = self._tab_for(payload.session_id)
        if tab is None:
            return
        if tab.awaiting_first_output:
            self._set_status(f"kabuk calisiyor — {self._app_state.capabilities.terminal_detail}")
        tab.feed(payload.data)

    def _on_exit(self, payload: TerminalExitPayload) -> None:
        tab = self._tab_for(payload.session_id)
        if tab is None:
            return
        tab.open = False
        tab.awaiting_first_output = False
        code = "?" if payload.exit_code is None else payload.exit_code
        index = self._tabs.indexOf(tab)
        if index >= 0:
            self._tabs.setTabText(index, self._tabs.tabText(index) + " (kapandi)")
        self._set_status(f"{payload.detail} (cikis kodu {code})")

    def _on_error(self, code: str, message: str) -> None:
        """Acilis bekleyen bir sekme varsa hata neredeyse kesin ona aittir.

        Ajan terminal hatalarini genel `error` zarfiyla gonderiyor; dinlemezsek
        basarisiz bir acilis "baslatiliyor" yazisiyla asili kalir.
        """
        pending = [
            self._tabs.widget(index)
            for index in range(self._tabs.count())
            if isinstance(self._tabs.widget(index), TerminalTab)
            and self._tabs.widget(index).awaiting_first_output
        ]
        if not pending:
            return
        for tab in pending:
            tab.open = False
            tab.awaiting_first_output = False
        self._set_status(f"kabuk baslatilamadi — {code}: {message}", warn=True)

    def _set_status(self, text: str, warn: bool = False) -> None:
        self._status.setText(text)
        self._status.setStyleSheet("color: #e67e22;" if warn else muted(self, size_px=12))
