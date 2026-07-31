from __future__ import annotations

import logging
import shutil

from pydantic import ValidationError

from pi_protocol import (
    Envelope,
    MessageType,
    PowerActionPayload,
    PowerActionResultPayload,
)

from pi_agent.config import AgentConfig
from pi_agent.proc import run
from pi_agent.wire import Connection

logger = logging.getLogger("pi_agent.power")

# systemd normally returns as soon as the job is queued, but the shutdown
# transaction can start killing units before we get to reply - keep the wait
# short so a handler task cannot sit around after the socket is gone.
_TIMEOUT_SECONDS = 15

# Exactly the two argv forms install.sh whitelists in /etc/sudoers.d/pi-agent.
# Nothing here is built from client input: the client only picks a dict key.
COMMANDS: dict[str, list[str]] = {
    "reboot": ["sudo", "-n", "systemctl", "reboot"],
    "shutdown": ["sudo", "-n", "systemctl", "poweroff"],
}


def is_available() -> bool:
    return shutil.which("systemctl") is not None


async def handle(conn: Connection, raw: dict, config: AgentConfig) -> None:
    try:
        envelope = Envelope[PowerActionPayload].model_validate(raw)
    except ValidationError as exc:
        await conn.send_error("bad_request", str(exc), raw.get("id"))
        return

    action = envelope.payload.action
    if not is_available():
        await conn.send_error("not_available", "systemd bu sistemde yok", envelope.id)
        return

    logger.warning("power %s requested by %s", action, conn.client_ip)
    code, _stdout, stderr = await run(COMMANDS[action], timeout=_TIMEOUT_SECONDS)
    ok = code == 0
    detail = "komut kabul edildi" if ok else (stderr.strip() or f"exit {code}")

    # On success the Pi is already going down, so this reply is best-effort: the
    # socket may die first and the client then just sees the disconnect. A
    # failure (sudo rule missing, say) reliably makes it back, which is the case
    # the user actually needs told.
    try:
        await conn.send(
            MessageType.POWER_ACTION_RESULT,
            PowerActionResultPayload(action=action, ok=ok, detail=detail),
            envelope.id,
        )
    except Exception:  # noqa: BLE001 - socket torn down by the shutdown itself
        logger.info("power %s result could not be delivered; system is going down", action)
