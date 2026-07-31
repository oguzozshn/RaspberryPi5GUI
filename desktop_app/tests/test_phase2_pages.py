from __future__ import annotations

from pi_protocol import (
    ChatMessagePayload,
    Envelope,
    MessageType,
    ServiceInfo,
    ServiceListResultPayload,
    ServiceLogsResultPayload,
)

from desktop_app.app_state import AppState
from desktop_app.ui.pages.chat_page import ChatPage
from desktop_app.ui.pages.services_page import ServicesPage


# --- chat -------------------------------------------------------------------


def test_chat_enabled_when_clipboard_available(app_state: AppState) -> None:
    page = ChatPage(app_state)
    assert page._send_button.isEnabled()
    assert "wl-copy" in page._banner.text()


def test_chat_disabled_and_explained_without_graphical_session(bare_app_state: AppState) -> None:
    page = ChatPage(bare_app_state)
    assert not page._send_button.isEnabled()
    assert "grafik oturumu" in page._banner.text()
    assert "masaustu oturumu gerektirir" in page._banner.text()


def test_chat_shows_delivery_confirmation(app_state: AppState) -> None:
    page = ChatPage(app_state)
    page._on_message(
        ChatMessagePayload(text="gizli", source="desktop", delivered_to_clipboard=True, detail="wl-copy")
    )
    assert "panoya yazildi" in page._history.toPlainText()


def test_chat_surfaces_delivery_failure(app_state: AppState) -> None:
    page = ChatPage(app_state)
    page._on_message(
        ChatMessagePayload(text="gizli", source="desktop", delivered_to_clipboard=False, detail="xclip yok")
    )
    assert "HATA: xclip yok" in page._history.toPlainText()


def test_chat_masks_text_in_history_when_masking_is_on(app_state: AppState) -> None:
    """A password sent with masking enabled must not be readable in the log."""
    page = ChatPage(app_state)
    page._mask_button.setChecked(True)
    page._on_message(
        ChatMessagePayload(text="hunter2", source="desktop", delivered_to_clipboard=True)
    )
    history = page._history.toPlainText()
    assert "hunter2" not in history
    assert "•••••••" in history


def test_chat_escapes_html_from_the_pi(app_state: AppState) -> None:
    page = ChatPage(app_state)
    page._on_message(ChatMessagePayload(text="<b>x</b>", source="pi"))
    assert "<b>x</b>" in page._history.toPlainText(), "markup metin olarak gosterilmeli"


def test_chat_reports_clipboard_read_failure(app_state: AppState) -> None:
    page = ChatPage(app_state)
    page._on_message(ChatMessagePayload(text="", source="pi", detail="Pi'nin panosu bos"))
    assert "pano okunamadi" in page._history.toPlainText()


# --- services ---------------------------------------------------------------


def _services_payload() -> ServiceListResultPayload:
    return ServiceListResultPayload(
        services=[
            ServiceInfo(unit="ssh.service", load="loaded", active="active", sub="running",
                        description="OpenBSD Secure Shell server"),
            ServiceInfo(unit="cron.service", load="loaded", active="failed", sub="dead",
                        description="Regular background program processing"),
        ]
    )


def test_services_table_populates_and_gates_buttons(app_state: AppState) -> None:
    page = ServicesPage(app_state)
    assert not page._start_button.isEnabled(), "secim yokken aksiyonlar kapali olmali"

    page._on_services(_services_payload())
    assert page._table.rowCount() == 2
    assert page._table.item(0, 0).text() == "ssh.service"

    page._table.selectRow(0)
    assert page._start_button.isEnabled()
    assert page._selected_unit() == "ssh.service"


def test_services_page_explains_missing_systemd(bare_app_state: AppState) -> None:
    page = ServicesPage(bare_app_state)
    page.start()
    assert "systemd yok" in page._status.text()
    assert not page._filter.isEnabled()


def test_status_colour_resets_after_a_warning(bare_app_state: AppState) -> None:
    """Regression: the warning colour used to be latched by setStyleSheet and
    left every later status line orange."""
    page = ServicesPage(bare_app_state)
    page.start()
    warned = page._status.styleSheet()
    assert "e67e22" in warned

    page._on_services(_services_payload())
    assert "e67e22" not in page._status.styleSheet()


def test_service_logs_render(app_state: AppState) -> None:
    page = ServicesPage(app_state)
    page._on_logs(ServiceLogsResultPayload(unit="ssh.service", lines=["satir bir", "satir iki"]))
    assert "satir iki" in page._logs.toPlainText()
    assert "2 satir log" in page._status.text()


# --- app_state routing ------------------------------------------------------


def test_app_state_routes_service_list(app_state: AppState) -> None:
    received: list[ServiceListResultPayload] = []
    app_state.services_listed.connect(received.append)

    app_state._on_message(
        Envelope(type=MessageType.SERVICE_LIST_RESULT, payload=_services_payload()).model_dump(mode="json")
    )
    assert received[0].services[0].unit == "ssh.service"


def test_app_state_routes_chat_message(app_state: AppState) -> None:
    received: list[ChatMessagePayload] = []
    app_state.chat_message_received.connect(received.append)

    payload = ChatMessagePayload(text="merhaba", source="pi")
    app_state._on_message(
        Envelope(type=MessageType.CHAT_MESSAGE, payload=payload).model_dump(mode="json")
    )
    assert received[0].text == "merhaba"
