"""Non-interactive install mode (``interneto-install --yes`` and friends).

The TUI is the right default for a person at a keyboard. This module is for
the other case: a freshly reinstalled machine where the same curated profile
has to be applied without anyone sitting in front of a terminal.

It reuses the exact planners the TUI uses (``commands.*``), so there is one
source of truth for what gets run. What it adds is orchestration: surface
selection, ``--only-missing`` inventories, a money-safe ``--dry-run``, a text
log, JSON output and a meaningful exit code.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any, TextIO

import platformdirs

from . import commands, data, detect, favorites, runner
from .secrets import redact

SURFACES = favorites.SURFACES
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
STATE_VERSION = 1


def command_hash(argv: list[str]) -> str:
    """Stable id for a planned command, used by --resume."""
    payload = json.dumps(argv, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def download_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def default_state_path() -> Path:
    """Where --resume looks when --state is omitted."""
    # Same per-user directory as favorites.json (LOCALAPPDATA on Windows).
    return Path(platformdirs.user_config_dir("interneto-install")) / "last-run.json"


def _load_state(path: Path) -> dict[str, dict[str, set[str]]]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(str(exc)) from exc
    if not isinstance(payload, dict):
        raise ValueError("the state file is not a JSON object")
    surfaces = payload.get("surfaces", {})
    if not isinstance(surfaces, dict):
        raise ValueError("'surfaces' is not an object")

    state: dict[str, dict[str, set[str]]] = {}
    for surface, values in surfaces.items():
        if not isinstance(values, dict):
            continue
        state[str(surface)] = {
            "commands": {
                item for item in values.get("commands", []) if isinstance(item, str)
            },
            "downloads": {
                item for item in values.get("downloads", []) if isinstance(item, str)
            },
        }
    return state


def _save_state(path: Path, state: dict[str, dict[str, set[str]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": STATE_VERSION,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "surfaces": {
            surface: {
                "commands": sorted(values.get("commands", set())),
                "downloads": sorted(values.get("downloads", set())),
            }
            for surface, values in state.items()
            if values.get("commands") or values.get("downloads")
        },
    }
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _apply_resume(run: "SurfaceRun", done: dict[str, set[str]]) -> None:
    """Drop commands/downloads already completed in a previous run."""
    completed_commands = done.get("commands", set())
    if completed_commands and run.commands:
        kept: list[list[str]] = []
        for command in run.commands:
            if command_hash(command) in completed_commands:
                run.resumed += 1
            else:
                kept.append(command)
        run.commands = kept

    completed_downloads = done.get("downloads", set())
    if completed_downloads and run.downloads:
        kept_downloads = []
        for item in run.downloads:
            if download_hash(item.url) in completed_downloads:
                run.resumed += 1
            else:
                kept_downloads.append(item)
        run.downloads = kept_downloads


@dataclass
class Options:
    system: detect.SystemInfo
    browser: str = "firefox"
    lib_lang: str = "javascript"
    only_missing: bool = False
    android_serial: str | None = None


@dataclass
class SurfaceRun:
    surface: str
    selected: list[str] = field(default_factory=list)
    commands: list[list[str]] = field(default_factory=list)
    downloads: list[commands.Download] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    already: list[str] = field(default_factory=list)
    resumed: int = 0
    note: str | None = None
    secrets: set[str] = field(default_factory=set)
    output: list[str] = field(default_factory=list)
    results: list[runner.CommandResult] = field(default_factory=list)
    executed: bool = False
    download_failures: int = 0

    @property
    def failures(self) -> int:
        return sum(1 for item in self.results if item.returncode != 0) + self.download_failures

    @property
    def succeeded(self) -> int:
        if self.downloads and self.executed:
            return max(0, len(self.downloads) - self.download_failures)
        return sum(1 for item in self.results if item.returncode == 0)


# --------------------------------------------------------------------------- #
# Installed-state inventories (--only-missing)
# --------------------------------------------------------------------------- #
def _capture(argv: list[str], timeout: int = 90) -> str | None:
    """Run a read-only command and return stdout, or None if unavailable."""
    exe = shutil.which(argv[0])
    if exe is None:
        return None
    try:
        completed = subprocess.run(
            [exe, *argv[1:]],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout if completed.returncode == 0 else None


def _winget_inventory() -> set[str] | None:
    exe = shutil.which("winget")
    if exe is None:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "installed.json"
        try:
            completed = subprocess.run(
                [
                    exe, "export", "--output", str(target),
                    "--accept-source-agreements", "--disable-interactivity",
                ],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if completed.returncode != 0 or not target.is_file():
            return None
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    installed: set[str] = set()
    for source in payload.get("Sources", []):
        for package in source.get("Packages", []):
            identifier = package.get("PackageIdentifier")
            if identifier:
                installed.add(identifier)
    return installed


def _desktop_inventory(pm_key: str) -> set[str] | None:
    """Installed package *names* as they appear in desktop-pkgs.json."""
    if pm_key == "windows_winget":
        return _winget_inventory()

    if pm_key == "macos_brew":
        formulae = _capture(["brew", "list", "--formula", "--quiet"])
        casks = _capture(["brew", "list", "--cask", "--quiet"])
        if formulae is None:
            return None
        return set(formulae.split()) | set((casks or "").split())

    readers: dict[str, list[str]] = {
        "linux_debian_apt": ["dpkg-query", "-W", "-f=${Package}\\n"],
        "linux_arch_pacman": ["pacman", "-Qq"],
        "linux_fedora_rpm": ["rpm", "-qa", "--qf", "%{NAME}\\n"],
        "linux_flatpak": ["flatpak", "list", "--app", "--columns=application"],
        "freebsd_pkg": ["pkg", "query", "-a", "%n"],
    }
    if pm_key in readers:
        output = _capture(readers[pm_key])
        return None if output is None else {line.strip() for line in output.splitlines() if line.strip()}

    if pm_key == "linux_snap":
        output = _capture(["snap", "list"])
        if output is None:
            return None
        names = set()
        for line in output.splitlines()[1:]:  # first line is the header
            parts = line.split()
            if parts:
                names.add(parts[0])
        return names

    if pm_key == "linux_gentoo_emerge":
        output = _capture(["qlist", "-IC"])
        return None if output is None else {line.strip() for line in output.splitlines() if line.strip()}

    return None  # nix-env attributes cannot be compared reliably


def _vscode_inventory() -> set[str] | None:
    output = _capture(["code", "--list-extensions"])
    if output is None:
        return None
    return {line.strip().lower() for line in output.splitlines() if line.strip()}


def _mobile_inventory(serial: str) -> set[str] | None:
    output = _capture(["adb", "-s", serial, "shell", "pm", "list", "packages"])
    if output is None:
        return None
    return {
        line.strip().removeprefix("package:")
        for line in output.splitlines()
        if line.strip().startswith("package:")
    }


def _filter_desktop(
    ids: list[str], pm_keys: list[str], installed: dict[str, set[str] | None]
) -> tuple[list[str], list[str]]:
    """Split favorites into (to install, already present) across managers.

    A package whose chosen manager has no readable inventory is kept (better to
    reinstall than to skip it blindly). Only a positive match marks it present.
    """
    packages = data.desktop_packages()
    keep: list[str] = []
    present: list[str] = []
    for pkg_id in ids:
        info = packages.get(pkg_id)
        key = commands.pick_desktop_manager(pm_keys, info) if info else None
        value = commands.desktop_value(info, key) if info and key else None
        known = installed.get(key) if key else None
        if value and known is not None and value in known:
            present.append(pkg_id)
        else:
            keep.append(pkg_id)
    return keep, present


def _filter_mobile(ids: list[str], installed: set[str]) -> tuple[list[str], list[str]]:
    packages = data.mobile_packages()
    keep: list[str] = []
    present: list[str] = []
    for pkg_id in ids:
        info = packages.get(pkg_id)
        app_id = (info or {}).get("package_manager", {}).get("android_pkg")
        if app_id and app_id in installed:
            present.append(pkg_id)
        else:
            keep.append(pkg_id)
    return keep, present


# --------------------------------------------------------------------------- #
# Turning favorites into one surface's plan
# --------------------------------------------------------------------------- #
def build_surface(surface: str, ids: list[str], opts: Options) -> SurfaceRun:
    run = SurfaceRun(surface=surface, selected=list(ids))

    if not ids:
        run.note = "No favorites for this surface."
        return run

    if surface == "desktop":
        managers = opts.system.available_managers
        if not managers:
            run.skipped = list(ids)
            run.note = "No supported package manager detected."
            return run
        if opts.only_missing:
            installed = {key: _desktop_inventory(key) for key in managers}
            if all(value is None for value in installed.values()):
                run.note = "Could not read the installed-package list; installing all favorites."
            else:
                run.selected, run.already = _filter_desktop(
                    run.selected, managers, installed
                )
        plan = commands.build_desktop(managers, run.selected)
        run.commands = plan.commands
        run.skipped = plan.non_installable
        run.note = plan.note or run.note
        run.secrets = plan.secrets

    elif surface == "vscode":
        if opts.only_missing:
            installed = _vscode_inventory()
            if installed is None:
                run.note = "Could not list installed VS Code extensions; installing all favorites."
            else:
                run.already = [
                    item for item in run.selected if item.lower() in installed
                ]
                run.selected = [
                    item for item in run.selected if item.lower() not in installed
                ]
        plan = commands.build_vscode(run.selected)
        run.commands = plan.commands
        run.note = plan.note or run.note

    elif surface == "lib":
        if opts.only_missing:
            run.note = "only-missing is not supported for language libraries; installing all."
        plan = commands.build_lib(opts.lib_lang, run.selected)
        run.commands = plan.commands
        if not plan.commands:
            run.note = f"No install command for language '{opts.lib_lang}'."

    elif surface == "browser":
        if opts.only_missing:
            run.note = "Browser extensions have no installed-state check; downloading all favorites."
        run.downloads, skipped = commands.browser_downloads(run.selected, opts.browser)
        run.skipped = skipped
        if not run.downloads:
            run.note = f"No downloadable extensions for {opts.browser} in this selection."

    elif surface == "mobile":
        devices = detect.adb_device_entries()
        if not devices:
            run.skipped = list(ids)
            run.note = "No Android device detected (need adb + USB debugging)."
            return run
        serials = [device.serial for device in devices]
        serial = opts.android_serial or serials[0]
        if serial not in serials:
            run.skipped = list(ids)
            run.note = f"Android device {serial!r} is not connected."
            return run
        if len(serials) > 1 and not opts.android_serial:
            run.note = (
                f"Multiple Android devices; using {serial}. "
                "Pass --android-serial to choose."
            )
        if opts.only_missing:
            installed = _mobile_inventory(serial)
            if installed is None:
                run.note = "Could not list packages on the device; opening all favorites."
            else:
                run.selected, run.already = _filter_mobile(run.selected, installed)
        plan = commands.build_mobile(serial, run.selected)
        run.commands = plan.commands
        run.skipped = plan.non_installable
        notes = [note for note in (run.note, plan.note) if note]
        run.note = "\n".join(notes) or None

    else:  # pragma: no cover - argparse restricts this
        run.note = f"Unknown surface: {surface}"

    return run


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def _version() -> str:
    try:
        return metadata.version("interneto-install")
    except metadata.PackageNotFoundError:
        return "0.0.0+dev"


def _force_utf8_streams() -> None:
    """Avoid UnicodeEncodeError on legacy Windows consoles (↓, ✓, ✗)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


class _Reporter:
    """Writes the same lines to stdout (unless --json) and the optional log."""

    def __init__(self, log: TextIO | None, quiet: bool) -> None:
        self.log = log
        self.quiet = quiet

    def header(self, text: str) -> None:
        if self.log:
            self.log.write(text + "\n")
        if not self.quiet:
            print(text)

    def line(self, run: SurfaceRun | None, text: str) -> None:
        if run is not None:
            run.output.append(text)
        if self.log:
            self.log.write(text + "\n")
        if not self.quiet:
            print(text)


def _report_json(
    runs: list[SurfaceRun],
    args: Any,
    system: detect.SystemInfo,
    state_path: Path | None = None,
) -> dict:
    surfaces = []
    for run in runs:
        surfaces.append(
            {
                "surface": run.surface,
                "selected": run.selected,
                "already_installed": run.already,
                "resumed": run.resumed,
                "skipped": run.skipped,
                "note": run.note,
                "commands": run.commands,
                "downloads": [
                    {"name": item.name, "filename": item.filename, "url": item.url}
                    for item in run.downloads
                ],
                "executed": run.executed,
                "results": [
                    {
                        "argv": item.argv,
                        "returncode": item.returncode,
                        "error": item.error,
                    }
                    for item in run.results
                ],
                "failures": run.failures,
                "output": run.output,
            }
        )

    command_count = sum(len(run.commands) for run in runs)
    return {
        "version": _version(),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "system": {
            "os": system.os_name,
            "label": system.os_label,
            "package_manager": system.pm_key,
            "fallbacks": system.pm_fallbacks,
        },
        "dry_run": bool(args.dry_run),
        "executed": any(run.executed for run in runs),
        "needs_yes": not bool(args.dry_run) and not bool(args.yes),
        "resuming": bool(args.resume),
        "state": str(state_path) if state_path else None,
        "android_serial": getattr(args, "android_serial", None),
        "surfaces": surfaces,
        "summary": {
            "surfaces": len(runs),
            "commands": command_count,
            "succeeded": sum(run.succeeded for run in runs),
            "failed": sum(run.failures for run in runs),
            "skipped": sum(len(run.skipped) for run in runs),
            "already_installed": sum(len(run.already) for run in runs),
            "resumed": sum(run.resumed for run in runs),
        },
        "log": str(args.log) if args.log else None,
    }


def run_headless(args: Any) -> int:
    """Apply favorites without the TUI. Returns a process exit code."""
    _force_utf8_streams()
    runner.refresh_path()

    favorites_set = favorites.load()
    if favorites.last_error:
        print(f"error: {favorites.last_error}", file=sys.stderr)
        return EXIT_USAGE

    if args.lib_lang not in data.lib_languages():
        print(
            f"error: unknown language '{args.lib_lang}'. "
            f"Choose one of: {', '.join(sorted(data.lib_languages()))}",
            file=sys.stderr,
        )
        return EXIT_USAGE

    requested = args.surface or ["desktop"]
    surfaces: list[str] = []
    for surface in requested:
        if surface == "all":
            for item in SURFACES:
                if item not in surfaces:
                    surfaces.append(item)
        elif surface not in SURFACES:
            print(f"error: unknown surface '{surface}'", file=sys.stderr)
            return EXIT_USAGE
        elif surface not in surfaces:
            surfaces.append(surface)

    system = detect.detect_system()
    android_serial = getattr(args, "android_serial", None)
    if "mobile" in surfaces:
        devices = detect.adb_devices()
        if android_serial and android_serial not in devices:
            print(
                f"error: Android device {android_serial!r} is not connected. "
                f"Found: {', '.join(devices) or 'none'}",
                file=sys.stderr,
            )
            return EXIT_USAGE
        if len(devices) > 1 and not android_serial and surfaces == ["mobile"]:
            print(
                "error: multiple Android devices connected; pass --android-serial. "
                f"Found: {', '.join(devices)}",
                file=sys.stderr,
            )
            return EXIT_USAGE

    opts = Options(
        system=system,
        browser=args.browser,
        lib_lang=args.lib_lang,
        only_missing=bool(args.only_missing),
        android_serial=android_serial,
    )
    runs = [
        build_surface(surface, list(favorites_set.get(surface, [])), opts)
        for surface in surfaces
    ]

    execute = bool(args.yes) and not bool(args.dry_run)

    state_path: Path | None = None
    if getattr(args, "state", None):
        state_path = Path(args.state).expanduser()
    elif getattr(args, "resume", False):
        state_path = default_state_path()
    if state_path is not None and state_path.is_dir():
        print(f"error: --state must be a file, not a directory: {state_path}", file=sys.stderr)
        return EXIT_USAGE

    state: dict[str, dict[str, set[str]]] = {}
    if getattr(args, "resume", False):
        try:
            state = _load_state(state_path)
        except (OSError, ValueError) as exc:
            print(f"error: could not read resume state {state_path}: {exc}", file=sys.stderr)
            return EXIT_USAGE
        if not state:
            print(
                f"note: no completed work in {state_path}; starting fresh.",
                file=sys.stderr,
            )
    elif state_path is not None and execute:
        # A new run without --resume starts a new state file.
        try:
            _save_state(state_path, {})
        except OSError as exc:
            print(f"error: could not write state {state_path}: {exc}", file=sys.stderr)
            return EXIT_USAGE

    if getattr(args, "resume", False):
        for run in runs:
            _apply_resume(run, state.get(run.surface, {}))

    log: TextIO | None = None
    if args.log:
        path = Path(args.log).expanduser()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            log = path.open("w", encoding="utf-8", newline="\n")
        except OSError as exc:
            print(f"error: could not open log {path}: {exc}", file=sys.stderr)
            return EXIT_USAGE

    reporter = _Reporter(log, quiet=bool(args.json))
    try:
        reporter.header(f"# interneto-install {_version()} — {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
        reporter.header(f"# system: {system.os_label} / {system.pm_label}")
        reporter.header(f"# surfaces: {', '.join(surfaces)}")
        if state_path is not None:
            mode = " (resume)" if args.resume else ""
            reporter.header(f"# state: {state_path}{mode}")
        reporter.header(f"# mode: {'dry-run' if args.dry_run else 'execute' if execute else 'plan only'}")
        reporter.header("")

        for run in runs:
            reporter.line(run, f"== {run.surface} ==")
            if run.note:
                reporter.line(run, f"note: {run.note}")
            if run.already:
                reporter.line(run, f"already installed: {', '.join(run.already)}")
            if run.resumed:
                reporter.line(run, f"resumed (already completed): {run.resumed}")
            if run.skipped:
                reporter.line(run, f"skipped/unavailable: {', '.join(run.skipped)}")
            for command in run.commands:
                reporter.line(run, "$ " + redact(shlex.join(command), run.secrets))
            for download in run.downloads:
                reporter.line(run, f"↓ {download.name}  ({download.filename})  ← {download.url}")

            if execute and run.downloads:
                for line in runner.run_browser_installs(run.downloads):
                    reporter.line(run, line)
                    if "✗" in line:
                        run.download_failures += 1
                    elif state_path is not None and "✓ Saved" in line:
                        for item in run.downloads:
                            if item.filename in line:
                                done = state.setdefault(
                                    run.surface,
                                    {"commands": set(), "downloads": set()},
                                )
                                done["downloads"].add(download_hash(item.url))
                                try:
                                    _save_state(state_path, state)
                                except OSError as exc:
                                    print(
                                        f"warning: could not save state: {exc}",
                                        file=sys.stderr,
                                    )
                run.executed = True
            elif execute and run.commands:
                results: list[runner.CommandResult] = []

                def _record(result: runner.CommandResult, surface: str = run.surface) -> None:
                    if state_path is None or result.returncode != 0:
                        return
                    done = state.setdefault(
                        surface, {"commands": set(), "downloads": set()}
                    )
                    done["commands"].add(command_hash(result.argv))
                    try:
                        _save_state(state_path, state)
                    except OSError as exc:
                        print(
                            f"warning: could not save state: {exc}",
                            file=sys.stderr,
                        )

                for line in runner.run_commands(
                    run.commands,
                    run.secrets,
                    continue_on_error=not bool(args.fail_fast),
                    results=results,
                    on_result=_record,
                ):
                    reporter.line(run, line)
                run.results = results
                run.executed = True
            elif run.resumed and not run.commands and not run.downloads:
                reporter.line(run, "(nothing left — resumed)")
            elif not run.commands and not run.downloads:
                reporter.line(run, "(nothing to do)")
            elif args.dry_run:
                reporter.line(run, "(dry run — not executed)")
            else:
                reporter.line(run, "(not executed — re-run with --yes)")

            if run.executed:
                # Let the next surface see code/npm/etc. installed by this one.
                runner.refresh_path()
            reporter.line(run, "")

        summary = (
            f"Summary: {len(runs)} surface(s), "
            f"{sum(len(run.commands) for run in runs)} command(s) planned, "
            f"{sum(run.succeeded for run in runs)} ok, "
            f"{sum(run.failures for run in runs)} failed, "
            f"{sum(len(run.already) for run in runs)} already installed, "
            f"{sum(run.resumed for run in runs)} resumed, "
            f"{sum(len(run.skipped) for run in runs)} skipped."
        )
        reporter.header(summary)
        if not execute and not args.dry_run:
            reporter.header("Refusing to run without --yes. Add --yes to execute, or --dry-run to inspect only.")

        if args.json:
            print(
                json.dumps(
                    _report_json(runs, args, system, state_path),
                    indent=2,
                    ensure_ascii=False,
                )
            )
    finally:
        if log:
            log.close()

    if not execute and not args.dry_run:
        return EXIT_USAGE
    if any(run.failures for run in runs):
        return EXIT_FAILED
    return EXIT_OK
