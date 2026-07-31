from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse

from pi_agent import paths
from pi_agent.auth import token_matches

logger = logging.getLogger("pi_agent.files")

router = APIRouter(prefix="/files")

# File bytes travel over plain HTTP rather than the WS control channel so that a
# large transfer cannot head-of-line block latency-sensitive stats/chat frames.


def _require_token(request: Request, authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    if not token_matches(request.app.state.config, authorization.removeprefix("Bearer ")):
        raise HTTPException(status_code=403, detail="invalid token")


@router.put("/upload")
async def upload(
    request: Request,
    path: str = Query(..., description="absolute destination path on the Pi"),
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    _require_token(request, authorization)

    target = paths.resolve(path)
    if not target.parent.is_dir():
        raise HTTPException(status_code=404, detail=f"hedef dizin yok: {target.parent}")
    if target.is_dir():
        raise HTTPException(status_code=400, detail=f"hedef bir dizin: {target}")

    # Stream to a sibling .part file and rename on success, so an interrupted
    # transfer never leaves a truncated file at the real destination.
    partial = target.with_name(target.name + ".part")
    written = 0
    try:
        with partial.open("wb") as handle:
            async for chunk in request.stream():
                handle.write(chunk)
                written += len(chunk)
        partial.replace(target)
    except PermissionError as exc:
        partial.unlink(missing_ok=True)
        raise HTTPException(status_code=403, detail=f"yazma izni yok: {target}") from exc
    except OSError as exc:
        partial.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    logger.info("uploaded %s (%d bytes)", target, written)
    return {"path": str(target), "size_bytes": written}


@router.get("/download")
async def download(
    request: Request,
    path: str = Query(..., description="absolute source path on the Pi"),
    authorization: str | None = Header(default=None),
) -> FileResponse:
    _require_token(request, authorization)

    source: Path = paths.resolve(path)
    if not source.exists():
        raise HTTPException(status_code=404, detail=f"dosya bulunamadi: {source}")
    if source.is_dir():
        raise HTTPException(status_code=400, detail=f"dizin indirilemez: {source}")
    if not _readable(source):
        raise HTTPException(status_code=403, detail=f"okuma izni yok: {source}")

    return FileResponse(source, filename=source.name)


def _readable(path: Path) -> bool:
    try:
        with path.open("rb"):
            return True
    except OSError:
        return False
