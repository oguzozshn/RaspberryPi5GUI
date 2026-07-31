from __future__ import annotations

from datetime import datetime


def bytes_human(value: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def duration_human(seconds: float) -> str:
    total = int(seconds)
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    # "sa" rather than "s" for hours, so it cannot be read as saniye.
    if days:
        return f"{days}g {hours}sa {minutes}dk"
    if hours:
        return f"{hours}sa {minutes}dk"
    return f"{minutes}dk"


def timestamp_human(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
