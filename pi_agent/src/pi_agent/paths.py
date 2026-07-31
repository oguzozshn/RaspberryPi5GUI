from __future__ import annotations

import stat as stat_module
from pathlib import Path

from pi_protocol import FileEntry


def resolve(path_str: str) -> Path:
    """Expand ~ and normalise. There is no chroot-style jail: the agent runs as
    your own account, so the filesystem it can touch is exactly what that account
    can touch, which is the point of a full file manager."""
    return Path(path_str).expanduser().resolve()


def entry_for(path: Path) -> FileEntry:
    st = path.stat()
    return FileEntry(
        name=path.name or str(path),
        path=str(path),
        is_dir=path.is_dir(),
        size_bytes=st.st_size,
        modified_ts=st.st_mtime,
        permissions=stat_module.filemode(st.st_mode),
    )


def list_directory(path: Path) -> list[FileEntry]:
    entries: list[FileEntry] = []
    for child in path.iterdir():
        try:
            entries.append(entry_for(child))
        except OSError:
            continue  # broken symlink or unreadable entry, skip it rather than fail the listing
    entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
    return entries


def parent_of(path: Path) -> str | None:
    parent = path.parent
    return None if parent == path else str(parent)
