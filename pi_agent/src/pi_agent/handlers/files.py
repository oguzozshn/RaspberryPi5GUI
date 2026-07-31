from __future__ import annotations

import asyncio

from pydantic import ValidationError

from pi_protocol import Envelope, FilesListPayload, FilesListResultPayload, MessageType

from pi_agent import paths
from pi_agent.config import AgentConfig
from pi_agent.wire import Connection


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
