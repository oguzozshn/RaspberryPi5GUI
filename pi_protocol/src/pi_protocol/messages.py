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
    docker_detail: str = ""
    gpio: bool = False
    gpio_detail: str = ""
    terminal: bool = False
    terminal_detail: str = ""
    vnc: bool = False
    vnc_detail: str = ""
    vnc_port: int = 5900


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


class FilesCreatePayload(BaseModel):
    """Create an empty file or a directory. `path` is the full target path."""

    path: str
    is_dir: bool = False


class FilesCreateResultPayload(BaseModel):
    path: str
    is_dir: bool
    ok: bool
    detail: str


class FilesDeletePayload(BaseModel):
    path: str
    # Deleting a directory that still has contents needs saying so explicitly;
    # nobody empties a home directory by mis-clicking one row.
    recursive: bool = False


class FilesDeleteResultPayload(BaseModel):
    path: str
    ok: bool
    detail: str


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


class GpioReleasePayload(BaseModel):
    """Hand a pin back: stop driving it and return it to input."""

    bcm: int


class GpioReleaseResultPayload(BaseModel):
    bcm: int
    ok: bool
    detail: str


# --- docker -----------------------------------------------------------------


class ContainerInfo(BaseModel):
    id: str
    name: str
    image: str
    state: str
    status: str
    ports: str = ""
    created: str = ""


class DockerListPayload(BaseModel):
    include_stopped: bool = True


class DockerListResultPayload(BaseModel):
    containers: list[ContainerInfo]


class DockerActionPayload(BaseModel):
    container: str
    action: Literal["start", "stop", "restart"]


class DockerActionResultPayload(BaseModel):
    container: str
    action: str
    ok: bool
    detail: str


class DockerLogsPayload(BaseModel):
    container: str
    lines: int = 200


class DockerLogsResultPayload(BaseModel):
    container: str
    lines: list[str]


# --- network ----------------------------------------------------------------


class NetworkInterface(BaseModel):
    name: str
    addresses: list[str] = []
    mac: str = ""
    is_up: bool = False
    speed_mbps: int | None = None
    bytes_sent: int = 0
    bytes_recv: int = 0


class NetworkInfoPayload(BaseModel):
    """No fields: the agent always reports every interface at once."""


# --- terminal ---------------------------------------------------------------


class TerminalSessionRef(BaseModel):
    """Hangi kabuk?

    Kimligi istemci uretir: sunucunun bir 'acildi' yaniti beklemeden ikinci
    sekmeyi acabilmesi ve her mesajin kendi basina hangi oturuma ait oldugunu
    tasimasi icin. Bos birakilirsa tek oturumlu eski davranis surer.
    """

    session_id: str = ""


class TerminalOpenPayload(TerminalSessionRef):
    """Start a shell on a pseudo-terminal."""

    cols: int = 80
    rows: int = 24
    # True ise ekrani ajan cizip hazir satirlar gonderir (terminal.screen).
    # Tarayici istemcisi icin: bir ANSI yorumlayicisini tarayiciya gommek yerine
    # sunucudaki emulatoru paylasiyoruz.
    rendered: bool = False


class TerminalInputPayload(TerminalSessionRef):
    data: str


class TerminalResizePayload(TerminalSessionRef):
    cols: int
    rows: int


class TerminalClosePayload(TerminalSessionRef):
    """Kill the session without dropping the whole connection."""


class TerminalOutputPayload(TerminalSessionRef):
    """Raw shell output, escape sequences included - the client emulates."""

    data: str


class TerminalScreenPayload(TerminalSessionRef):
    """Ajanda cizilmis ekran: kacis dizileri yok, oldugu gibi gosterilir."""

    lines: list[str]
    cursor_row: int = 0
    cursor_col: int = 0


class TerminalExitPayload(TerminalSessionRef):
    exit_code: int | None = None
    detail: str = ""


# --- network ----------------------------------------------------------------


class NetworkInfoResultPayload(BaseModel):
    hostname: str
    interfaces: list[NetworkInterface]
    default_gateway: str = ""
    dns_servers: list[str] = []
    wifi_interface: str = ""
    wifi_ssid: str = ""
    wifi_signal_dbm: int | None = None
