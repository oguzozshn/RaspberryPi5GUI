from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pi_agent.handlers import gpio, power
from pi_protocol import (
    AuthRequestPayload,
    Envelope,
    GpioWritePayload,
    MessageType,
    PowerActionPayload,
)

from .conftest import TOKEN

SUDOERS = Path(__file__).resolve().parents[1] / "scripts" / "sudoers.d_pi-agent"


def _authenticated(client: TestClient):
    ws = client.websocket_connect("/ws").__enter__()
    ws.send_json(
        Envelope(type=MessageType.AUTH_REQUEST, payload=AuthRequestPayload(token=TOKEN)).model_dump(mode="json")
    )
    assert ws.receive_json()["type"] == MessageType.AUTH_OK.value
    return ws


class _RecordingRun:
    """Replacement for pi_agent.proc.run that records argv instead of actually
    rebooting the machine running the tests."""

    def __init__(self, code: int = 0, stderr: str = "") -> None:
        self.code = code
        self.stderr = stderr
        self.commands: list[list[str]] = []

    async def __call__(self, command: list[str], timeout: float = 30) -> tuple[int, str, str]:
        self.commands.append(command)
        return self.code, "", self.stderr


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> _RecordingRun:
    recorder = _RecordingRun()
    monkeypatch.setattr(power, "run", recorder)
    monkeypatch.setattr(power, "is_available", lambda: True)
    return recorder


# --- command shape ----------------------------------------------------------


def test_power_commands_are_covered_by_the_sudoers_rule() -> None:
    """The agent runs unattended: a verb that install.sh does not whitelist
    would fail with a password prompt on the Pi and nowhere else."""
    rule = SUDOERS.read_text(encoding="utf-8")
    for command in power.COMMANDS.values():
        assert command[:2] == ["sudo", "-n"], "asla interaktif sudo olmamali"
        assert f"/usr/bin/{' '.join(command[2:])}" in rule, command


# --- handler ----------------------------------------------------------------


def test_reboot_runs_systemctl_reboot_and_acknowledges(client: TestClient, runner: _RecordingRun) -> None:
    ws = _authenticated(client)
    request = Envelope(type=MessageType.POWER_ACTION, payload=PowerActionPayload(action="reboot"))
    ws.send_json(request.model_dump(mode="json"))

    reply = ws.receive_json()
    assert runner.commands == [["sudo", "-n", "systemctl", "reboot"]]
    assert reply["type"] == MessageType.POWER_ACTION_RESULT.value
    assert reply["id"] == request.id
    assert reply["payload"]["ok"] is True


def test_shutdown_maps_to_poweroff(client: TestClient, runner: _RecordingRun) -> None:
    ws = _authenticated(client)
    ws.send_json(
        Envelope(type=MessageType.POWER_ACTION, payload=PowerActionPayload(action="shutdown")).model_dump(mode="json")
    )
    ws.receive_json()
    assert runner.commands == [["sudo", "-n", "systemctl", "poweroff"]]


def test_power_failure_is_reported_with_the_stderr(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing sudoers rule is the one failure the user must actually see -
    it comes back before the Pi goes anywhere."""
    monkeypatch.setattr(power, "run", _RecordingRun(code=1, stderr="sudo: a password is required"))
    monkeypatch.setattr(power, "is_available", lambda: True)

    ws = _authenticated(client)
    ws.send_json(
        Envelope(type=MessageType.POWER_ACTION, payload=PowerActionPayload(action="reboot")).model_dump(mode="json")
    )
    reply = ws.receive_json()
    assert reply["payload"]["ok"] is False
    assert "password is required" in reply["payload"]["detail"]


def test_unknown_power_action_is_rejected_without_running_anything(
    client: TestClient, runner: _RecordingRun
) -> None:
    ws = _authenticated(client)
    ws.send_json({"type": "power.action", "id": "x1", "ts": 0, "payload": {"action": "rm -rf /"}})

    reply = ws.receive_json()
    assert reply["type"] == MessageType.ERROR.value
    assert reply["payload"]["code"] == "bad_request"
    assert runner.commands == []


def test_power_reports_not_available_without_systemd(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(power, "is_available", lambda: False)
    ws = _authenticated(client)
    ws.send_json(
        Envelope(type=MessageType.POWER_ACTION, payload=PowerActionPayload(action="reboot")).model_dump(mode="json")
    )
    reply = ws.receive_json()
    assert reply["payload"]["code"] == "not_available"


# --- gpio over the wire -----------------------------------------------------


def test_gpio_write_is_refused_when_the_pi_has_no_gpio(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gpio, "is_available", lambda: False)
    ws = _authenticated(client)
    ws.send_json(
        Envelope(type=MessageType.GPIO_WRITE, payload=GpioWritePayload(bcm=17, value=1)).model_dump(mode="json")
    )
    reply = ws.receive_json()
    assert reply["type"] == MessageType.ERROR.value
    assert reply["payload"]["code"] == "not_available"


def test_gpio_write_rejects_a_level_outside_0_and_1(client: TestClient) -> None:
    """Caught by the schema, before the handler ever reaches the hardware."""
    ws = _authenticated(client)
    ws.send_json({"type": "gpio.write", "id": "x2", "ts": 0, "payload": {"bcm": 17, "value": 7}})

    reply = ws.receive_json()
    assert reply["type"] == MessageType.ERROR.value
    assert reply["payload"]["code"] == "bad_request"
