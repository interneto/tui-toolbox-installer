# Journal — interneto-tui-installer

Newest first; the handoff carries current state.

## 2026-11-05 — distro detection, PATH refresh and Android selector

Linux manager selection now reads `/etc/os-release` instead of trusting the
first binary found: openSUSE/Alpine/Void/NixOS are labelled correctly,
immutable Fedora prefers flatpak and refuses dnf, and an incidental `nix-env`
is last outside NixOS. Added zypper/apk/xbps/rpm-ostree labels and prefixes
(the catalog still has no package names for them). `runner.refresh_path()`
re-reads the Windows registry PATH and adds tool dirs everywhere, so
`--surface all` can find a freshly installed `code`/`npm`. Android now parses
`adb devices -l`, has a device selector in the mobile tab and
`--android-serial` in headless. A small apt-external-repos data file flags
packages needing third-party repositories. 67 tests pass.

## 2026-11-05 — cancellation and resume

`RunScreen` now has a Stop button and Esc; `runner.RunControl` kills the
process tree (POSIX session + SIGTERM/SIGKILL, Windows `taskkill /T /F`) and
leaving the screen stops a live run. Headless gained `--state PATH` /
`--resume`: each successful command hash is written atomically and skipped on
the next run; `--dry-run` never touches the file. Browser downloads now use
`platformdirs.user_downloads_dir()`. 57 tests pass.

## 2026-11-05 — fallback managers and macOS casks

Desktop packages now resolve to the first detected manager that has them
(primary first, then flatpak/snap), instead of being dropped when the primary
lacks them. On this Debian host that is 171 → 226 items; the Toolbox profile
drops from 37 to 26 skipped. Added `data/brew-casks.json` (135 casks generated
from the Homebrew API) so GUI apps use `brew install --cask`; the generator is
`scripts/sync_brew_casks.py` and CI verifies the file ships in the wheel.
49 tests pass.

## 2026-11-05 — headless mode

Added `headless.py` and the CLI flags around it: `--surface` (repeatable,
`all`), `--yes`, `--dry-run`, `--only-missing`, `--json`, `--log`,
`--fail-fast`, `--browser`, `--lib-lang`. It reuses `commands.*`; the new
parts are native installed-state inventories, JSON/exit-code reporting and a
runner option to continue past failures with per-command results. `--favorites`
alone still opens the TUI. 43 tests pass (was 33).

## 2026-11-05 — P0s of the clean-reinstall flow

Applied the review's P0s: favorites merge per surface plus the real
`%LOCALAPPDATA%` path and `--favorites`; non-interactive flags for
apt/dnf/pacman/emerge/flatpak/pkg/winget/AUR; sudo preflight with the TUI
suspended; Windows-safe agent argv (no more `shlex` eating backslashes),
shell-only snippets skipped instead of half-run, no cross-CLI fallback; and
redaction of secret env values in preview/log. Fixed the corrupted `daw-mcp`
Copilot path in the data. 33 tests pass (was 21). P1s recorded in the handoff.
