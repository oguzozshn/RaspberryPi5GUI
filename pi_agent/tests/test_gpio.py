from __future__ import annotations

from typing import Iterator

import pytest

from pi_agent.handlers import gpio


class FakeLgpio:
    """Stand-in for the lgpio C extension, which only exists on a Pi.

    Models the parts the handler leans on: chips are identified by label rather
    than by number, a claimed line reports itself as in-use, and claiming a line
    someone else already holds raises.
    """

    LINE_FLAG_KERNEL = 1
    LINE_FLAG_OUTPUT = 2

    def __init__(self, chips: dict[int, tuple[str, int]] | None = None) -> None:
        # chip number -> (label, line count)
        self.chips = chips if chips is not None else {0: ("pinctrl-rp1", 54)}
        self.levels: dict[int, int] = {}
        self.foreign: dict[int, str] = {}  # lines held by some other consumer
        self.claims: dict[int, str] = {}  # lines held by us: "input" / "output"
        self.open_handles: set[int] = set()
        self.closed: list[int] = []

    # --- chip -------------------------------------------------------------

    def gpiochip_open(self, number: int) -> int:
        if number not in self.chips:
            raise OSError(f"/dev/gpiochip{number} yok")
        handle = 100 + number
        self.open_handles.add(handle)
        return handle

    def gpiochip_close(self, handle: int) -> None:
        self.open_handles.discard(handle)
        self.closed.append(handle)

    def gpio_get_chip_info(self, handle: int) -> list:
        label, lines = self.chips[handle - 100]
        return [0, lines, f"gpiochip{handle - 100}", label]

    def gpio_get_line_info(self, handle: int, gpio: int) -> list:
        flags = 0
        consumer = ""
        if gpio in self.foreign:
            flags |= self.LINE_FLAG_KERNEL
            consumer = self.foreign[gpio]
        if gpio in self.claims:
            flags |= self.LINE_FLAG_KERNEL
            consumer = "lgpio"
            if self.claims[gpio] == "output":
                flags |= self.LINE_FLAG_OUTPUT
        return [0, gpio, flags, f"GPIO{gpio}", consumer]

    # --- lines ------------------------------------------------------------

    def _guard(self, gpio: int) -> None:
        if gpio in self.foreign:
            raise OSError(f"GPIO busy: {gpio}")

    def gpio_claim_input(self, handle: int, gpio: int, flags: int = 0) -> None:
        self._guard(gpio)
        self.claims[gpio] = "input"

    def gpio_claim_output(self, handle: int, gpio: int, level: int = 0, flags: int = 0) -> None:
        self._guard(gpio)
        self.claims[gpio] = "output"
        self.levels[gpio] = level

    def gpio_free(self, handle: int, gpio: int) -> None:
        self.claims.pop(gpio, None)

    def gpio_read(self, handle: int, gpio: int) -> int:
        if gpio not in self.claims:
            raise OSError(f"GPIO not claimed: {gpio}")
        return self.levels.get(gpio, 0)

    def gpio_write(self, handle: int, gpio: int, level: int) -> None:
        if self.claims.get(gpio) != "output":
            raise OSError(f"GPIO not an output: {gpio}")
        self.levels[gpio] = level


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeLgpio]:
    gpio.reset()
    stub = FakeLgpio()
    monkeypatch.setattr(gpio, "_module", stub)
    yield stub
    gpio.reset()


# --- availability -----------------------------------------------------------


def test_unavailable_without_lgpio(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Pi (or dev box) without the compiled extension must degrade to
    gpio=false with a reason, not blow up the whole connection."""
    gpio.reset()
    monkeypatch.setattr(gpio, "_module_error", "lgpio kullanilamiyor: No module named 'lgpio'")
    assert gpio.is_available() is False
    assert "lgpio" in gpio.describe()
    assert gpio.read_all() == []
    gpio.reset()


def test_unavailable_when_no_chip_can_be_opened(monkeypatch: pytest.MonkeyPatch) -> None:
    gpio.reset()
    monkeypatch.setattr(gpio, "_module", FakeLgpio(chips={}))
    assert gpio.is_available() is False
    assert "gpio" in gpio.describe()
    gpio.reset()


def test_chip_is_found_by_label_not_by_number(monkeypatch: pytest.MonkeyPatch) -> None:
    """gpiochip4 on kernel 6.1, gpiochip0 on 6.6 - only the label is stable."""
    gpio.reset()
    stub = FakeLgpio(chips={0: ("gpio-brcmstb", 32), 4: ("pinctrl-rp1", 54)})
    monkeypatch.setattr(gpio, "_module", stub)

    assert gpio.is_available() is True
    assert "/dev/gpiochip4" in gpio.describe()
    assert 100 in stub.closed, "eslesmeyen yonga kapatilmali"
    gpio.reset()


# --- reading ----------------------------------------------------------------


def test_read_all_covers_the_header_in_physical_pin_order(fake: FakeLgpio) -> None:
    pins = gpio.read_all()
    assert len(pins) == len(gpio.HEADER)
    assert [p.physical for p in pins] == sorted(p.physical for p in pins)
    assert pins[0].physical == 3 and pins[0].bcm == 2
    assert pins[-1].physical == 40 and pins[-1].bcm == 21


def test_read_all_labels_reserved_pins(fake: FakeLgpio) -> None:
    by_bcm = {pin.bcm: pin for pin in gpio.read_all()}
    assert by_bcm[2].reserved_for == "I2C1 SDA"
    assert by_bcm[14].reserved_for == "UART TX"
    assert by_bcm[4].reserved_for == ""


def test_read_all_releases_lines_it_only_sampled(fake: FakeLgpio) -> None:
    """Regression guard: leaving the claims in place would make the agent look
    like the consumer of the whole header to everything else on the Pi."""
    gpio.read_all()
    assert fake.claims == {}


def test_pins_held_by_another_driver_report_no_value(fake: FakeLgpio) -> None:
    fake.foreign[10] = "spi0"
    by_bcm = {pin.bcm: pin for pin in gpio.read_all()}
    assert by_bcm[10].value is None
    assert by_bcm[10].consumer == "spi0"
    assert by_bcm[4].value == 0, "diger pinler okunmaya devam etmeli"


def test_written_pin_keeps_its_claim_and_level_across_a_refresh(fake: FakeLgpio) -> None:
    assert gpio.write(17, 1) == (True, "BCM 17 cikis olarak ayrildi, seviye 1")

    by_bcm = {pin.bcm: pin for pin in gpio.read_all()}
    assert by_bcm[17].mode == "output"
    assert by_bcm[17].value == 1
    assert fake.claims.get(17) == "output", "surulen pin birakilmamali"


# --- writing ----------------------------------------------------------------


def test_write_toggles_an_already_claimed_pin(fake: FakeLgpio) -> None:
    gpio.write(17, 1)
    ok, detail = gpio.write(17, 0)
    assert ok, detail
    assert fake.levels[17] == 0


def test_write_refuses_the_hat_eeprom_pins(fake: FakeLgpio) -> None:
    for bcm in (0, 1):
        ok, detail = gpio.write(bcm, 1)
        assert not ok
        assert "EEPROM" in detail
    assert fake.claims == {}


def test_write_refuses_pins_outside_the_header(fake: FakeLgpio) -> None:
    for bcm in (-1, 28, 47):
        ok, detail = gpio.write(bcm, 1)
        assert not ok
        assert "baslikta" in detail


def test_write_reports_a_busy_line_instead_of_raising(fake: FakeLgpio) -> None:
    fake.foreign[18] = "pwm"
    ok, detail = gpio.write(18, 1)
    assert not ok
    assert "baska bir surec" in detail


def test_write_rejects_levels_other_than_0_and_1(fake: FakeLgpio) -> None:
    ok, detail = gpio.write(17, 5)
    assert not ok
    assert "seviye" in detail
