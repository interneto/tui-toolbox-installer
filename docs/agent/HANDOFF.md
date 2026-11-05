# Handoff — interneto-tui-installer

Updated: 2026-11-05

Read with [`../../AGENTS.md`](../../AGENTS.md). Branch `main`; version `0.1.0`.

## Current state

- P0 review of the clean-reinstall flow is applied:
  - `favorites.load()` merges the user file over bundled defaults **per
    surface**; invalid JSON sets `favorites.last_error` and the app warns
    instead of silently installing a different set.
  - `favorites.user_path()` honours `INTERNETO_FAVORITES`, and
    `interneto-install --favorites PATH` sets it. The documented Windows path
    is `%LOCALAPPDATA%\interneto-install\favorites.json` (platformdirs uses
    local AppData, not roaming `%APPDATA%`).
  - `favorites.save()` writes atomically (temp file + `os.replace`).
  - Package-manager prefixes in `data/config.json` are non-interactive
    (`apt-get -y`, `dnf -y`, `pacman --noconfirm`, `emerge --ask=n`,
    `flatpak --noninteractive`, `pkg -y`); winget gets
    `--silent --disable-interactivity --accept-*-agreements`; AUR uses
    yay/paru with `--noconfirm`.
  - The runner passes `stdin=DEVNULL`, sets non-interactive env defaults and
    starts the child in its own process group/session.
  - Before a plan that starts with `sudo`, the app authenticates with
    `sudo -v` while the TUI is suspended (`App.suspend()`).
  - Agent commands: exact CLI match only (no falling back to another CLI's
    command), `%VAR%` expanded on Windows, POSIX/Windows argv splitting that
    preserves backslashes, top-level `&&`/newline steps, shell-only snippets
    skipped with a “run manually” note, and secret values redacted from the
    preview and log.
  - Fixed the corrupted `daw-mcp` Copilot path in `data/agents-pkgs.json`.
- **Headless mode** (`interneto_install/headless.py`, 2026-11-05):
  - `--surface` (repeatable, `all`), `--yes`, `--dry-run`, `--only-missing`,
    `--json`, `--log PATH`, `--fail-fast`, `--browser`, `--lib-lang`.
  - It is a thin orchestrator over `commands.*`; no command-building is
    duplicated. `--only-missing` uses native inventories (`winget export`,
    `brew list`, `dpkg-query`, `pacman -Qq`, `rpm -qa`, `flatpak list`,
    `snap list`, `pkg info`, `code --list-extensions`,
    `adb shell pm list packages`).
  - Exit codes: 0 ok, 1 one or more failed commands, 2 usage / missing
    `--yes` / unreadable favorites. `--json` keeps stdout clean; `--log`
    writes the text log; `--fail-fast` restores stop-on-first-error.
  - `runner.run_commands` now accepts `continue_on_error` and an optional
    `results` list of `CommandResult`; the TUI keeps the old behaviour.
  - `--favorites PATH` alone still launches the TUI; any headless flag
    switches to `run_headless`.
- **Fallback managers and macOS casks** (2026-11-05):
  - `SystemInfo.available_managers` exposes primary + fallbacks.
    `commands.pick_desktop_manager` resolves per package, so flatpak/snap
    packages are no longer dropped when the primary manager lacks them (on
    this Debian host: 171 → 226 desktop items; 55 more packages, 37 → 26
    skipped in the Toolbox profile).
  - `build_desktop` groups commands by manager and notes which were used.
  - `data/brew-casks.json` (135 casks) drives `brew install --cask`;
    regenerate with `python scripts/sync_brew_casks.py`.
  - CI checks `brew-casks.json` is present in the wheel.
- **Cancellation and resume** (2026-11-05):
  - `runner.RunControl` + a Stop button / Esc in `RunScreen`; commands run in
    their own session/process group, POSIX gets SIGTERM then SIGKILL after 3 s,
    Windows uses `taskkill /T /F`. Leaving the screen stops a live run.
  - Headless `--state PATH` records every successful command hash atomically;
    `--resume` skips completed commands (default state:
    `<config>/interneto-install/last-run.json`). `--dry-run` never touches it.
  - Browser downloads use `platformdirs.user_downloads_dir()` instead of a
    hardcoded `~/Downloads`.
- **Detection, PATH and Android** (2026-11-05):
  - Linux managers now come from `/etc/os-release` (`ID`/`ID_LIKE`), with
    zypper/apk/xbps/rpm-ostree labels and prefixes. Immutable Fedora prefers
    flatpak and never uses dnf; `nix-env` is last outside NixOS. The catalog
    still has no zypper/apk/xbps package names, so those hosts fall back to
    flatpak/snap.
  - `runner.refresh_path()` re-reads the Windows registry PATH and adds the
    usual tool dirs on every platform; called after each executed surface and
    after a TUI run.
  - Android: `adb devices -l` parsing with model labels, a device selector in
    the mobile tab, and `--android-serial` for headless (required if `mobile`
    is the only surface and several devices are attached).
  - `data/apt-external-repos.json` flags apt names that need a third-party
    repository; it is a note, not an automatic repo setup.
- `pyproject.toml` declares `platformdirs` directly (it was only transitive
  through Textual).

## Verification

```bash
python -m pytest -q        # 67 passed
python -m interneto_install --detect
python -m interneto_install --surface all --dry-run --json
```

CI (`.github/workflows/ci.yml`) still runs 3 OS × Python 3.10–3.13.

## Next action

P1s from the review, in order:

1. Catalog coverage for zypper/apk/xbps (the app can already drive them) and
   third-party apt repo setup if it is ever automated; for now they are
   flagged and left manual.
2. Verify `scripts/install.sh`/`install.ps1` pinning (currently a moving
   `main` install) before calling the one-liner release-ready.
3. Real-machine verification of the TUI cancellation and the macOS cask list;
   both are covered by tests but not by a physical Windows/macOS run.
