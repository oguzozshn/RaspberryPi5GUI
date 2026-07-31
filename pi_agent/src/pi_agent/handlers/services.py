from __future__ import annotations

import json
import logging
import re
import shutil

from pydantic import ValidationError

from pi_protocol import (
    Envelope,
    MessageType,
    ServiceActionPayload,
    ServiceActionResultPayload,
    ServiceInfo,
    ServiceListPayload,
    ServiceListResultPayload,
    ServiceLogsPayload,
    ServiceLogsResultPayload,
)

from pi_agent.config import AgentConfig
from pi_agent.proc import run
from pi_agent.wire import Connection

logger = logging.getLogger("pi_agent.services")

_MAX_LOG_LINES = 2000

# Unit names arrive from the client. Nothing is run through a shell, so this is
# not about shell metacharacters - it stops a name like "--all" or "-M host"
# from being read by systemctl as an option instead of a unit.
_UNIT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9@._:\\-]{0,255}$")


def is_available() -> bool:
    return shutil.which("systemctl") is not None


def validate_unit(unit: str) -> bool:
    return bool(_UNIT_PATTERN.match(unit))


def parse_units(payload: str) -> list[ServiceInfo]:
    """Parse `systemctl list-units --output=json`. Fields are occasionally null
    for units in odd states, so every one is coerced to a string."""
    try:
        rows = json.loads(payload)
    except json.JSONDecodeError:
        return []

    services: list[ServiceInfo] = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("unit"):
            continue
        services.append(
            ServiceInfo(
                unit=str(row.get("unit")),
                load=str(row.get("load") or ""),
                active=str(row.get("active") or ""),
                sub=str(row.get("sub") or ""),
                description=str(row.get("description") or ""),
            )
        )
    services.sort(key=lambda s: s.unit.lower())
    return services


# --- handlers ---------------------------------------------------------------


async def handle_list(conn: Connection, raw: dict, config: AgentConfig) -> None:
    try:
        envelope = Envelope[ServiceListPayload].model_validate(raw)
    except ValidationError as exc:
        await conn.send_error("bad_request", str(exc), raw.get("id"))
        return

    if not is_available():
        await conn.send_error("not_available", "systemd bu sistemde yok", envelope.id)
        return

    code, stdout, stderr = await run(
        ["systemctl", "list-units", "--type=service", "--all", "--no-pager", "--output=json"]
    )
    if code != 0:
        await conn.send_error("systemctl_failed", stderr.strip() or f"exit {code}", envelope.id)
        return

    services = parse_units(stdout)
    if pattern := envelope.payload.pattern.strip().lower():
        services = [
            s for s in services if pattern in s.unit.lower() or pattern in s.description.lower()
        ]

    await conn.send(
        MessageType.SERVICE_LIST_RESULT, ServiceListResultPayload(services=services), envelope.id
    )


async def handle_action(conn: Connection, raw: dict, config: AgentConfig) -> None:
    try:
        envelope = Envelope[ServiceActionPayload].model_validate(raw)
    except ValidationError as exc:
        await conn.send_error("bad_request", str(exc), raw.get("id"))
        return

    unit = envelope.payload.unit
    if not validate_unit(unit):
        await conn.send_error("bad_request", f"gecersiz unit adi: {unit!r}", envelope.id)
        return
    if not is_available():
        await conn.send_error("not_available", "systemd bu sistemde yok", envelope.id)
        return

    # install.sh grants passwordless sudo for exactly these systemctl verbs.
    code, _stdout, stderr = await run(["sudo", "-n", "systemctl", envelope.payload.action, unit])
    ok = code == 0
    detail = "tamam" if ok else (stderr.strip() or f"exit {code}")
    logger.info("service %s %s -> %s", envelope.payload.action, unit, "ok" if ok else detail)

    await conn.send(
        MessageType.SERVICE_ACTION_RESULT,
        ServiceActionResultPayload(
            unit=unit, action=envelope.payload.action, ok=ok, detail=detail
        ),
        envelope.id,
    )


async def handle_logs(conn: Connection, raw: dict, config: AgentConfig) -> None:
    try:
        envelope = Envelope[ServiceLogsPayload].model_validate(raw)
    except ValidationError as exc:
        await conn.send_error("bad_request", str(exc), raw.get("id"))
        return

    unit = envelope.payload.unit
    if not validate_unit(unit):
        await conn.send_error("bad_request", f"gecersiz unit adi: {unit!r}", envelope.id)
        return

    lines = max(1, min(envelope.payload.lines, _MAX_LOG_LINES))
    code, stdout, stderr = await run(
        ["sudo", "-n", "journalctl", "-u", unit, "-n", str(lines), "--no-pager", "--output=short-iso"]
    )
    if code != 0:
        await conn.send_error("journalctl_failed", stderr.strip() or f"exit {code}", envelope.id)
        return

    await conn.send(
        MessageType.SERVICE_LOGS_RESULT,
        ServiceLogsResultPayload(unit=unit, lines=stdout.splitlines()),
        envelope.id,
    )
