from __future__ import annotations

import asyncio

import psutil
from pydantic import ValidationError

from pi_protocol import (
    Envelope,
    MessageType,
    ProcessInfo,
    ProcessKillPayload,
    ProcessKillResultPayload,
    ProcessListPayload,
    ProcessListResultPayload,
)

from pi_agent.config import AgentConfig
from pi_agent.wire import Connection

_ATTRS = ["pid", "name", "username", "cpu_percent", "memory_percent", "memory_info", "status", "cmdline"]

_primed = False


async def _prime() -> None:
    """Process.cpu_percent() is delta-based and returns 0.0 on its first call.
    process_iter reuses cached Process objects, so one throwaway pass plus a
    short wait makes the first real request return meaningful numbers."""
    global _primed
    if _primed:
        return
    for proc in psutil.process_iter(["cpu_percent"]):
        pass
    await asyncio.sleep(0.2)
    _primed = True


def collect(limit: int, sort_by: str) -> ProcessListResultPayload:
    processes: list[ProcessInfo] = []
    for proc in psutil.process_iter(_ATTRS):
        info = proc.info
        try:
            cmdline = " ".join(info.get("cmdline") or [])
        except (TypeError, psutil.Error):
            cmdline = ""
        memory_info = info.get("memory_info")
        processes.append(
            ProcessInfo(
                pid=info["pid"],
                name=info.get("name") or "?",
                username=info.get("username"),
                cpu_percent=info.get("cpu_percent") or 0.0,
                memory_percent=info.get("memory_percent") or 0.0,
                memory_rss_bytes=getattr(memory_info, "rss", 0),
                status=info.get("status") or "unknown",
                cmdline=cmdline,
            )
        )

    total = len(processes)
    key = {
        "cpu": lambda p: -p.cpu_percent,
        "memory": lambda p: -p.memory_percent,
        "pid": lambda p: p.pid,
        "name": lambda p: p.name.lower(),
    }[sort_by]
    processes.sort(key=key)
    return ProcessListResultPayload(processes=processes[:limit], total_count=total)


async def handle(conn: Connection, raw: dict, config: AgentConfig) -> None:
    try:
        envelope = Envelope[ProcessListPayload].model_validate(raw)
    except ValidationError as exc:
        await conn.send_error("bad_request", str(exc), raw.get("id"))
        return

    await _prime()
    payload = await asyncio.to_thread(collect, envelope.payload.limit, envelope.payload.sort_by)
    await conn.send(MessageType.PROCESS_LIST_RESULT, payload, envelope.id)


def kill(pid: int, force: bool) -> tuple[bool, str]:
    """Signal a process. Deliberately not run under sudo: the agent can only
    reach processes its own account owns, so a stolen pairing token cannot be
    used to kill system daemons."""
    try:
        proc = psutil.Process(pid)
        name = proc.name()
        proc.kill() if force else proc.terminate()
    except psutil.NoSuchProcess:
        return False, f"process bulunamadi: {pid}"
    except psutil.AccessDenied:
        return False, f"izin yok (baska bir kullaniciya ait olabilir): {pid}"
    except psutil.Error as exc:
        return False, str(exc)

    try:
        proc.wait(timeout=3)
    except psutil.TimeoutExpired:
        verb = "SIGKILL" if force else "SIGTERM"
        return True, f"{verb} gonderildi, {name} henuz kapanmadi"
    return True, f"{name} sonlandirildi"


async def handle_kill(conn: Connection, raw: dict, config: AgentConfig) -> None:
    try:
        envelope = Envelope[ProcessKillPayload].model_validate(raw)
    except ValidationError as exc:
        await conn.send_error("bad_request", str(exc), raw.get("id"))
        return

    ok, detail = await asyncio.to_thread(kill, envelope.payload.pid, envelope.payload.force)
    await conn.send(
        MessageType.PROCESS_KILL_RESULT,
        ProcessKillResultPayload(pid=envelope.payload.pid, ok=ok, detail=detail),
        envelope.id,
    )
