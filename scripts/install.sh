#!/bin/sh
# Interneto · Toolbox Installer — macOS / Linux bootstrap.
#
# Usage (one-liner):
#   curl -fsSL https://raw.githubusercontent.com/interneto/tui-toolbox-installer/main/scripts/install.sh | sh
#
# Installs `uv` if missing, installs the app from GitHub as a uv tool, and
# launches it. Re-run any time to update to the latest version.

set -eu
REPO="git+https://github.com/interneto/tui-toolbox-installer"

printf '\033[36mInterneto · Toolbox Installer\033[0m\n'

# 1. Ensure uv is available.
if ! command -v uv >/dev/null 2>&1; then
    printf '\033[33mInstalling uv (Python tool manager)...\033[0m\n'
    curl -fsSL https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

# 2. Install (or update) the app from GitHub.
printf '\033[33mInstalling interneto-install from GitHub...\033[0m\n'
uv tool install --force "$REPO"

export PATH="$HOME/.local/bin:$PATH"

# 3. Launch. When run via `curl | sh`, stdin is the script, so reattach the
#    terminal so the TUI can read the keyboard.
if [ -e /dev/tty ]; then
    printf '\033[32mLaunching — press q to quit.\033[0m\n'
    exec interneto-install < /dev/tty
else
    printf '\033[32mInstalled. Run:\033[0m interneto-install\n'
fi
