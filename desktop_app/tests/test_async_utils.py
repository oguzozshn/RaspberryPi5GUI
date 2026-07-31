from __future__ import annotations

import asyncio

from desktop_app.async_utils import schedule


def test_schedule_without_loop_returns_none_and_does_not_raise() -> None:
    async def work() -> None:
        pass

    assert schedule(work()) is None


def test_schedule_reports_failure_to_callback() -> None:
    errors: list[BaseException] = []

    async def failing() -> None:
        raise RuntimeError("not connected")

    async def main() -> None:
        schedule(failing(), errors.append)
        await asyncio.sleep(0)  # let the task run and the done-callback fire
        await asyncio.sleep(0)

    asyncio.run(main())
    assert len(errors) == 1
    assert str(errors[0]) == "not connected"
