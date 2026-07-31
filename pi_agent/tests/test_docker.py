from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pi_agent.handlers import docker
from pi_protocol import (
    AuthRequestPayload,
    DockerActionPayload,
    DockerListPayload,
    DockerLogsPayload,
    Envelope,
    MessageType,
)

from .conftest import TOKEN

# `docker ps --all --no-trunc --format {{json .}}` emits one object per line,
# not a JSON array. Shape as of Docker 24 on Raspberry Pi OS Bookworm.
DOCKER_PS_NDJSON = """\
{"ID":"9f1c2","Names":"pihole","Image":"pihole/pihole:latest","State":"running","Status":"Up 3 hours","Ports":"0.0.0.0:53->53/tcp","CreatedAt":"2026-07-01 10:00:00 +0300 +03"}
{"ID":"3ab77","Names":"backup","Image":"alpine:3.19","State":"exited","Status":"Exited (0) 2 days ago","Ports":"","CreatedAt":"2026-06-20 08:00:00 +0300 +03"}
{"ID":"c0ffe","Names":"Grafana","Image":"grafana/grafana","State":"running","Status":"Up 5 minutes","Ports":"0.0.0.0:3000->3000/tcp","CreatedAt":"2026-07-31 09:00:00 +0300 +03"}
"""


def _authenticated(client: TestClient):
    ws = client.websocket_connect("/ws").__enter__()
    ws.send_json(
        Envelope(type=MessageType.AUTH_REQUEST, payload=AuthRequestPayload(token=TOKEN)).model_dump(mode="json")
    )
    assert ws.receive_json()["type"] == MessageType.AUTH_OK.value
    return ws


def _available(monkeypatch: pytest.MonkeyPatch, ok: bool = True, detail: str = "docker 24.0.7") -> None:
    async def probe() -> tuple[bool, str]:
        return ok, detail

    monkeypatch.setattr(docker, "probe", probe)


class _RecordingRun:
    def __init__(self, code: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.code, self.stdout, self.stderr = code, stdout, stderr
        self.commands: list[list[str]] = []

    async def __call__(self, command: list[str], timeout: float = 30) -> tuple[int, str, str]:
        self.commands.append(command)
        return self.code, self.stdout, self.stderr


# --- parsing ----------------------------------------------------------------


def test_parse_containers_puts_running_first_then_sorts_case_insensitively() -> None:
    containers = docker.parse_containers(DOCKER_PS_NDJSON)
    assert [c.name for c in containers] == ["Grafana", "pihole", "backup"]

    pihole = next(c for c in containers if c.name == "pihole")
    assert pihole.image == "pihole/pihole:latest"
    assert pihole.state == "running"
    assert pihole.ports.startswith("0.0.0.0:53")


def test_parse_containers_derives_state_from_status_on_older_clients() -> None:
    """Docker CLIs before 20.10 have no State field; Status still carries it."""
    containers = docker.parse_containers(
        '{"ID":"abc","Names":"old","Image":"busybox","Status":"Exited (137) 1 hour ago"}'
    )
    assert containers[0].state == "exited"


def test_parse_containers_skips_junk_lines_and_keeps_the_rest() -> None:
    payload = 'not json\n\n{"Names":"orphan"}\n' + DOCKER_PS_NDJSON.splitlines()[0]
    containers = docker.parse_containers(payload)
    assert [c.name for c in containers] == ["pihole"]


def test_parse_containers_returns_empty_for_no_containers() -> None:
    assert docker.parse_containers("") == []


@pytest.mark.parametrize("name", ["pihole", "my_app.1", "grafana-oss", "9f1c2ab", "a"])
def test_validate_name_accepts_real_names(name: str) -> None:
    assert docker.validate_name(name)


@pytest.mark.parametrize(
    "name",
    ["--all", "-f status=running", "", "pihole extra", "pihole;reboot", "../etc", "a" * 200],
)
def test_validate_name_rejects_option_like_and_malformed_names(name: str) -> None:
    assert not docker.validate_name(name)


# --- handlers ---------------------------------------------------------------


def test_list_returns_parsed_containers(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _available(monkeypatch)
    runner = _RecordingRun(stdout=DOCKER_PS_NDJSON)
    monkeypatch.setattr(docker, "run", runner)

    ws = _authenticated(client)
    request = Envelope(type=MessageType.DOCKER_LIST, payload=DockerListPayload(include_stopped=True))
    ws.send_json(request.model_dump(mode="json"))

    reply = ws.receive_json()
    assert reply["type"] == MessageType.DOCKER_LIST_RESULT.value
    assert reply["id"] == request.id
    assert len(reply["payload"]["containers"]) == 3
    assert "--all" in runner.commands[0]


def test_list_without_stopped_containers_drops_the_all_flag(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _available(monkeypatch)
    runner = _RecordingRun(stdout="")
    monkeypatch.setattr(docker, "run", runner)

    ws = _authenticated(client)
    ws.send_json(
        Envelope(type=MessageType.DOCKER_LIST, payload=DockerListPayload(include_stopped=False)).model_dump(mode="json")
    )
    ws.receive_json()
    assert "--all" not in runner.commands[0]


def test_missing_daemon_is_explained_rather_than_failing_silently(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _available(monkeypatch, ok=False, detail="docker daemon'a erisim yok - kullanici 'docker' grubunda mi?")
    ws = _authenticated(client)
    ws.send_json(
        Envelope(type=MessageType.DOCKER_LIST, payload=DockerListPayload()).model_dump(mode="json")
    )

    reply = ws.receive_json()
    assert reply["payload"]["code"] == "not_available"
    assert "docker" in reply["payload"]["message"]


def test_action_runs_the_requested_verb(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _available(monkeypatch)
    runner = _RecordingRun()
    monkeypatch.setattr(docker, "run", runner)

    ws = _authenticated(client)
    ws.send_json(
        Envelope(
            type=MessageType.DOCKER_ACTION,
            payload=DockerActionPayload(container="pihole", action="restart"),
        ).model_dump(mode="json")
    )

    reply = ws.receive_json()
    assert runner.commands == [["docker", "restart", "pihole"]]
    assert reply["payload"]["ok"] is True


def test_action_rejects_an_option_like_container_name(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A name starting with '-' would be read by the CLI as a flag, not a
    container - reject it before docker ever sees it."""
    _available(monkeypatch)
    runner = _RecordingRun()
    monkeypatch.setattr(docker, "run", runner)

    ws = _authenticated(client)
    ws.send_json(
        {"type": "docker.action", "id": "x1", "ts": 0,
         "payload": {"container": "--all", "action": "stop"}}
    )

    reply = ws.receive_json()
    assert reply["payload"]["code"] == "bad_request"
    assert runner.commands == []


def test_action_failure_carries_the_daemon_message(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _available(monkeypatch)
    monkeypatch.setattr(docker, "run", _RecordingRun(code=1, stderr="No such container: gone"))

    ws = _authenticated(client)
    ws.send_json(
        Envelope(
            type=MessageType.DOCKER_ACTION,
            payload=DockerActionPayload(container="gone", action="start"),
        ).model_dump(mode="json")
    )

    reply = ws.receive_json()
    assert reply["payload"]["ok"] is False
    assert "No such container" in reply["payload"]["detail"]


def test_logs_include_the_containers_stderr(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Most images log to stderr; dropping it would leave the viewer empty for
    exactly the containers someone is trying to debug."""
    _available(monkeypatch)
    monkeypatch.setattr(
        docker, "run", _RecordingRun(stdout="stdout satiri\n", stderr="hata satiri\n")
    )

    ws = _authenticated(client)
    ws.send_json(
        Envelope(
            type=MessageType.DOCKER_LOGS, payload=DockerLogsPayload(container="pihole", lines=50)
        ).model_dump(mode="json")
    )

    reply = ws.receive_json()
    assert reply["payload"]["lines"] == ["stdout satiri", "hata satiri"]


def test_logs_line_count_is_capped(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _available(monkeypatch)
    runner = _RecordingRun()
    monkeypatch.setattr(docker, "run", runner)

    ws = _authenticated(client)
    ws.send_json(
        Envelope(
            type=MessageType.DOCKER_LOGS,
            payload=DockerLogsPayload(container="pihole", lines=10_000_000),
        ).model_dump(mode="json")
    )
    ws.receive_json()
    assert runner.commands[0] == ["docker", "logs", "--tail", "2000", "pihole"]
