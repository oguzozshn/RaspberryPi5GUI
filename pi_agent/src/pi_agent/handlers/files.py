from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

from pydantic import ValidationError

from pi_protocol import (
    Envelope,
    FilesCreatePayload,
    FilesCreateResultPayload,
    FilesDeletePayload,
    FilesDeleteResultPayload,
    FilesListPayload,
    FilesListResultPayload,
    MessageType,
)

from pi_agent import paths
from pi_agent.config import AgentConfig
from pi_agent.wire import Connection

logger = logging.getLogger("pi_agent.files")

# Refusing to delete these is not real security - the agent runs as a user who
# could remove them anyway - but every one of them is a "no undo, and now the Pi
# needs a card reader" mistake, and no file browser needs to offer it.
_PROTECTED = {"/", "/boot", "/boot/firmware", "/etc", "/usr", "/var", "/bin", "/sbin", "/lib",
              "/proc", "/sys", "/dev", "/home", "/root", "/opt"}


async def handle_list(conn: Connection, raw: dict, config: AgentConfig) -> None:
    try:
        envelope = Envelope[FilesListPayload].model_validate(raw)
    except ValidationError as exc:
        await conn.send_error("bad_request", str(exc), raw.get("id"))
        return

    target = paths.resolve(envelope.payload.path)

    if not target.exists():
        await conn.send_error("not_found", f"yol bulunamadi: {target}", envelope.id)
        return
    if not target.is_dir():
        await conn.send_error("not_a_directory", f"dizin degil: {target}", envelope.id)
        return

    try:
        entries = await asyncio.to_thread(paths.list_directory, target)
    except PermissionError:
        await conn.send_error("permission_denied", f"erisim reddedildi: {target}", envelope.id)
        return
    except OSError as exc:
        await conn.send_error("io_error", str(exc), envelope.id)
        return

    payload = FilesListResultPayload(
        path=str(target), parent=paths.parent_of(target), entries=entries
    )
    await conn.send(MessageType.FILES_LIST_RESULT, payload, envelope.id)


# --- create / delete --------------------------------------------------------


def is_protected(target: Path) -> bool:
    # as_posix(), cunku bu liste POSIX yollari; Windows'ta gelistirirken
    # str(Path("/etc")) "\\etc" olur ve karsilastirma sessizce kacar.
    return target.as_posix().rstrip("/") in _PROTECTED or target.as_posix() == "/"


def create(target: Path, is_dir: bool) -> tuple[bool, str]:
    if target.exists():
        return False, f"zaten var: {target.name}"
    try:
        if is_dir:
            target.mkdir(parents=False)
        else:
            # Exclusive create: never truncate a file that appeared in between.
            target.touch(exist_ok=False)
    except FileNotFoundError:
        return False, f"ust dizin yok: {target.parent}"
    except FileExistsError:
        return False, f"zaten var: {target.name}"
    except PermissionError:
        return False, f"izin yok: {target.parent}"
    except OSError as exc:
        return False, str(exc)
    return True, f"{'dizin' if is_dir else 'dosya'} olusturuldu: {target.name}"


def delete(target: Path, recursive: bool) -> tuple[bool, str]:
    # Koruma once: bir yolun silinemez olmasi, o an var olup olmamasindan
    # bagimsiz bir kural.
    if is_protected(target):
        return False, f"korunan yol, silinmez: {target}"
    if not target.exists() and not target.is_symlink():
        return False, f"yol bulunamadi: {target}"

    try:
        if target.is_dir() and not target.is_symlink():
            if any(target.iterdir()) and not recursive:
                return False, "dizin bos degil"
            shutil.rmtree(target) if recursive else target.rmdir()
        else:
            target.unlink()
    except PermissionError:
        return False, f"izin yok: {target}"
    except OSError as exc:
        return False, str(exc)
    return True, f"silindi: {target.name}"


async def handle_create(conn: Connection, raw: dict, config: AgentConfig) -> None:
    try:
        envelope = Envelope[FilesCreatePayload].model_validate(raw)
    except ValidationError as exc:
        await conn.send_error("bad_request", str(exc), raw.get("id"))
        return

    target = paths.resolve(envelope.payload.path)
    ok, detail = await asyncio.to_thread(create, target, envelope.payload.is_dir)
    logger.info("files create %s -> %s", target, "ok" if ok else detail)
    await conn.send(
        MessageType.FILES_CREATE_RESULT,
        FilesCreateResultPayload(
            path=str(target), is_dir=envelope.payload.is_dir, ok=ok, detail=detail
        ),
        envelope.id,
    )


async def handle_delete(conn: Connection, raw: dict, config: AgentConfig) -> None:
    try:
        envelope = Envelope[FilesDeletePayload].model_validate(raw)
    except ValidationError as exc:
        await conn.send_error("bad_request", str(exc), raw.get("id"))
        return

    target = paths.resolve(envelope.payload.path)
    ok, detail = await asyncio.to_thread(delete, target, envelope.payload.recursive)
    logger.info("files delete %s -> %s", target, "ok" if ok else detail)
    await conn.send(
        MessageType.FILES_DELETE_RESULT,
        FilesDeleteResultPayload(path=str(target), ok=ok, detail=detail),
        envelope.id,
    )
