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


def _output(page: TerminalPage, data: str, session_id: str | None = None) -> None:
    tab = page._current_tab()
    page._on_output(
        TerminalOutputPayload(data=data, session_id=session_id or tab.session_id)
    )


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


def test_pasting_sends_the_clipboard_to_the_shell(app_state: AppState, monkeypatch: pytest.MonkeyPatch) -> None:
    page = TerminalPage(app_state)
    page.start()
    sent: list[tuple] = []

    def fake(data: str, session_id: str = ""):
        sent.append((data, session_id))

        async def noop() -> None:
            return None

        return noop()

    monkeypatch.setattr(app_state, "send_terminal_input", fake)
    QGuiApplication.clipboard().setText("sudo systemctl restart pi-agent\n")

    page._current_tab().view.paste_clipboard()
    assert sent and sent[0][0] == "sudo systemctl restart pi-agent\r"


# --- ekran ve gecmis --------------------------------------------------------


def test_output_is_rendered(app_state: AppState) -> None:
    page = TerminalPage(app_state)
    page.start()
    _output(page, "merhaba\r\n")
    assert "merhaba" in page._current_tab().view.toPlainText()


def test_cursor_movement_redraws_instead_of_appending(app_state: AppState) -> None:
    """Kabuk imleci geri alip satiri yeniden yaziyor; eklemeli bir gorunum
    burada 'kirmizi'yi de 'yesil'i de gosterirdi."""
    page = TerminalPage(app_state)
    page.start()
    _output(page, "kirmizi")
    _output(page, "\r\x1b[Kyesil")

    text = page._current_tab().view.toPlainText()
    assert "yesil" in text
    assert "kirmizi" not in text


def test_lines_scrolled_off_the_screen_are_kept(app_state: AppState) -> None:
    """Kullanici bildirdi: terminalde yukari kaydirilamiyordu. pyte yalnizca
    gorunen ekrani tutar; ekrandan kayan satirlar saklanmazsa kaydiracak bir sey
    olmaz."""
    page = TerminalPage(app_state)
    page.start()
    for i in range(1, 121):
        _output(page, f"satir {i}\r\n")

    text = page._current_tab().view.toPlainText()
    assert "satir 120" in text, "son satir gorunmeli"
    assert "satir 1\n" in text, "ekrandan kayan satirlar gecmiste durmali"
    assert text.count("\n") > 60, "gecmis, ekran yuksekliginden uzun olmali"


# --- sekmeler ---------------------------------------------------------------


def test_first_tab_opens_with_the_page(app_state: AppState) -> None:
    page = TerminalPage(app_state)
    page.start()
    assert page._tabs.count() == 1
    assert page._current_tab().open


def test_tabs_have_separate_sessions_and_screens(app_state: AppState) -> None:
    page = TerminalPage(app_state)
    page.start()
    first = page._current_tab()
    second = page.new_tab()

    assert second is not None
    assert first.session_id != second.session_id, "her sekme ayri kabuk"

    page._on_output(TerminalOutputPayload(data="birinci", session_id=first.session_id))
    page._on_output(TerminalOutputPayload(data="ikinci", session_id=second.session_id))

    assert "birinci" in first.view.toPlainText()
    assert "birinci" not in second.view.toPlainText()
    assert "ikinci" in second.view.toPlainText()


def test_output_for_an_unknown_session_is_ignored(app_state: AppState) -> None:
    page = TerminalPage(app_state)
    page.start()
    page._on_output(TerminalOutputPayload(data="baskasinin ciktisi", session_id="yok-boyle"))
    assert "baskasinin" not in page._current_tab().view.toPlainText()


def test_closing_a_tab_removes_it(app_state: AppState) -> None:
    page = TerminalPage(app_state)
    page.start()
    page.new_tab()
    assert page._tabs.count() == 2

    page._close_tab(1)
    assert page._tabs.count() == 1


def test_tab_count_is_capped(app_state: AppState) -> None:
    """Her sekme Pi'de gercek bir surec; sinirsiz acmak makineyi doldurur."""
    page = TerminalPage(app_state)
    page.start()
    for _ in range(20):
        page.new_tab()

    assert page._tabs.count() <= 8
    assert "en fazla" in page._status.text()


def test_exit_marks_only_its_own_tab(app_state: AppState) -> None:
    page = TerminalPage(app_state)
    page.start()
    first = page._current_tab()
    second = page.new_tab()

    page._on_exit(TerminalExitPayload(exit_code=0, detail="kabuk kapandi", session_id=first.session_id))
    assert not first.open
    assert second.open, "diger sekme etkilenmemeli"


def test_a_failed_open_is_reported_not_left_hanging(app_state: AppState) -> None:
    """Kabuk hic acilamazsa ajan `error` gonderiyor; dinlemezsek kullanici
    sonsuza kadar 'baslatiliyor' gorurdu."""
    page = TerminalPage(app_state)
    page.start()

    page._on_error("terminal_failed", "pty acilamadi")
    assert "baslatilamadi" in page._status.text()
    assert not page._current_tab().open


def test_unrelated_errors_do_not_touch_a_running_session(app_state: AppState) -> None:
    page = TerminalPage(app_state)
    page.start()
    _output(page, "$ ")

    page._on_error("docker_failed", "baska bir sekmenin hatasi")
    assert "baslatilamadi" not in page._status.text()
    assert page._current_tab().open


def test_page_explains_a_pi_without_a_shell(bare_app_state: AppState) -> None:
    page = TerminalPage(bare_app_state)
    page.start()
    assert "Terminal kullanilamiyor" in page._banner.text()
    assert not page._new_button.isEnabled()
    assert page._tabs.count() == 0
