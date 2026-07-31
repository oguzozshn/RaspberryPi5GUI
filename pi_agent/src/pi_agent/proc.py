from __future__ import annotations

import asyncio

DEFAULT_TIMEOUT_SECONDS = 30


async def run(command: list[str], timeout: float = DEFAULT_TIMEOUT_SECONDS) -> tuple[int, str, str]:
    """Run a command and return (returncode, stdout, stderr).

    Always exec, never a shell: arguments that came from the client reach the
    binary as single argv entries, so quoting and metacharacters carry no
    meaning. A timeout kills the child rather than pinning the handler task.
    """
    process = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        process.kill()
        return 124, "", f"komut zaman asimina ugradi: {' '.join(command)}"
    return (
        process.returncode or 0,
        stdout.decode(errors="replace"),
        stderr.decode(errors="replace"),
    )
