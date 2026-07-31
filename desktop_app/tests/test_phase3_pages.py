from __future__ import annotations

from pi_protocol import (
    Envelope,
    GpioListResultPayload,
    GpioPin,
    GpioWriteResultPayload,
    MessageType,
    PowerActionResultPayload,
)

from desktop_app.app_state import AppState
from desktop_app.ui.pages.power_page import PowerPage


def _gpio_payload() -> GpioListResultPayload:
    return GpioListResultPayload(
        detail="pinctrl-rp1 (/dev/gpiochip4)",
        pins=[
            GpioPin(bcm=2, physical=3, mode="input", value=1, consumer="", reserved_for="I2C1 SDA"),
            GpioPin(bcm=17, physical=11, mode="output", value=0),
            GpioPin(bcm=10, physical=19, mode="input", value=None, consumer="spi0",
                    reserved_for="SPI0 MOSI"),
            GpioPin(bcm=0, physical=27, mode="input", value=0,
                    reserved_for="HAT ID EEPROM SD", writable=False),
        ],
    )


# --- gpio table -------------------------------------------------------------


def test_gpio_table_populates_and_gates_write_buttons(app_state: AppState) -> None:
    page = PowerPage(app_state)
    assert not page._high_button.isEnabled(), "secim yokken yazma kapali olmali"

    page._on_gpio(_gpio_payload())
    assert page._table.rowCount() == 4
    assert page._table.item(0, 1).text() == "GPIO2"
    assert page._table.item(1, 3).text() == "0"

    page._table.selectRow(1)
    assert page._high_button.isEnabled()
    assert page._low_button.isEnabled()
    assert page._selected_pin().bcm == 17


def test_write_buttons_stay_disabled_for_a_blocked_pin(app_state: AppState) -> None:
    """The HAT ID EEPROM pins are refused by the agent too; the UI should not
    offer a button that can only come back as an error."""
    page = PowerPage(app_state)
    page._on_gpio(_gpio_payload())

    page._table.selectRow(3)
    assert page._selected_pin().bcm == 0
    assert not page._high_button.isEnabled()
    assert not page._low_button.isEnabled()


def test_pins_owned_by_another_driver_render_as_unknown(app_state: AppState) -> None:
    page = PowerPage(app_state)
    page._on_gpio(_gpio_payload())

    assert page._table.item(2, 3).text() == "—"
    assert page._table.item(2, 4).text() == "spi0"
    assert "1 pin baska bir surucude" in page._gpio_status.text()


def test_gpio_section_explains_a_pi_without_lgpio(bare_app_state: AppState) -> None:
    page = PowerPage(bare_app_state)
    page.start()
    assert "GPIO kullanilamiyor" in page._gpio_banner.text()
    assert "lgpio" in page._gpio_banner.text()
    assert not page._refresh_button.isEnabled()


def test_gpio_write_failure_is_surfaced(app_state: AppState) -> None:
    page = PowerPage(app_state)
    page._on_gpio_write(
        GpioWriteResultPayload(bcm=18, value=1, ok=False, detail="pin ayrilamadi (busy)")
    )
    assert "GPIO18 yazilamadi" in page._gpio_status.text()
    assert "e67e22" in page._gpio_status.styleSheet()


# --- power ------------------------------------------------------------------


def test_power_buttons_are_disabled_without_systemd(bare_app_state: AppState) -> None:
    page = PowerPage(bare_app_state)
    page.start()
    assert not page._reboot_button.isEnabled()
    assert not page._shutdown_button.isEnabled()
    assert "systemd yok" in page._power_status.text()


def test_power_success_explains_the_disconnect_that_follows(app_state: AppState) -> None:
    """A reboot always ends with the socket dropping; saying so up front keeps
    it from reading as a failure."""
    page = PowerPage(app_state)
    page._on_power_result(
        PowerActionResultPayload(action="reboot", ok=True, detail="komut kabul edildi")
    )
    assert "Baglantinin kesilmesi normaldir" in page._power_status.text()
    assert "e67e22" not in page._power_status.styleSheet()


def test_power_failure_is_surfaced_as_a_warning(app_state: AppState) -> None:
    page = PowerPage(app_state)
    page._on_power_result(
        PowerActionResultPayload(action="reboot", ok=False, detail="sudo: a password is required")
    )
    assert "basarisiz" in page._power_status.text()
    assert "e67e22" in page._power_status.styleSheet()


# --- app_state routing ------------------------------------------------------


def test_app_state_routes_and_caches_gpio_list(app_state: AppState) -> None:
    received: list[GpioListResultPayload] = []
    app_state.gpio_listed.connect(received.append)

    app_state._on_message(
        Envelope(type=MessageType.GPIO_LIST_RESULT, payload=_gpio_payload()).model_dump(mode="json")
    )
    assert received[0].pins[0].bcm == 2
    assert app_state.latest_gpio is not None, "sekmeye sonradan gecen kullanici bekletilmemeli"


def test_app_state_routes_power_result(app_state: AppState) -> None:
    received: list[PowerActionResultPayload] = []
    app_state.power_action_done.connect(received.append)

    payload = PowerActionResultPayload(action="shutdown", ok=True, detail="komut kabul edildi")
    app_state._on_message(
        Envelope(type=MessageType.POWER_ACTION_RESULT, payload=payload).model_dump(mode="json")
    )
    assert received[0].action == "shutdown"
