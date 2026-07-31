from __future__ import annotations

import asyncio
import logging
from typing import Callable, Coroutine

logger = logging.getLogger("desktop_app.async_utils")


def schedule(
    coro: Coroutine, on_error: Callable[[BaseException], None] | None = None
) -> asyncio.Task | None:
    """Fire-and-forget a coroutine on the qasync loop.

    Bare asyncio.ensure_future() leaves failures as "task exception was never
    retrieved" noise on stderr; this attaches a done-callback so a dropped
    connection surfaces in the UI instead of vanishing.
    """
    try:
        task = asyncio.ensure_future(coro)
    except RuntimeError:
        coro.close()
        logger.warning("no running event loop; dropped %r", coro.__qualname__)
        return None

    def _on_done(finished: asyncio.Task) -> None:
        if finished.cancelled():
            return
        error = finished.exception()
        if error is None:
            return
        logger.warning("background task failed: %s", error)
        if on_error is not None:
            on_error(error)

    task.add_done_callback(_on_done)
    return task
