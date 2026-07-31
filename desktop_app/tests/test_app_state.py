from __future__ import annotations

from pi_protocol import (
    CpuStats,
    Envelope,
    ErrorPayload,
    FileEntry,
    FilesListResultPayload,
    MemoryStats,
    MessageType,
    ProcessInfo,
    ProcessListResultPayload,
    StatsUpdatePayload,
    SwapStats,
)

from desktop_app.app_state import AppState


def _stats_envelope() -> dict:
    payload = StatsUpdatePayload(
        hostname="raspberrypi",
        uptime_seconds=3600.0,
        load_avg=(0.5, 0.4, 0.3),
        cpu=CpuStats(percent=12.5, per_core=[10.0, 15.0, 12.0, 13.0], temperature_c=47.8),
        memory=MemoryStats(total_bytes=8_000_000_000, used_bytes=2_000_000_000, available_bytes=6_000_000_000, percent=25.0),
        swap=SwapStats(total_bytes=0, used_bytes=0, percent=0.0),
        disks=[],
    )
    return Envelope(type=MessageType.STATS_UPDATE, payload=payload).model_dump(mode="json")


def test_stats_update_parsed_and_cached(app_state: AppState) -> None:
    received: list[StatsUpdatePayload] = []
    app_state.stats_updated.connect(received.append)

    app_state._on_message(_stats_envelope())

    assert len(received) == 1
    assert received[0].cpu.temperature_c == 47.8
    assert app_state.latest_stats is received[0], "sonraki sayfa acilisi icin onbellege alinmali"


def test_process_result_parsed(app_state: AppState) -> None:
    received: list[ProcessListResultPayload] = []
    app_state.processes_updated.connect(received.append)

    payload = ProcessListResultPayload(
        processes=[
            ProcessInfo(
                pid=1, name="systemd", username="root", cpu_percent=0.5,
                memory_percent=1.2, memory_rss_bytes=10_000, status="sleeping", cmdline="/sbin/init",
            )
        ],
        total_count=1,
    )
    app_state._on_message(Envelope(type=MessageType.PROCESS_LIST_RESULT, payload=payload).model_dump(mode="json"))

    assert received[0].processes[0].name == "systemd"
    assert app_state.latest_processes is received[0]


def test_files_result_parsed(app_state: AppState) -> None:
    received: list[FilesListResultPayload] = []
    app_state.files_listed.connect(received.append)

    payload = FilesListResultPayload(
        path="/home/pi",
        parent="/home",
        entries=[FileEntry(name="a.txt", path="/home/pi/a.txt", is_dir=False, size_bytes=5, modified_ts=0.0, permissions="-rw-r--r--")],
    )
    app_state._on_message(Envelope(type=MessageType.FILES_LIST_RESULT, payload=payload).model_dump(mode="json"))

    assert received[0].entries[0].name == "a.txt"


def test_error_emitted(app_state: AppState) -> None:
    received: list[tuple[str, str]] = []
    app_state.error_received.connect(lambda code, msg: received.append((code, msg)))

    payload = ErrorPayload(code="not_found", message="yol bulunamadi")
    app_state._on_message(Envelope(type=MessageType.ERROR, payload=payload).model_dump(mode="json"))

    assert received == [("not_found", "yol bulunamadi")]


def test_unknown_type_is_ignored(app_state: AppState) -> None:
    app_state._on_message({"type": "bogus", "id": "x", "ts": 0.0, "payload": {}})
    assert app_state.latest_stats is None


def test_malformed_payload_does_not_raise(app_state: AppState) -> None:
    # A schema-violating stats frame must not take down the UI.
    app_state._on_message({"type": MessageType.STATS_UPDATE.value, "id": "x", "ts": 0.0, "payload": {}})
    assert app_state.latest_stats is None
