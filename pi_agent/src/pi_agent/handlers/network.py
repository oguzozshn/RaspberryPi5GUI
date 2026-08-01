from __future__ import annotations

import asyncio
import re
import shutil
import socket
from pathlib import Path

import psutil

from pi_protocol import (
    MessageType,
    NetworkInfoResultPayload,
    NetworkInterface,
)

from pi_agent.config import AgentConfig
from pi_agent.proc import run
from pi_agent.wire import Connection

_IW_TIMEOUT_SECONDS = 5

PROC_ROUTE = Path("/proc/net/route")
PROC_WIRELESS = Path("/proc/net/wireless")
RESOLV_CONF = Path("/etc/resolv.conf")

# Flag bit 0x2 in /proc/net/route means "this route goes via a gateway".
_RTF_GATEWAY = 0x2

_SSID_PATTERN = re.compile(r"^\s*SSID:\s*(.+)$", re.MULTILINE)
_SIGNAL_PATTERN = re.compile(r"^\s*signal:\s*(-?\d+)", re.MULTILINE)


# --- pure parsers -----------------------------------------------------------


def parse_default_gateway(text: str) -> str:
    """Pull the default gateway out of /proc/net/route.

    Addresses there are little-endian hex, so 0102A8C0 is 192.168.2.1. When
    several default routes exist (Ethernet and Wi-Fi both up) the lowest metric
    is the one traffic actually takes.
    """
    best: tuple[int, str] | None = None
    for line in text.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 8 or fields[1] != "00000000":
            continue
        try:
            flags = int(fields[3], 16)
            metric = int(fields[6])
            raw = int(fields[2], 16)
        except ValueError:
            continue
        if not flags & _RTF_GATEWAY:
            continue
        address = ".".join(str((raw >> shift) & 0xFF) for shift in (0, 8, 16, 24))
        if best is None or metric < best[0]:
            best = (metric, address)
    return best[1] if best else ""


def parse_resolv_conf(text: str) -> list[str]:
    servers: list[str] = []
    for line in text.splitlines():
        line = line.split("#")[0].strip()
        if line.startswith("nameserver"):
            parts = line.split()
            if len(parts) > 1 and parts[1] not in servers:
                servers.append(parts[1])
    return servers


def parse_wireless_interfaces(text: str) -> list[str]:
    """Interface names from /proc/net/wireless - the cheapest way to tell which
    interfaces are Wi-Fi without asking a tool that may not be installed."""
    names: list[str] = []
    for line in text.splitlines():
        if ":" not in line:
            continue
        name = line.split(":", 1)[0].strip()
        # The two header lines contain "Inter-|" and "face |".
        if name and not name.endswith("|") and " " not in name:
            names.append(name)
    return names


def parse_iw_link(text: str) -> tuple[str, int | None]:
    """(ssid, signal in dBm) from `iw dev <if> link`. Unassociated adaptors
    print "Not connected." and yield ("", None)."""
    ssid_match = _SSID_PATTERN.search(text)
    signal_match = _SIGNAL_PATTERN.search(text)
    ssid = ssid_match.group(1).strip() if ssid_match else ""
    signal = int(signal_match.group(1)) if signal_match else None
    return ssid, signal


# Loopback plus the interface families container and VM runtimes create. Matched
# by name because psutil exposes nothing that distinguishes them.
_VIRTUAL_PREFIXES = ("docker", "br-", "veth", "virbr", "vmnet", "tun", "tap", "wg")


def is_virtual(name: str) -> bool:
    return name == "lo" or name.startswith(_VIRTUAL_PREFIXES)


def _read(path: Path) -> str:
    """Read a /proc or /etc file, tolerating its absence: on Windows (dev) none
    of them exist, and a container may not expose all of them either."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


# --- collection -------------------------------------------------------------


def collect_interfaces() -> list[NetworkInterface]:
    addresses = psutil.net_if_addrs()
    stats = psutil.net_if_stats()
    counters = psutil.net_io_counters(pernic=True)

    interfaces: list[NetworkInterface] = []
    for name, entries in addresses.items():
        ip_addresses: list[str] = []
        mac = ""
        for entry in entries:
            if entry.family == socket.AF_INET:
                ip_addresses.append(entry.address)
            elif entry.family == socket.AF_INET6:
                # Link-local addresses carry a %scope suffix that is noise here.
                ip_addresses.append(entry.address.split("%")[0])
            elif getattr(psutil, "AF_LINK", None) is not None and entry.family == psutil.AF_LINK:
                mac = entry.address

        stat = stats.get(name)
        counter = counters.get(name)
        interfaces.append(
            NetworkInterface(
                name=name,
                addresses=ip_addresses,
                mac=mac,
                is_up=bool(stat.isup) if stat else False,
                speed_mbps=stat.speed if stat and stat.speed > 0 else None,
                bytes_sent=counter.bytes_sent if counter else 0,
                bytes_recv=counter.bytes_recv if counter else 0,
            )
        )

    # Up-and-addressed physical interfaces first: on a Pi running docker the
    # bridges and veth pairs otherwise sort above wlan0 and bury the one
    # interface anybody opened this tab to look at.
    interfaces.sort(key=lambda i: (not i.is_up, not i.addresses, is_virtual(i.name), i.name))
    return interfaces


def collect_static() -> tuple[str, list[str], list[str]]:
    """Everything that comes from reading files, gathered in one thread hop."""
    return (
        parse_default_gateway(_read(PROC_ROUTE)),
        parse_resolv_conf(_read(RESOLV_CONF)),
        parse_wireless_interfaces(_read(PROC_WIRELESS)),
    )


async def _wifi_details(wireless: list[str]) -> tuple[str, str, int | None]:
    """(interface, ssid, signal) for the first associated Wi-Fi adaptor."""
    if not wireless or shutil.which("iw") is None:
        return "", "", None

    for name in wireless:
        code, stdout, _stderr = await run(
            ["iw", "dev", name, "link"], timeout=_IW_TIMEOUT_SECONDS
        )
        if code != 0:
            continue
        ssid, signal = parse_iw_link(stdout)
        if ssid:
            return name, ssid, signal
    return wireless[0], "", None


# --- handler ----------------------------------------------------------------


async def handle(conn: Connection, raw: dict, config: AgentConfig) -> None:
    interfaces = await asyncio.to_thread(collect_interfaces)
    gateway, dns, wireless = await asyncio.to_thread(collect_static)
    wifi_interface, ssid, signal = await _wifi_details(wireless)

    await conn.send(
        MessageType.NETWORK_INFO_RESULT,
        NetworkInfoResultPayload(
            hostname=socket.gethostname(),
            interfaces=interfaces,
            default_gateway=gateway,
            dns_servers=dns,
            wifi_interface=wifi_interface,
            wifi_ssid=ssid,
            wifi_signal_dbm=signal,
        ),
        raw.get("id"),
    )
