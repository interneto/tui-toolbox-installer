"""Execute install commands, streaming their output line by line.

Kept UI-agnostic: it yields plain strings so the Textual app can pump them into
a log widget from a worker thread.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Protocol


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


# --------------------------------------------------------------------------- #
# Browser extension installs: download the .xpi/.crx, then open it so the
# browser performs the final install.
# --------------------------------------------------------------------------- #
class _Downloadable(Protocol):
    name: str
    url: str
    filename: str


def _downloads_dir() -> Path:
    home = Path.home() / "Downloads"
    base = home if home.is_dir() else Path(tempfile.gettempdir())
    target = base / "interneto-extensions"
    target.mkdir(parents=True, exist_ok=True)
    return target


def _open_file(path: Path) -> None:
    """Open a file with the OS default handler (the browser, for .xpi/.crx)."""
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def run_browser_installs(downloads: Iterable[_Downloadable]) -> Iterator[str]:
    """Download each extension file and open it for the browser to install."""
    dest = _downloads_dir()
    yield f"Saving to {dest}"
    yield ""
    opened = 0
    for item in downloads:
        yield f"↓ {item.name}"
        yield f"  {item.url}"
        target = dest / item.filename
        request = urllib.request.Request(
            item.url, headers={"User-Agent": "Mozilla/5.0 (interneto-install)"}
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as resp, open(target, "wb") as fh:
                shutil.copyfileobj(resp, fh)
        except Exception as exc:  # network/HTTP errors are environment dependent
            yield f"  ✗ Download failed: {exc}"
            yield ""
            continue
        yield f"  ✓ Saved {item.filename} ({target.stat().st_size // 1024} KiB)"
        try:
            _open_file(target)
            opened += 1
            yield "  → Opened to finish installing in your browser."
        except Exception as exc:  # pragma: no cover - environment dependent
            yield f"  ✗ Could not open the file: {exc}"
        yield ""
    yield f"Done — opened {opened} file(s) for install."
    yield (
        "Note: Firefox will ask you to confirm the add-on. Chrome may refuse a "
        ".crx that wasn't installed from the Web Store."
    )
