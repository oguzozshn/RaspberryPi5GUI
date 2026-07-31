from __future__ import annotations

import pytest

from pi_agent.handlers import services

# Shape of `systemctl list-units --type=service --all --output=json` on
# Raspberry Pi OS Bookworm (systemd 252).
SYSTEMCTL_JSON = """[
  {"unit":"ssh.service","load":"loaded","active":"active","sub":"running",
   "description":"OpenBSD Secure Shell server","following":null,"job_id":0},
  {"unit":"apt-daily.service","load":"loaded","active":"inactive","sub":"dead",
   "description":"Daily apt download activities","following":null,"job_id":0},
  {"unit":"Bluetooth.service","load":"loaded","active":"active","sub":"running",
   "description":"Bluetooth service","following":null,"job_id":0}
]"""


def test_parse_units_extracts_fields_and_sorts_case_insensitively() -> None:
    units = services.parse_units(SYSTEMCTL_JSON)
    assert [u.unit for u in units] == ["apt-daily.service", "Bluetooth.service", "ssh.service"]

    ssh = next(u for u in units if u.unit == "ssh.service")
    assert (ssh.load, ssh.active, ssh.sub) == ("loaded", "active", "running")
    assert ssh.description == "OpenBSD Secure Shell server"


def test_parse_units_coerces_null_fields() -> None:
    units = services.parse_units('[{"unit":"x.service","load":null,"active":null,'
                                 '"sub":null,"description":null}]')
    assert units[0].unit == "x.service"
    assert units[0].active == ""


def test_parse_units_skips_rows_without_a_unit_name() -> None:
    assert services.parse_units('[{"description":"orphan"}, "junk", 42]') == []


def test_parse_units_returns_empty_on_malformed_json() -> None:
    assert services.parse_units("not json at all") == []


@pytest.mark.parametrize(
    "unit",
    ["ssh.service", "getty@tty1.service", "user-1000.slice", "my_app.service", "a"],
)
def test_validate_unit_accepts_real_names(unit: str) -> None:
    assert services.validate_unit(unit)


@pytest.mark.parametrize(
    "unit",
    [
        "--all",  # would be read as an option, not a unit
        "-M container",
        "",
        "ssh.service extra",  # a second argument smuggled in
        "unit;reboot",
        "../../etc/passwd",
        "a" * 300,
    ],
)
def test_validate_unit_rejects_option_like_and_malformed_names(unit: str) -> None:
    assert not services.validate_unit(unit)
