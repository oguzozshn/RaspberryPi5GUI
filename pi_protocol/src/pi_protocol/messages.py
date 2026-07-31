from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

# --- auth -------------------------------------------------------------------


class AuthRequestPayload(BaseModel):
    token: str


class AuthOkPayload(BaseModel):
    protocol_version: int


class AuthRejectedPayload(BaseModel):
    reason: str


# --- stats (server push) ----------------------------------------------------


class CpuStats(BaseModel):
    percent: float
    per_core: list[float]
    temperature_c: float | None = None
    frequency_mhz: float | None = None


class MemoryStats(BaseModel):
    total_bytes: int
    used_bytes: int
    available_bytes: int
    percent: float


class SwapStats(BaseModel):
    total_bytes: int
    used_bytes: int
    percent: float


class DiskStats(BaseModel):
    mountpoint: str
    total_bytes: int
    used_bytes: int
    percent: float


class StatsUpdatePayload(BaseModel):
    hostname: str
    uptime_seconds: float
    load_avg: tuple[float, float, float] | None = None
    cpu: CpuStats
    memory: MemoryStats
    swap: SwapStats
    disks: list[DiskStats]


# --- processes (request / response) -----------------------------------------


class ProcessInfo(BaseModel):
    pid: int
    name: str
    username: str | None = None
    cpu_percent: float
    memory_percent: float
    memory_rss_bytes: int
    status: str
    cmdline: str


class ProcessListPayload(BaseModel):
    limit: int = 60
    sort_by: Literal["cpu", "memory", "pid", "name"] = "cpu"


class ProcessListResultPayload(BaseModel):
    processes: list[ProcessInfo]
    total_count: int


# --- files (request / response) ---------------------------------------------


class FileEntry(BaseModel):
    name: str
    path: str
    is_dir: bool
    size_bytes: int
    modified_ts: float
    permissions: str


class FilesListPayload(BaseModel):
    path: str


class FilesListResultPayload(BaseModel):
    path: str
    parent: str | None
    entries: list[FileEntry]
