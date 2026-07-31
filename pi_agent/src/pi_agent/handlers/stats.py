from __future__ import annotations

import asyncio
import logging
import platform
import time
from pathlib import Path

import psutil

from pi_protocol import (
    CpuStats,
    DiskStats,
    MemoryStats,
    MessageType,
    StatsUpdatePayload,
    SwapStats,
)

from pi_agent.wire import Connection

logger = logging.getLogger("pi_agent.stats")

_THERMAL_ZONE = Path("/sys/class/thermal/thermal_zone0/temp")


def _cpu_temperature() -> float | None:
    """psutil.sensors_temperatures() is Linux-only and the Pi's key name varies
    across kernels, so fall back to the thermal zone sysfs file."""
    sensors = getattr(psutil, "sensors_temperatures", None)
    if sensors is not None:
        try:
            readings = sensors()
        except Exception:  # noqa: BLE001 - sensor access is best-effort
            readings = {}
        for key in ("cpu_thermal", "coretemp", "soc_thermal"):
            if readings.get(key):
                return float(readings[key][0].current)
        for entries in readings.values():
            if entries:
                return float(entries[0].current)

    try:
        return int(_THERMAL_ZONE.read_text().strip()) / 1000.0
    except (OSError, ValueError):
        return None


def _cpu_frequency() -> float | None:
    try:
        freq = psutil.cpu_freq()
    except Exception:  # noqa: BLE001 - not available on every platform
        return None
    return float(freq.current) if freq else None


def _load_avg() -> tuple[float, float, float] | None:
    try:
        one, five, fifteen = psutil.getloadavg()
    except (OSError, AttributeError):
        return None
    return (one, five, fifteen)


def _disks() -> list[DiskStats]:
    result: list[DiskStats] = []
    for partition in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(partition.mountpoint)
        except OSError:
            continue  # unreadable or disconnected mount, skip rather than fail the whole update
        result.append(
            DiskStats(
                mountpoint=partition.mountpoint,
                total_bytes=usage.total,
                used_bytes=usage.used,
                percent=usage.percent,
            )
        )
    return result


def collect() -> StatsUpdatePayload:
    memory = psutil.virtual_memory()
    swap = psutil.swap_memory()
    return StatsUpdatePayload(
        hostname=platform.node(),
        uptime_seconds=time.time() - psutil.boot_time(),
        load_avg=_load_avg(),
        cpu=CpuStats(
            percent=psutil.cpu_percent(interval=None),
            per_core=psutil.cpu_percent(interval=None, percpu=True),
            temperature_c=_cpu_temperature(),
            frequency_mhz=_cpu_frequency(),
        ),
        memory=MemoryStats(
            total_bytes=memory.total,
            used_bytes=memory.used,
            available_bytes=memory.available,
            percent=memory.percent,
        ),
        swap=SwapStats(total_bytes=swap.total, used_bytes=swap.used, percent=swap.percent),
        disks=_disks(),
    )


async def push_loop(conn: Connection, interval_seconds: float) -> None:
    """Broadcast stats to one client until the connection drops or the task is
    cancelled. psutil.cpu_percent(interval=None) is delta-based, so the first
    sample after startup is meaningless - prime it before the first send."""
    psutil.cpu_percent(interval=None)
    psutil.cpu_percent(interval=None, percpu=True)
    await asyncio.sleep(interval_seconds)

    while True:
        try:
            payload = await asyncio.to_thread(collect)
            await conn.send(MessageType.STATS_UPDATE, payload)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - never let one bad sample kill the loop
            logger.exception("stats collection failed")
        await asyncio.sleep(interval_seconds)
