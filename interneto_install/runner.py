"""Execute install commands, streaming their output line by line.

Kept UI-agnostic: it yields plain strings so the Textual app can pump them into
a log widget from a worker thread.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
from collections.abc import Iterator


def _resolve(argv: list[str]) -> list[str] | None:
    """Resolve the executable on PATH (finds code.cmd, winget.exe, etc.)."""
    if not argv:
        return None
    exe = shutil.which(argv[0])
    if exe is None:
        return None
    return [exe, *argv[1:]]


def run_commands(commands: list[list[str]]) -> Iterator[str]:
    """Run each command in order, yielding output and status lines.

    Stops early if a command's executable is missing or it exits non-zero.
    """
    for argv in commands:
        printable = shlex.join(argv)
        yield f"$ {printable}"

        resolved = _resolve(argv)
        if resolved is None:
            yield f"✗ '{argv[0]}' was not found on PATH. Install it and retry."
            return

        try:
            process = subprocess.Popen(
                resolved,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except OSError as exc:  # pragma: no cover - environment dependent
            yield f"✗ Failed to start: {exc}"
            return

        assert process.stdout is not None
        for line in process.stdout:
            yield line.rstrip("\n")
        code = process.wait()

        if code != 0:
            yield f"✗ Exited with code {code}. Stopping."
            return
        yield "✓ Done."

    yield ""
    yield "All commands finished."
