from __future__ import annotations

import logging
from pathlib import Path
from typing import AsyncIterator, Callable

import aiohttp

logger = logging.getLogger("desktop_app.file_client")

CHUNK_SIZE = 1024 * 1024  # 1 MB keeps memory flat regardless of file size

ProgressCallback = Callable[[int, int], None]  # (transferred_bytes, total_bytes)


class TransferError(Exception):
    pass


class FileClient:
    """Streams file bytes over the agent's HTTP routes. Separate from the WS
    control channel so a big transfer can't stall live stats."""

    def __init__(self, host: str, port: int, token: str) -> None:
        self._base = f"http://{host}:{port}/files"
        self._headers = {"Authorization": f"Bearer {token}"}

    async def upload(
        self, local_path: Path, remote_path: str, on_progress: ProgressCallback | None = None
    ) -> int:
        total = local_path.stat().st_size

        async def sender() -> AsyncIterator[bytes]:
            sent = 0
            with local_path.open("rb") as handle:
                while chunk := handle.read(CHUNK_SIZE):
                    sent += len(chunk)
                    if on_progress:
                        on_progress(sent, total)
                    yield chunk

        async with aiohttp.ClientSession(headers=self._headers) as session:
            async with session.put(
                f"{self._base}/upload", params={"path": remote_path}, data=sender()
            ) as response:
                if response.status != 200:
                    raise TransferError(await _detail(response))
                return (await response.json())["size_bytes"]

    async def download(
        self, remote_path: str, local_path: Path, on_progress: ProgressCallback | None = None
    ) -> int:
        async with aiohttp.ClientSession(headers=self._headers) as session:
            async with session.get(f"{self._base}/download", params={"path": remote_path}) as response:
                if response.status != 200:
                    raise TransferError(await _detail(response))

                total = int(response.headers.get("Content-Length", 0))
                received = 0
                # Write to .part and rename so an interrupted download never
                # leaves a truncated file at the real destination.
                partial = local_path.with_name(local_path.name + ".part")
                try:
                    with partial.open("wb") as handle:
                        async for chunk in response.content.iter_chunked(CHUNK_SIZE):
                            handle.write(chunk)
                            received += len(chunk)
                            if on_progress:
                                on_progress(received, total)
                    partial.replace(local_path)
                except BaseException:
                    partial.unlink(missing_ok=True)
                    raise
                return received


async def _detail(response: aiohttp.ClientResponse) -> str:
    try:
        body = await response.json()
        return f"HTTP {response.status}: {body.get('detail', body)}"
    except Exception:  # noqa: BLE001 - error bodies are not always JSON
        return f"HTTP {response.status}"
