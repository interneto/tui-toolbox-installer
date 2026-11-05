"""Execute install commands, streaming their output line by line.

Kept UI-agnostic: it yields plain strings so the Textual app can pump them into
a log widget from a worker thread.
"""

from __future__ import annotations

import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import urllib.request
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import platformdirs

from .secrets import redact


@dataclass
class CommandResult:
    """Outcome of one command, for headless summaries/JSON."""

    argv: list[str]
    returncode: int | None = None
    error: str | None = None


class RunControl:
    """Thread-safe stop handle shared by the UI and the worker running commands."""

    def __init__(self) -> None:
        self._stopped = threading.Event()
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._cancelled = False

    @property
    def stopped(self) -> bool:
        return self._stopped.is_set()

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def attach(self, process: subprocess.Popen) -> None:
        with self._lock:
            self._process = process
            already_stopped = self._stopped.is_set()
        if already_stopped:
            _terminate_tree(process)

    def detach(self, process: subprocess.Popen) -> None:
        with self._lock:
            if self._process is process:
                self._process = None

    def request_stop(self) -> None:
        with self._lock:
            self._cancelled = True
            self._stopped.set()
            process = self._process
        if process is not None:
            _terminate_tree(process)


def _terminate_tree(process: subprocess.Popen) -> None:
    """Ask the child (and its children) to stop, then force-kill after a grace period."""
    if process.poll() is not None:
        return
    if os.name == "posix":
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                process.terminate()
            except OSError:
                pass
        _schedule_force_kill(process)
    else:
        try:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(process.pid)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            try:
                process.kill()
            except OSError:
                pass


def _schedule_force_kill(process: subprocess.Popen) -> None:
    def force() -> None:
        if process.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                process.kill()
            except OSError:
                pass

    timer = threading.Timer(3.0, force)
    timer.daemon = True
    timer.start()


def _resolve(argv: list[str]) -> list[str] | None:
    """Resolve the executable on PATH (finds code.cmd, winget.exe, etc.)."""
    if not argv:
        return None
    exe = shutil.which(argv[0])
    if exe is None:
        return None
    return [exe, *argv[1:]]


def _subprocess_env() -> dict[str, str]:
    """Environment for install commands that must not stop for input."""
    env = os.environ.copy()
    env.setdefault("DEBIAN_FRONTEND", "noninteractive")
    env.setdefault("HOMEBREW_NO_AUTO_UPDATE", "1")
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    env.setdefault("npm_config_yes", "true")
    return env


def _spawn_kwargs() -> dict[str, object]:
    """Give the child its own process group/session (needed for cancellation)."""
    if os.name == "posix":
        return {"start_new_session": True}
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return {"creationflags": flags} if flags else {}


_PATH_CANDIDATES = (
    "~/.local/bin",
    "~/.local/share/pnpm",
    "~/.npm-global/bin",
    "~/.cargo/bin",
    "~/.bun/bin",
    "~/.nix-profile/bin",
    "/usr/local/bin",
    "/opt/homebrew/bin",
    "/home/linuxbrew/.linuxbrew/bin",
    "/nix/var/nix/profiles/default/bin",
    "/Applications/Visual Studio Code.app/Contents/Resources/app/bin",
)


def _norm_path_entry(entry: str) -> str:
    return entry.rstrip("\\/").lower() if os.name == "nt" else entry.rstrip("/")


def _refresh_windows_path() -> None:
    """Re-read the machine/user PATH from the registry (winget updates it)."""
    try:
        import winreg
    except ImportError:  # pragma: no cover - non-Windows
        return

    entries: list[str] = []
    locations = (
        (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
        (winreg.HKEY_CURRENT_USER, r"Environment"),
    )
    for root, subkey in locations:
        try:
            with winreg.OpenKey(root, subkey) as key:
                value, _ = winreg.QueryValueEx(key, "Path")
        except OSError:
            continue
        entries.extend(
            part for part in os.path.expandvars(str(value)).split(os.pathsep) if part
        )

    current = [part for part in os.environ.get("PATH", "").split(os.pathsep) if part]
    seen = {_norm_path_entry(part) for part in current}
    for entry in entries:
        norm = _norm_path_entry(entry)
        if norm and norm not in seen:
            current.append(entry)
            seen.add(norm)
    if current:
        os.environ["PATH"] = os.pathsep.join(current)


def refresh_path(extra_dirs: Iterable[str | Path] = ()) -> None:
    """Pick up tools installed by this run without restarting the app.

    On Windows the registry PATH is the source of truth; everywhere the
    well-known tool directories (uv, cargo, pnpm, brew, VS Code, Nix) are
    appended if they exist. Safe to call repeatedly.
    """
    if os.name == "nt":
        _refresh_windows_path()

    current = [part for part in os.environ.get("PATH", "").split(os.pathsep) if part]
    seen = {_norm_path_entry(part) for part in current}
    for raw in [*_PATH_CANDIDATES, *(str(item) for item in extra_dirs)]:
        path = Path(raw).expanduser()
        if not path.is_dir():
            continue
        entry = str(path)
        norm = _norm_path_entry(entry)
        if norm not in seen:
            current.append(entry)
            seen.add(norm)
    if current:
        os.environ["PATH"] = os.pathsep.join(current)


def requires_sudo(commands: Iterable[list[str]]) -> bool:
    """True when any planned command starts with sudo/doas."""
    return any(argv and argv[0] in {"sudo", "doas"} for argv in commands)


def sudo_ready() -> bool:
    """True when sudo can run without a password prompt right now."""
    exe = shutil.which("sudo")
    if exe is None:
        return True  # No sudo: let the command itself report the real error.
    try:
        return subprocess.run(
            [exe, "-n", "true"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def authenticate_sudo() -> int:
    """Ask sudo for a password with the real terminal attached (call suspended)."""
    exe = shutil.which("sudo")
    if exe is None:
        return 0
    return subprocess.call([exe, "-v"])


def run_commands(
    commands: list[list[str]],
    secrets: Iterable[str] = (),
    *,
    continue_on_error: bool = False,
    results: list[CommandResult] | None = None,
    on_result: Callable[[CommandResult], None] | None = None,
    control: RunControl | None = None,
) -> Iterator[str]:
    """Run each command in order, yielding output and status lines.

    stdin is /dev/null so a package manager cannot block on an invisible
    prompt, and secret values are redacted from everything this yields.
    By default it stops at the first failure (the TUI's behaviour); headless
    batches pass ``continue_on_error=True`` so one bad package does not block
    the rest. Outcomes are appended to ``results`` when given and passed to
    ``on_result`` (headless uses it to persist resume state). ``control`` lets
    the UI stop the current process tree.
    """
    secrets = tuple(secrets)
    env = _subprocess_env()
    failures = 0

    for argv in commands:
        if control is not None and control.stopped:
            yield "✗ Cancelled."
            return

        printable = redact(shlex.join(argv), secrets)
        yield f"$ {printable}"

        resolved = _resolve(argv)
        if resolved is None:
            result = CommandResult(list(argv), error=f"'{argv[0]}' not found on PATH")
            if results is not None:
                results.append(result)
            if on_result is not None:
                on_result(result)
            failures += 1
            yield f"✗ '{argv[0]}' was not found on PATH. Install it and retry."
            if control is not None and control.stopped:
                yield "✗ Cancelled."
                return
            if continue_on_error:
                continue
            return

        try:
            process = subprocess.Popen(
                resolved,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
                **_spawn_kwargs(),
            )
        except OSError as exc:  # pragma: no cover - environment dependent
            result = CommandResult(list(argv), error=str(exc))
            if results is not None:
                results.append(result)
            if on_result is not None:
                on_result(result)
            failures += 1
            yield f"✗ Failed to start: {exc}"
            if control is not None and control.stopped:
                yield "✗ Cancelled."
                return
            if continue_on_error:
                continue
            return

        if control is not None:
            control.attach(process)
        assert process.stdout is not None
        try:
            for line in process.stdout:
                yield redact(line.rstrip("\n"), secrets)
        finally:
            if control is not None:
                control.detach(process)

        code = process.wait()
        result = CommandResult(list(argv), returncode=code)
        if results is not None:
            results.append(result)
        if on_result is not None:
            on_result(result)

        if control is not None and control.stopped:
            yield "✗ Cancelled."
            return

        if code != 0:
            failures += 1
            yield f"✗ Exited with code {code}."
            if continue_on_error:
                continue
            yield "Stopping."
            return
        yield "✓ Done."

    yield ""
    if failures:
        yield f"Finished with {failures} failed command(s)."
    else:
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
    base = Path(platformdirs.user_downloads_dir())
    if not base.is_dir():
        base = Path(tempfile.gettempdir())
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


def run_browser_installs(
    downloads: Iterable[_Downloadable], control: RunControl | None = None
) -> Iterator[str]:
    """Download each extension file and open it for the browser to install."""
    dest = _downloads_dir()
    yield f"Saving to {dest}"
    yield ""
    opened = 0
    for item in downloads:
        if control is not None and control.stopped:
            yield "✗ Cancelled."
            return
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
