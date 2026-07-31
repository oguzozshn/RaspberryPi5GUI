from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

# --- auth -------------------------------------------------------------------


class AuthRequestPayload(BaseModel):
    token: str


class Capabilities(BaseModel):
    """What this particular Pi can actually do. Ships inside auth.ok rather than
    as a separate push so the client can never race ahead of it."""

    clipboard: bool = False
    clipboard_detail: str = ""
    systemd: bool = False
    docker: bool = False
    gpio: bool = False
    gpio_detail: str = ""


class AuthOkPayload(BaseModel):
    protocol_version: int
    capabilities: Capabilities = Capabilities()


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


class ProcessKillPayload(BaseModel):
    pid: int
    force: bool = False


class ProcessKillResultPayload(BaseModel):
    pid: int
    ok: bool
    detail: str


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


# --- chat / clipboard bridge ------------------------------------------------


class ChatSendPayload(BaseModel):
    """Text typed in the desktop GUI, to be placed on the Pi's system clipboard
    so it can be pasted into whatever prompt is focused there."""

    text: str


class ChatMessagePayload(BaseModel):
    text: str
    source: Literal["desktop", "pi"]
    delivered_to_clipboard: bool = False
    detail: str = ""


class ClipboardPullPayload(BaseModel):
    """Read the Pi's clipboard back into the desktop chat history."""


# --- systemd services -------------------------------------------------------


class ServiceInfo(BaseModel):
    unit: str
    load: str
    active: str
    sub: str
    description: str


class ServiceListPayload(BaseModel):
    pattern: str = ""


class ServiceListResultPayload(BaseModel):
    services: list[ServiceInfo]


class ServiceActionPayload(BaseModel):
    unit: str
    action: Literal["start", "stop", "restart"]


class ServiceActionResultPayload(BaseModel):
    unit: str
    action: str
    ok: bool
    detail: str


class ServiceLogsPayload(BaseModel):
    unit: str
    lines: int = 200


class ServiceLogsResultPayload(BaseModel):
    unit: str
    lines: list[str]


# --- power ------------------------------------------------------------------


class PowerActionPayload(BaseModel):
    action: Literal["reboot", "shutdown"]


class PowerActionResultPayload(BaseModel):
    action: str
    ok: bool
    detail: str


# --- gpio -------------------------------------------------------------------


class GpioPin(BaseModel):
    """One usable GPIO on the 40-pin header. `value` is None when the level
    could not be read - typically because another driver owns the line."""

    bcm: int
    physical: int
    mode: Literal["input", "output"]
    value: int | None = None
    consumer: str = ""
    reserved_for: str = ""
    writable: bool = True


class GpioListPayload(BaseModel):
    """No fields: the agent always reports every header pin at once."""


class GpioListResultPayload(BaseModel):
    pins: list[GpioPin]
    detail: str = ""


class GpioWritePayload(BaseModel):
    bcm: int
    value: Literal[0, 1]


class GpioWriteResultPayload(BaseModel):
    bcm: int
    value: int
    ok: bool
    detail: str
