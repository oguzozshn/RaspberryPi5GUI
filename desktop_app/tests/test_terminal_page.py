from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QKeyEvent

from pi_protocol import TerminalExitPayload, TerminalOutputPayload

from desktop_app.app_state import AppState
from desktop_app.ui.pages.terminal_page import (
    TerminalPage,
    is_copy,
    is_paste,
    key_to_bytes,
    paste_payload,
)


def _key(key: Qt.Key, text: str = "", ctrl: bool = False) -> QKeyEvent:
    modifiers = (
        Qt.KeyboardModifier.ControlModifier if ctrl else Qt.KeyboardModifier.NoModifier
    )
    return QKeyEvent(QKeyEvent.Type.KeyPress, key.value, modifiers, text)


# --- key mapping ------------------------------------------------------------


def test_printable_keys_pass_through(qapp) -> None:
    assert key_to_bytes(_key(Qt.Key.Key_A, "a")) == "a"
    assert key_to_bytes(_key(Qt.Key.Key_Space, " ")) == " "


def test_enter_sends_carriage_return(qapp) -> None:
    """Kabuk satir sonu olarak \\r bekler; \\n ile komut calismaz."""
    assert key_to_bytes(_key(Qt.Key.Key_Return)) == "\r"


def test_ctrl_c_sends_the_interrupt_byte(qapp) -> None:
    """Ctrl+C, on plandaki programa SIGINT olarak ulasmali."""
    assert key_to_bytes(_key(Qt.Key.Key_C, "c", ctrl=True)) == "\x03"
    assert key_to_bytes(_key(Qt.Key.Key_D, "d", ctrl=True)) == "\x04"


def test_arrows_send_escape_sequences(qapp) -> None:
    assert key_to_bytes(_key(Qt.Key.Key_Up)) == "\x1b[A"
    assert key_to_bytes(_key(Qt.Key.Key_Left)) == "\x1b[D"


def test_backspace_sends_del(qapp) -> None:
    assert key_to_bytes(_key(Qt.Key.Key_Backspace)) == "\x7f"


# --- yapistirma -------------------------------------------------------------


def test_paste_shortcuts_are_recognised(qapp) -> None:
    """Ctrl+Shift+V terminal gelenegi, Ctrl+V Windows refleksi, Shift+Insert
    ikisinden de eski; ucu de kabul ediliyor."""
    ctrl_shift = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
    assert is_paste(_key(Qt.Key.Key_V, "v", ctrl=True))
    assert is_paste(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_V.value, ctrl_shift, "V"))
    assert is_paste(
        QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Insert.value,
                  Qt.KeyboardModifier.ShiftModifier, "")
    )


def test_plain_v_is_not_a_paste(qapp) -> None:
    assert not is_paste(_key(Qt.Key.Key_V, "v"))


def test_ctrl_c_is_not_a_copy(qapp) -> None:
    """Ctrl+C kopyalama degil SIGINT; kopyalama Ctrl+Shift+C."""
    ctrl_shift = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
    assert not is_copy(_key(Qt.Key.Key_C, "c", ctrl=True))
    assert is_copy(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_C.value, ctrl_shift, "C"))


def test_paste_converts_newlines_for_the_shell() -> None:
    """Kabuk satir sonu olarak \\r bekler; \\n ile yapistirilan komut calismaz."""
    assert paste_payload("ls -la\nwhoami\n") == "ls -la\rwhoami\r"
    assert paste_payload("ls\r\nps") == "ls\rps"


def _spy_input(monkeypatch: pytest.MonkeyPatch, app_state: AppState) -> list[str]:
    """AppState katmanindan yakala: TerminalView, _send_input'un bagli
    referansini kurulusta aldigi icin sayfayi yamalamak ise yaramaz."""
    sent: list[str] = []

    def fake(data: str):
        sent.append(data)

        async def noop() -> None:
            return None

        return noop()

    monkeypatch.setattr(app_state, "send_terminal_input", fake)
    return sent


def test_pasting_sends_the_clipboard_to_the_shell(app_state: AppState, monkeypatch: pytest.MonkeyPatch) -> None:
    page = TerminalPage(app_state)
    page.open_session()
    sent = _spy_input(monkeypatch, app_state)
    QGuiApplication.clipboard().setText("sudo systemctl restart pi-agent\n")

    page._view.paste_clipboard()
    assert sent == ["sudo systemctl restart pi-agent\r"]


def test_pasting_an_empty_clipboard_sends_nothing(app_state: AppState, monkeypatch: pytest.MonkeyPatch) -> None:
    page = TerminalPage(app_state)
    page.open_session()
    sent = _spy_input(monkeypatch, app_state)
    QGuiApplication.clipboard().setText("")

    page._view.paste_clipboard()
    assert sent == []


# --- screen rendering -------------------------------------------------------


def test_output_is_rendered(app_state: AppState) -> None:
    page = TerminalPage(app_state)
    page._on_output(TerminalOutputPayload(data="merhaba\r\n"))
    assert "merhaba" in page._view.toPlainText()


def test_cursor_movement_redraws_instead_of_appending(app_state: AppState) -> None:
    """Kabuk imleci geri alip satiri yeniden yaziyor; eklemeli bir gorunum
    burada 'kirmizi'yi de 'yesil'i de gosterirdi."""
    page = TerminalPage(app_state)
    page._on_output(TerminalOutputPayload(data="kirmizi"))
    page._on_output(TerminalOutputPayload(data="\r\x1b[Kyesil"))

    text = page._view.toPlainText()
    assert "yesil" in text
    assert "kirmizi" not in text


def test_screen_clear_is_honoured(app_state: AppState) -> None:
    page = TerminalPage(app_state)
    page._on_output(TerminalOutputPayload(data="eski satir\r\n"))
    page._on_output(TerminalOutputPayload(data="\x1b[2J\x1b[H"))
    assert "eski satir" not in page._view.toPlainText()


# --- session state ----------------------------------------------------------


def test_buttons_track_the_session(app_state: AppState) -> None:
    page = TerminalPage(app_state)
    assert page._open_button.isEnabled()
    assert not page._close_button.isEnabled()

    page.open_session()
    assert not page._open_button.isEnabled()
    assert page._close_button.isEnabled()

    page._on_exit(TerminalExitPayload(exit_code=0, detail="kabuk kapandi"))
    assert page._open_button.isEnabled()
    assert not page._close_button.isEnabled()
    assert "cikis kodu 0" in page._status.text()


def test_input_is_dropped_when_no_session_is_open(app_state: AppState, monkeypatch: pytest.MonkeyPatch) -> None:
    page = TerminalPage(app_state)
    sent: list[str] = []

    def fake(data: str):
        sent.append(data)

        async def noop() -> None:
            return None

        return noop()

    monkeypatch.setattr(app_state, "send_terminal_input", fake)

    page._send_input("ls\r")
    assert sent == [], "oturum yokken tusa basmak mesaj uretmemeli"

    page.open_session()
    page._send_input("ls\r")
    assert sent == ["ls\r"]


def test_starting_message_clears_once_the_shell_answers(app_state: AppState) -> None:
    """Kullanici bildirdi: 'kabuk baslatiliyor' yazisi ekranda asili kaliyordu.
    Ajan ayri bir 'acildi' mesaji gondermiyor, ilk cikti bunun isareti."""
    page = TerminalPage(app_state)
    page.open_session()
    assert "baslatiliyor" in page._status.text()

    page._on_output(TerminalOutputPayload(data="paarax@paarnax:~ $ "))
    assert "baslatiliyor" not in page._status.text()
    assert "calisiyor" in page._status.text()


def test_a_failed_open_is_reported_not_left_hanging(app_state: AppState) -> None:
    """Kabuk hic acilamazsa ajan `error` gonderiyor; sekme bunu dinlemezse
    kullanici sonsuza kadar 'baslatiliyor' gorurdu."""
    page = TerminalPage(app_state)
    page.open_session()

    page._on_error("terminal_failed", "pty acilamadi")
    assert "baslatilamadi" in page._status.text()
    assert "pty acilamadi" in page._status.text()
    assert page._open_button.isEnabled(), "tekrar denenebilmeli"
    assert not page._close_button.isEnabled()


def test_unrelated_errors_do_not_touch_a_running_session(app_state: AppState) -> None:
    page = TerminalPage(app_state)
    page.open_session()
    page._on_output(TerminalOutputPayload(data="$ "))

    page._on_error("docker_failed", "baska bir sekmenin hatasi")
    assert "baslatilamadi" not in page._status.text()
    assert not page._open_button.isEnabled(), "oturum acik kalmali"


def test_page_explains_a_pi_without_a_shell(bare_app_state: AppState) -> None:
    page = TerminalPage(bare_app_state)
    page.start()
    assert "Terminal kullanilamiyor" in page._banner.text()
    assert not page._open_button.isEnabled()
