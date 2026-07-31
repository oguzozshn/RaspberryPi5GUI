from __future__ import annotations

import json
import logging
import re
import shutil

from pydantic import ValidationError

from pi_protocol import (
    ContainerInfo,
    DockerActionPayload,
    DockerActionResultPayload,
    DockerListPayload,
    DockerListResultPayload,
    DockerLogsPayload,
    DockerLogsResultPayload,
    Envelope,
    MessageType,
)

from pi_agent.config import AgentConfig
from pi_agent.proc import run
from pi_agent.wire import Connection

logger = logging.getLogger("pi_agent.docker")

# `docker stop` waits 10s for the container to exit on its own before killing
# it, so actions get more headroom than a plain query.
_PROBE_TIMEOUT_SECONDS = 5
_ACTION_TIMEOUT_SECONDS = 60
_MAX_LOG_LINES = 2000

# Container names and ids come from the client. Same reasoning as unit names in
# services.py: no shell is involved, this stops a name like "--all" being read
# by the docker CLI as an option rather than a container.
_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def validate_name(container: str) -> bool:
    return bool(_NAME_PATTERN.match(container))


def is_installed() -> bool:
    return shutil.which("docker") is not None


async def probe() -> tuple[bool, str]:
    """Is there a docker daemon this agent may talk to?

    Having the CLI installed is not enough: the daemon may be stopped, or the
    agent's account may not be in the `docker` group - and group membership only
    takes effect after the service restarts, which is a confusing failure to hit
    without an explanation.
    """
    if not is_installed():
        return False, "docker kurulu degil"

    code, stdout, stderr = await run(
        ["docker", "version", "--format", "{{.Server.Version}}"],
        timeout=_PROBE_TIMEOUT_SECONDS,
    )
    if code == 0:
        return True, f"docker {stdout.strip()}"

    detail = stderr.strip() or f"exit {code}"
    if "permission denied" in detail.lower():
        return False, (
            "docker daemon'a erisim yok - kullanici 'docker' grubunda mi? "
            "(uyelik icin 'sudo systemctl restart pi-agent' gerekir)"
        )
    return False, f"docker daemon'a erisilemiyor: {detail.splitlines()[0] if detail else ''}"


def parse_containers(payload: str) -> list[ContainerInfo]:
    """Parse `docker ps --format {{json .}}`: one JSON object per line, not a
    JSON array. Fields are missing on older CLI versions, so each is optional."""
    containers: list[ContainerInfo] = []
    for line in payload.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict) or not row.get("ID"):
            continue

        state = str(row.get("State") or "")
        status = str(row.get("Status") or "")
        if not state and status:
            # Pre-20.10 CLIs have no State field; the first word of Status
            # ("Up 3 hours", "Exited (0) ...") carries the same information.
            state = status.split()[0].lower()

        containers.append(
            ContainerInfo(
                id=str(row.get("ID"))[:12],
                name=str(row.get("Names") or ""),
                image=str(row.get("Image") or ""),
                state=state,
                status=status,
                ports=str(row.get("Ports") or ""),
                created=str(row.get("CreatedAt") or ""),
            )
        )

    # Running first, then alphabetical: the ones you can act on are at the top.
    containers.sort(key=lambda c: (c.state != "running", c.name.lower()))
    return containers


# --- handlers ---------------------------------------------------------------


async def handle_list(conn: Connection, raw: dict, config: AgentConfig) -> None:
    try:
        envelope = Envelope[DockerListPayload].model_validate(raw)
    except ValidationError as exc:
        await conn.send_error("bad_request", str(exc), raw.get("id"))
        return

    available, detail = await probe()
    if not available:
        await conn.send_error("not_available", detail, envelope.id)
        return

    command = ["docker", "ps", "--no-trunc", "--format", "{{json .}}"]
    if envelope.payload.include_stopped:
        command.insert(2, "--all")

    code, stdout, stderr = await run(command)
    if code != 0:
        await conn.send_error("docker_failed", stderr.strip() or f"exit {code}", envelope.id)
        return

    await conn.send(
        MessageType.DOCKER_LIST_RESULT,
        DockerListResultPayload(containers=parse_containers(stdout)),
        envelope.id,
    )


async def handle_action(conn: Connection, raw: dict, config: AgentConfig) -> None:
    try:
        envelope = Envelope[DockerActionPayload].model_validate(raw)
    except ValidationError as exc:
        await conn.send_error("bad_request", str(exc), raw.get("id"))
        return

    container, action = envelope.payload.container, envelope.payload.action
    if not validate_name(container):
        await conn.send_error("bad_request", f"gecersiz container adi: {container!r}", envelope.id)
        return

    available, detail = await probe()
    if not available:
        await conn.send_error("not_available", detail, envelope.id)
        return

    # No sudo: the agent's account is in the docker group, and membership of
    # that group is already equivalent to root on this machine.
    code, _stdout, stderr = await run(
        ["docker", action, container], timeout=_ACTION_TIMEOUT_SECONDS
    )
    ok = code == 0
    result = "tamam" if ok else (stderr.strip() or f"exit {code}")
    logger.info("docker %s %s -> %s", action, container, "ok" if ok else result)

    await conn.send(
        MessageType.DOCKER_ACTION_RESULT,
        DockerActionResultPayload(container=container, action=action, ok=ok, detail=result),
        envelope.id,
    )


async def handle_logs(conn: Connection, raw: dict, config: AgentConfig) -> None:
    try:
        envelope = Envelope[DockerLogsPayload].model_validate(raw)
    except ValidationError as exc:
        await conn.send_error("bad_request", str(exc), raw.get("id"))
        return

    container = envelope.payload.container
    if not validate_name(container):
        await conn.send_error("bad_request", f"gecersiz container adi: {container!r}", envelope.id)
        return

    available, detail = await probe()
    if not available:
        await conn.send_error("not_available", detail, envelope.id)
        return

    lines = max(1, min(envelope.payload.lines, _MAX_LOG_LINES))
    code, stdout, stderr = await run(["docker", "logs", "--tail", str(lines), container])
    if code != 0:
        await conn.send_error("docker_failed", stderr.strip() or f"exit {code}", envelope.id)
        return

    # A container's own stderr arrives on our stderr, and most images log there.
    # Dropping it would hide exactly the lines someone opens the log viewer for;
    # the two streams are concatenated rather than interleaved by timestamp.
    combined = stdout.splitlines() + stderr.splitlines()
    await conn.send(
        MessageType.DOCKER_LOGS_RESULT,
        DockerLogsResultPayload(container=container, lines=combined[-lines:]),
        envelope.id,
    )
