# Operating instructions for AI agents working in this repo

`interneto-install` is a cross-platform Textual TUI that installs desktop apps,
libraries, editor/browser extensions, Android apps and AI-agent plugins. The
package data is the JSON in `interneto_install/data/`, mirrored from the
website's `public/pkgs/`.

## Before changing code

1. Read [`README.md`](README.md) and [`docs/agent/HANDOFF.md`](docs/agent/HANDOFF.md).
2. Install and test:

   ```bash
   python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -e ".[dev]"
   python -m pytest -q
   ```

3. Windows, macOS and Linux are all supported targets; CI runs the suite on
   all three. A change that only works on the machine you are sitting at is
   not finished.

## Invariants (do not regress)

- **Commands are argv lists, never shell strings.** `commands.py` builds and
  validates them; anything that genuinely needs a shell (`|`, `;`, redirects,
  cmd.exe builtins, `%VAR%` on a non-Windows host) is reported as “run
  manually” rather than passed to `shlex` and silently mangled.
- **Never print a credential.** Values of env vars whose names look like
  `*TOKEN*`, `*SECRET*`, `*PASSWORD*`, `*API_KEY*` are collected in
  `CommandPlan.secrets` and redacted by `secrets.redact` in both the preview
  and the live log.
- **Favorites merge per surface** over the bundled defaults, so a hand-edited
  file with only `desktop` does not wipe the other tabs. The per-user path
  comes from `platformdirs` (`%LOCALAPPDATA%` on Windows, not `%APPDATA%`);
  `--favorites PATH` / `INTERNETO_FAVORITES` override it.
- **Installers must not prompt.** Linux/macOS prefixes carry `-y` /
  `--noconfirm` / `--noninteractive`; winget gets the agreement and
  `--disable-interactivity` flags; child stdin is `/dev/null`; sudo is
  pre-authenticated with the TUI suspended.
- **Headless is a thin orchestrator over the same planners.** `headless.py`
  must call `commands.*`; do not duplicate command-building there. It is the
  only place that should know about `--only-missing` inventories, JSON output
  and exit codes.
- **Never assume the primary package manager.** `SystemInfo.available_managers`
  is the preference order (primary, then detected fallbacks);
  `commands.pick_desktop_manager` chooses per package. A flatpak-only app on an
  apt box must stay installable. macOS casks come from
  `data/brew-casks.json` (`scripts/sync_brew_casks.py`), never from a guess.
- **Cancellation kills the process tree.** `runner.RunControl` is the only way
  to stop a run; commands are spawned in their own session/process group.
  Leaving the run screen must stop a live package manager.
- **Resume state is command hashes, written atomically.** `--state` is cleared
  only at the start of a real run without `--resume`; `--dry-run` never touches
  it. Do not store secrets in it.
- **Linux detection comes from `/etc/os-release`.** Do not infer the distro
  from whichever binary happens to be first; keep `_distro_preference` and the
  immutable-Fedora/nix-last rules. `runner.refresh_path()` must run after a
  surface so later tabs see freshly installed tools.
- `python -m pytest -q` must stay green (currently 67 tests).

## Closing a session

Update [`docs/agent/HANDOFF.md`](docs/agent/HANDOFF.md) with current state and
the exact next step, and append a short entry to
[`docs/agent/JOURNAL.md`](docs/agent/JOURNAL.md). Do not leave the baton only
in chat.
