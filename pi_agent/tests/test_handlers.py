from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from pi_agent.handlers import processes, stats
from pi_protocol import (
    AuthRequestPayload,
    Envelope,
    FilesListPayload,
    MessageType,
    ProcessListPayload,
    StatsUpdatePayload,
)

from .conftest import TOKEN


def _authenticated(client: TestClient):
    ws = client.websocket_connect("/ws").__enter__()
    ws.send_json(
        Envelope(type=MessageType.AUTH_REQUEST, payload=AuthRequestPayload(token=TOKEN)).model_dump(mode="json")
    )
    assert ws.receive_json()["type"] == MessageType.AUTH_OK.value
    return ws


def test_stats_collect_returns_real_values() -> None:
    payload = stats.collect()
    assert isinstance(payload, StatsUpdatePayload)
    assert payload.hostname
    assert payload.uptime_seconds > 0
    assert 0 <= payload.memory.percent <= 100
    assert payload.memory.total_bytes > 0
    assert payload.disks, "en az bir disk bolumu raporlanmali"


def test_process_list(client: TestClient) -> None:
    ws = _authenticated(client)
    request = Envelope(type=MessageType.PROCESS_LIST, payload=ProcessListPayload(limit=5, sort_by="cpu"))
    ws.send_json(request.model_dump(mode="json"))

    reply = ws.receive_json()
    assert reply["type"] == MessageType.PROCESS_LIST_RESULT.value
    assert reply["id"] == request.id, "yanit istek id'sini echo etmeli"
    procs = reply["payload"]["processes"]
    assert 0 < len(procs) <= 5
    assert reply["payload"]["total_count"] >= len(procs)
    assert all(p["name"] for p in procs)
    cpu_values = [p["cpu_percent"] for p in procs]
    assert cpu_values == sorted(cpu_values, reverse=True), "sort_by=cpu azalan sirali olmali"


def test_files_list(client: TestClient, tmp_path: Path) -> None:
    (tmp_path / "alpha.txt").write_text("hello")
    (tmp_path / "subdir").mkdir()

    ws = _authenticated(client)
    request = Envelope(type=MessageType.FILES_LIST, payload=FilesListPayload(path=str(tmp_path)))
    ws.send_json(request.model_dump(mode="json"))

    reply = ws.receive_json()
    assert reply["type"] == MessageType.FILES_LIST_RESULT.value
    names = [e["name"] for e in reply["payload"]["entries"]]
    assert names == ["subdir", "alpha.txt"], "dizinler once, sonra alfabetik"
    assert reply["payload"]["parent"] is not None


def test_files_list_not_found(client: TestClient, tmp_path: Path) -> None:
    ws = _authenticated(client)
    request = Envelope(type=MessageType.FILES_LIST, payload=FilesListPayload(path=str(tmp_path / "yok")))
    ws.send_json(request.model_dump(mode="json"))

    reply = ws.receive_json()
    assert reply["type"] == MessageType.ERROR.value
    assert reply["payload"]["code"] == "not_found"


def test_slow_handler_does_not_block_other_requests(client: TestClient, tmp_path: Path) -> None:
    """Regression: handlers used to be awaited inline in the receive loop, so a
    ~2s process.list starved every other request on the connection."""
    ws = _authenticated(client)

    slow = Envelope(type=MessageType.PROCESS_LIST, payload=ProcessListPayload(limit=60))
    fast = Envelope(type=MessageType.FILES_LIST, payload=FilesListPayload(path=str(tmp_path)))
    ws.send_json(slow.model_dump(mode="json"))
    ws.send_json(fast.model_dump(mode="json"))

    first, second = ws.receive_json(), ws.receive_json()
    by_id = {first["id"]: first, second["id"]: second}
    assert by_id[fast.id]["type"] == MessageType.FILES_LIST_RESULT.value
    assert by_id[slow.id]["type"] == MessageType.PROCESS_LIST_RESULT.value
    assert first["id"] == fast.id, "hizli istek yavas olani beklememeli"


def test_kill_terminates_a_real_child_process() -> None:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        ok, detail = processes.kill(child.pid, force=False)
        assert ok, detail
        assert child.wait(timeout=5) is not None
    finally:
        if child.poll() is None:
            child.kill()


def test_kill_reports_missing_process() -> None:
    ok, detail = processes.kill(9_999_999, force=False)
    assert ok is False
    assert "bulunamadi" in detail


def test_auth_ok_carries_capabilities(client: TestClient) -> None:
    """Capabilities ride inside auth.ok rather than a follow-up push, so the
    client cannot start rendering before it knows what the Pi supports."""
    with client.websocket_connect("/ws") as ws:
        ws.send_json(
            Envelope(type=MessageType.AUTH_REQUEST, payload=AuthRequestPayload(token=TOKEN)).model_dump(mode="json")
        )
        reply = ws.receive_json()

    caps = reply["payload"]["capabilities"]
    assert set(caps) >= {"clipboard", "clipboard_detail", "systemd", "docker", "gpio"}
    assert isinstance(caps["clipboard"], bool)
    assert caps["clipboard_detail"], "kullaniciya gosterilecek bir aciklama olmali"


def test_unknown_message_type_does_not_close_connection(client: TestClient) -> None:
    ws = _authenticated(client)
    ws.send_json({"type": "bogus.type", "id": "abc", "ts": 0, "payload": {}})
    reply = ws.receive_json()
    assert reply["type"] == MessageType.ERROR.value
    assert reply["payload"]["code"] == "unknown_type"
    assert reply["id"] == "abc"
