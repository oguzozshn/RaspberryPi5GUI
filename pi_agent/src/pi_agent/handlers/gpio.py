from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass

from pydantic import ValidationError

from pi_protocol import (
    Envelope,
    GpioListResultPayload,
    GpioPin,
    GpioReleasePayload,
    GpioReleaseResultPayload,
    GpioWritePayload,
    GpioWriteResultPayload,
    MessageType,
)

from pi_agent.config import AgentConfig
from pi_agent.wire import Connection

logger = logging.getLogger("pi_agent.gpio")

# BCM number -> (position on the 40-pin header, what the pin is normally wired
# to). Power and ground pins are not listed: they are not GPIO lines at all.
HEADER: dict[int, tuple[int, str]] = {
    2: (3, "I2C1 SDA"),
    3: (5, "I2C1 SCL"),
    4: (7, ""),
    14: (8, "UART TX"),
    15: (10, "UART RX"),
    17: (11, ""),
    18: (12, "PCM CLK / PWM0"),
    27: (13, ""),
    22: (15, ""),
    23: (16, ""),
    24: (18, ""),
    10: (19, "SPI0 MOSI"),
    9: (21, "SPI0 MISO"),
    25: (22, ""),
    11: (23, "SPI0 SCLK"),
    8: (24, "SPI0 CE0"),
    7: (26, "SPI0 CE1"),
    0: (27, "HAT ID EEPROM SD"),
    1: (28, "HAT ID EEPROM SC"),
    5: (29, ""),
    6: (31, ""),
    12: (32, "PWM0"),
    13: (33, "PWM1"),
    19: (35, "PCM FS"),
    16: (36, ""),
    26: (37, ""),
    20: (38, "PCM DIN"),
    21: (40, "PCM DOUT"),
}

# Driving the HAT ID EEPROM lines can break HAT detection on the next boot and
# no ordinary wiring needs them, so writes are refused outright rather than
# merely warned about.
WRITE_BLOCKED: dict[int, str] = {
    0: "HAT ID EEPROM pini",
    1: "HAT ID EEPROM pini",
}

# The header bank is the RP1 south bridge on a Pi 5 and the SoC pin controller
# on older boards. Its chip *number* moved between kernel releases (gpiochip4 ->
# gpiochip0 during Bookworm), so probe by label instead of hardcoding a node.
_CHIP_LABELS = ("pinctrl-rp1", "pinctrl-bcm2835", "pinctrl-bcm2711", "pinctrl-bcm2712")
_CHIP_CANDIDATES = range(0, 6)
_MIN_HEADER_LINES = 28

# lgpio line-info flag bits.
_FLAG_KERNEL = 1  # some other consumer holds this line
_FLAG_OUTPUT = 2

@dataclass(frozen=True)
class _Chip:
    handle: int
    number: int
    label: str


_lock = threading.RLock()
_module = None
_module_error = ""
_chip: _Chip | None = None
# Lines this agent currently holds, BCM -> "output". Kept so a refresh does not
# release a pin the user deliberately drove high.
_claimed: dict[int, str] = {}


# --- lgpio plumbing ---------------------------------------------------------


def _load_module():
    """Import lgpio lazily. It is a Linux-only, compiled dependency, so the
    agent has to keep working (with GPIO switched off) when it is absent -
    including on a Windows dev box."""
    global _module, _module_error
    if _module is None and not _module_error:
        try:
            import lgpio  # noqa: PLC0415 - optional dependency, imported on demand
        except Exception as exc:  # noqa: BLE001 - ImportError, or a broken build
            _module_error = f"lgpio kullanilamiyor: {exc}"
        else:
            _module = lgpio
    return _module


def _chip_info(lgpio, handle: int) -> tuple[str, int]:
    """(label, line count) from gpio_get_chip_info, which returns
    [status, lines, name, label]."""
    try:
        info = lgpio.gpio_get_chip_info(handle)
    except Exception:  # noqa: BLE001
        return "", 0
    label = str(info[3]) if len(info) > 3 else ""
    lines = int(info[1]) if len(info) > 1 else 0
    return label, lines


def _close(lgpio, handle: int) -> None:
    try:
        lgpio.gpiochip_close(handle)
    except Exception:  # noqa: BLE001 - nothing useful to do if closing fails
        pass


def _open_chip() -> _Chip | None:
    global _chip
    if _chip is not None:
        return _chip
    lgpio = _load_module()
    if lgpio is None:
        return None

    fallback: _Chip | None = None
    for number in _CHIP_CANDIDATES:
        try:
            handle = lgpio.gpiochip_open(number)
        except Exception:  # noqa: BLE001 - node missing, or no permission
            continue
        label, lines = _chip_info(lgpio, handle)
        candidate = _Chip(handle=handle, number=number, label=label)

        if any(label.startswith(known) for known in _CHIP_LABELS):
            if fallback is not None:
                _close(lgpio, fallback.handle)
            _chip = candidate
            return _chip
        # An unfamiliar board still works if the chip is wide enough to cover
        # the header; keep the first such one in case no label ever matches.
        if fallback is None and lines >= _MIN_HEADER_LINES:
            fallback = candidate
        else:
            _close(lgpio, handle)

    _chip = fallback
    return _chip


def _describe() -> str:
    chip = _open_chip()
    if chip is not None:
        return f"{chip.label or 'bilinmeyen yonga'} (/dev/gpiochip{chip.number})"
    if _module is None:
        return _module_error or "lgpio kurulu degil"
    return "/dev/gpiochip* acilamadi - kullanici 'gpio' grubunda mi?"


def describe() -> str:
    with _lock:
        return _describe()


def is_available() -> bool:
    with _lock:
        return _open_chip() is not None


def reset() -> None:
    """Release every line held here and forget the chip handle. Used by tests;
    the kernel does the same automatically when the agent process exits."""
    global _chip, _module, _module_error
    with _lock:
        lgpio = _module
        if lgpio is not None and _chip is not None:
            for bcm in list(_claimed):
                try:
                    lgpio.gpio_free(_chip.handle, bcm)
                except Exception:  # noqa: BLE001
                    pass
            _close(lgpio, _chip.handle)
        _claimed.clear()
        _chip = None
        _module = None
        _module_error = ""


# --- reading / writing ------------------------------------------------------


def _read_level(lgpio, chip: _Chip, bcm: int, ours: bool, busy: bool, is_output: bool) -> int | None:
    if ours:
        try:
            return int(lgpio.gpio_read(chip.handle, bcm))
        except Exception:  # noqa: BLE001
            return None
    if busy:
        return None  # another consumer owns the line; claiming it would fail
    if is_output:
        # Configured as an output but held by nobody - typically a pin some
        # earlier process drove and then exited, because the RP1 pad keeps its
        # direction and level after the line is released. Sampling it would mean
        # claiming it as an input, which drops that drive: opening this tab would
        # silently switch off whatever it was holding. Report it as unknown
        # instead; writing to it is still allowed and takes it over explicitly.
        return None

    try:
        lgpio.gpio_claim_input(chip.handle, bcm)
    except Exception:  # noqa: BLE001
        return None
    try:
        return int(lgpio.gpio_read(chip.handle, bcm))
    except Exception:  # noqa: BLE001
        return None
    finally:
        # Free immediately: holding 26 lines open would make the agent show up
        # as the consumer of the whole header to every other program on the Pi.
        try:
            lgpio.gpio_free(chip.handle, bcm)
        except Exception:  # noqa: BLE001
            pass


def _read_pin(lgpio, chip: _Chip, bcm: int) -> GpioPin:
    physical, reserved_for = HEADER[bcm]
    flags, consumer = 0, ""
    try:
        info = lgpio.gpio_get_line_info(chip.handle, bcm)
        flags = int(info[2])
        consumer = str(info[4] or "")
    except Exception:  # noqa: BLE001 - report the pin as unknown rather than drop it
        pass

    ours = _claimed.get(bcm)
    busy = bool(flags & _FLAG_KERNEL)
    is_output = bool(flags & _FLAG_OUTPUT)
    mode = "output" if (ours == "output" or is_output) else "input"
    return GpioPin(
        bcm=bcm,
        physical=physical,
        mode=mode,
        value=_read_level(
            lgpio, chip, bcm, ours=ours is not None, busy=busy, is_output=is_output
        ),
        consumer=consumer,
        reserved_for=reserved_for,
        writable=bcm not in WRITE_BLOCKED,
    )


def read_all() -> list[GpioPin]:
    """Snapshot every header GPIO, ordered by physical pin so the table reads
    like the board does."""
    with _lock:
        lgpio = _load_module()
        chip = _open_chip()
        if lgpio is None or chip is None:
            return []
        order = sorted(HEADER, key=lambda bcm: HEADER[bcm][0])
        return [_read_pin(lgpio, chip, bcm) for bcm in order]


def write(bcm: int, value: int) -> tuple[bool, str]:
    if bcm not in HEADER:
        return False, f"BCM {bcm} 40-pin baslikta bir GPIO degil"
    if bcm in WRITE_BLOCKED:
        return False, f"BCM {bcm}: {WRITE_BLOCKED[bcm]}, yazma engellendi"
    if value not in (0, 1):
        return False, f"gecersiz seviye: {value}"

    with _lock:
        lgpio = _load_module()
        chip = _open_chip()
        if lgpio is None or chip is None:
            return False, _describe()

        if _claimed.get(bcm) != "output":
            try:
                lgpio.gpio_claim_output(chip.handle, bcm, value)
            except Exception as exc:  # noqa: BLE001 - busy line, or no permission
                return False, f"pin ayrilamadi (baska bir surec kullaniyor olabilir): {exc}"
            _claimed[bcm] = "output"
            return True, f"BCM {bcm} cikis olarak ayrildi, seviye {value}"

        try:
            lgpio.gpio_write(chip.handle, bcm, value)
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)
        return True, f"BCM {bcm} <- {value}"


def release(bcm: int) -> tuple[bool, str]:
    """Stop driving a pin and hand it back as an input.

    Claiming a line as an input is what actually resets the RP1 pad - merely
    freeing it leaves the pin driving, which is why stopping the agent does not
    switch anything off. The read path used to do this claim implicitly for
    every pin and disturbed outputs nobody asked it to touch; here it is the
    explicit point of the request.
    """
    if bcm not in HEADER:
        return False, f"BCM {bcm} 40-pin baslikta bir GPIO degil"
    if bcm in WRITE_BLOCKED:
        return False, f"BCM {bcm}: {WRITE_BLOCKED[bcm]}, dokunulmuyor"

    with _lock:
        lgpio = _load_module()
        chip = _open_chip()
        if lgpio is None or chip is None:
            return False, _describe()

        if bcm in _claimed:
            try:
                lgpio.gpio_free(chip.handle, bcm)
            except Exception:  # noqa: BLE001 - re-claiming below is what matters
                pass
            _claimed.pop(bcm, None)

        try:
            lgpio.gpio_claim_input(chip.handle, bcm)
        except Exception as exc:  # noqa: BLE001 - held by another process
            return False, f"pin girise alinamadi (baska bir surec kullaniyor olabilir): {exc}"
        try:
            lgpio.gpio_free(chip.handle, bcm)
        except Exception:  # noqa: BLE001
            pass
        return True, f"BCM {bcm} girise alindi, artik surulmuyor"


# --- handlers ---------------------------------------------------------------


async def handle_list(conn: Connection, raw: dict, config: AgentConfig) -> None:
    if not await asyncio.to_thread(is_available):
        await conn.send_error("not_available", describe(), raw.get("id"))
        return

    pins = await asyncio.to_thread(read_all)
    await conn.send(
        MessageType.GPIO_LIST_RESULT,
        GpioListResultPayload(pins=pins, detail=describe()),
        raw.get("id"),
    )


async def handle_write(conn: Connection, raw: dict, config: AgentConfig) -> None:
    try:
        envelope = Envelope[GpioWritePayload].model_validate(raw)
    except ValidationError as exc:
        await conn.send_error("bad_request", str(exc), raw.get("id"))
        return

    bcm, value = envelope.payload.bcm, envelope.payload.value
    if not await asyncio.to_thread(is_available):
        await conn.send_error("not_available", describe(), envelope.id)
        return

    ok, detail = await asyncio.to_thread(write, bcm, value)
    logger.info("gpio write BCM %s <- %s: %s", bcm, value, "ok" if ok else detail)
    await conn.send(
        MessageType.GPIO_WRITE_RESULT,
        GpioWriteResultPayload(bcm=bcm, value=value, ok=ok, detail=detail),
        envelope.id,
    )


async def handle_release(conn: Connection, raw: dict, config: AgentConfig) -> None:
    try:
        envelope = Envelope[GpioReleasePayload].model_validate(raw)
    except ValidationError as exc:
        await conn.send_error("bad_request", str(exc), raw.get("id"))
        return

    bcm = envelope.payload.bcm
    if not await asyncio.to_thread(is_available):
        await conn.send_error("not_available", describe(), envelope.id)
        return

    ok, detail = await asyncio.to_thread(release, bcm)
    logger.info("gpio release BCM %s: %s", bcm, "ok" if ok else detail)
    await conn.send(
        MessageType.GPIO_RELEASE_RESULT,
        GpioReleaseResultPayload(bcm=bcm, ok=ok, detail=detail),
        envelope.id,
    )
