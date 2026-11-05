"""Build the actual install commands for each installer surface.

This mirrors the web toolbox's command-builder logic, but produces ``argv``
lists (no shell) so they can be executed safely and cross-platform.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
from collections.abc import Iterable
from dataclasses import dataclass, field

from . import data
from .detect import PM_LABELS
from .secrets import is_secret_name, redact

_ENV_VAR = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")
_WIN_ENV_VAR = re.compile(r"%([A-Za-z_][A-Za-z0-9_]*)%")
# Commands that need a real shell: pipes, redirects, chaining other than the
# top-level "&&" we split on, command substitution, and cmd.exe builtins.
_SHELL_SYNTAX = re.compile(r"[|<>;`&]|\$\(|%[A-Za-z_][A-Za-z0-9_]*%")
_CMD_BUILTIN = re.compile(r"^\s*(if\s+(not\s+)?exist|cd\s+/d|for\s+%|set\s+)", re.IGNORECASE)
_WINDOWS = os.name == "nt"


@dataclass
class CommandPlan:
    commands: list[list[str]] = field(default_factory=list)  # argv lists, run in order
    non_installable: list[str] = field(default_factory=list)  # display names skipped
    note: str | None = None  # caveats (e.g. assisted install)
    secrets: set[str] = field(default_factory=set)  # values to redact in preview/logs

    @property
    def has_commands(self) -> bool:
        return bool(self.commands)

    def preview(self) -> str:
        return "\n".join(
            redact(shlex.join(cmd), self.secrets) for cmd in self.commands
        )


# --------------------------------------------------------------------------- #
# Desktop applications (native package managers)
# --------------------------------------------------------------------------- #
def normalize_managers(pm_keys: str | Iterable[str] | None) -> list[str]:
    """Accept one manager key or a preference-ordered list of them."""
    if pm_keys is None:
        return []
    if isinstance(pm_keys, str):
        return [pm_keys] if pm_keys else []
    return [key for key in pm_keys if key]


def desktop_value(info: dict, pm_key: str) -> str | None:
    """Package name for ``pm_key``, including the pacman -> AUR fallback."""
    managers = info.get("package_manager", {})
    value = managers.get(pm_key)
    if not value and pm_key == "linux_arch_pacman":
        value = managers.get("linux_arch_aur")
    return value


def pick_desktop_manager(pm_keys: str | Iterable[str] | None, info: dict) -> str | None:
    """First manager in preference order that can install this package."""
    for key in normalize_managers(pm_keys):
        if desktop_value(info, key):
            return key
    return None


def build_desktop(
    pm_keys: str | Iterable[str] | None, selected_ids: list[str]
) -> CommandPlan:
    """Build commands for the first available manager per package.

    ``pm_keys`` is preference-ordered: the detected primary manager first, then
    the fallbacks present on the host (e.g. apt, then flatpak, then snap). That
    is what keeps a package that only exists as a flatpak from being reported
    as uninstallable on a Debian box.
    """
    managers = normalize_managers(pm_keys)
    packages = data.desktop_packages()
    grouped: dict[str, list[str]] = {}
    assignments: dict[str, str] = {}
    aur_names: list[str] = []
    non_installable: list[str] = []

    for pkg_id in selected_ids:
        info = packages.get(pkg_id)
        if not info:
            continue
        key = pick_desktop_manager(managers, info)
        if key is None:
            non_installable.append(info.get("name", pkg_id))
            continue
        value = desktop_value(info, key)
        if not value:
            continue
        assignments[pkg_id] = key
        if key == "linux_arch_pacman" and not info.get("package_manager", {}).get(key):
            aur_names.append(value)
        else:
            grouped.setdefault(key, []).append(value)

    plan = CommandPlan(non_installable=non_installable)
    used: list[str] = []
    notes: list[str] = []

    for key in managers:
        values = list(dict.fromkeys(grouped.get(key, [])))
        if values:
            used.append(key)
            if key == "windows_winget":
                # winget installs one package per invocation. The agreement and
                # interactivity flags are what make it usable from a TUI that owns
                # the terminal: without them winget can block on a prompt that is
                # not visible anymore.
                for name in values:
                    plan.commands.append([
                        "winget", "install", "--exact", "--id", name,
                        "--silent", "--disable-interactivity",
                        "--accept-package-agreements", "--accept-source-agreements",
                    ])
            elif key == "macos_brew":
                # GUI apps live in casks; `brew install <cask>` only works on
                # recent Homebrew versions, so split them explicitly.
                casks = data.brew_casks()
                formulae = [name for name in values if name not in casks]
                cask_names = [name for name in values if name in casks]
                prefix = shlex.split(data.distro_prefixes().get(key, ""))
                if formulae and prefix:
                    plan.commands.append([*prefix, *formulae])
                if cask_names:
                    plan.commands.append(["brew", "install", "--cask", *cask_names])
            else:
                prefix = shlex.split(data.distro_prefixes().get(key, ""))
                if prefix:
                    plan.commands.append([*prefix, *values])

        if key == "linux_arch_pacman" and aur_names:
            # yay/paru both escalate on their own; pass --noconfirm so they don't
            # stop the batch on an AUR package that needs rebuilding.
            helper = (
                "yay" if shutil.which("yay")
                else "paru" if shutil.which("paru")
                else "yay"
            )
            plan.commands.append(
                [helper, "-S", "--noconfirm", *dict.fromkeys(aur_names)]
            )
            used.append("AUR")
            if shutil.which(helper):
                notes.append(f"AUR packages use {helper}.")
            else:
                notes.append(
                    "AUR packages need yay or paru; neither was found on PATH."
                )

    if len(used) > 1:
        labels = [PM_LABELS.get(key, key) for key in used]
        notes.insert(0, f"Installs via {', '.join(labels)}.")

    external = data.apt_external_repos()
    if external and "linux_debian_apt" in used:
        external_names = [
            f"{packages[pkg_id].get('name', pkg_id)} ({external[pkg_id]})"
            for pkg_id, key in assignments.items()
            if key == "linux_debian_apt" and pkg_id in external
        ]
        if external_names:
            notes.append(
                "Needs an external apt repo: " + ", ".join(external_names) + "."
            )

    if notes:
        plan.note = "\n".join(notes)

    return plan


# --------------------------------------------------------------------------- #
# VS Code extensions  ->  code --install-extension <id>
# --------------------------------------------------------------------------- #
def build_vscode(selected_ids: list[str]) -> CommandPlan:
    flags: list[str] = []
    for ext_id in selected_ids:
        flags += ["--install-extension", ext_id]
    plan = CommandPlan()
    if flags:
        plan.commands.append(["code", *flags])
        plan.note = "Requires the VS Code 'code' command on PATH."
    return plan


# --------------------------------------------------------------------------- #
# Libraries  ->  <language manager cmd> <names...>
# --------------------------------------------------------------------------- #
def build_lib(language: str, selected_names: list[str]) -> CommandPlan:
    langs = data.lib_languages()
    lang = langs.get(language, {})
    manager_cmd = lang.get("manager", {}).get("cmd", "")
    plan = CommandPlan()
    if selected_names and manager_cmd:
        plan.commands.append([*shlex.split(manager_cmd), *selected_names])
    return plan


# --------------------------------------------------------------------------- #
# AI agents (MCP servers / plugins): claude/codex/copilot CLI, or npx.
# --------------------------------------------------------------------------- #
def _resolve_install(entry: dict, agent_cli: str) -> dict | None:
    """Pick the install meant for this agent, never another agent's command.

    Order: exact match, then an agent-less install. Falling back to an
    arbitrary entry used to run e.g. Claude's command when the user selected
    Codex, which could install the wrong thing or fail confusingly.
    """
    installs = entry.get("installs") or []
    for want in (agent_cli, ""):
        for inst in installs:
            if inst.get("agent") == want:
                return inst
    return None


def _split_steps(cmd: str) -> list[str]:
    """Split a command on top-level ``&&`` and newlines, keeping quotes intact."""
    steps: list[str] = []
    buf: list[str] = []
    quote: str | None = None

    def flush() -> None:
        step = "".join(buf).strip()
        if step:
            steps.append(step)
        buf.clear()

    index = 0
    while index < len(cmd):
        char = cmd[index]
        if quote is not None:
            buf.append(char)
            if char == quote and (index == 0 or cmd[index - 1] != "\\"):
                quote = None
        elif char in {"'", '"'}:
            quote = char
            buf.append(char)
        elif char == "\n":
            flush()
        elif char == "&" and index + 1 < len(cmd) and cmd[index + 1] == "&":
            flush()
            index += 1
        else:
            buf.append(char)
        index += 1
    flush()
    return steps


def _split_argv(step: str, windows: bool) -> list[str]:
    """Split one simple command into argv, respecting Windows path rules."""
    if not windows:
        return shlex.split(step)
    # posix=False preserves backslashes and keeps quotes attached; strip the
    # surrounding quotes afterwards so the executable sees the real path.
    parts = shlex.split(step, posix=False)
    return [
        part[1:-1]
        if len(part) >= 2 and part[0] == part[-1] and part[0] in {"'", '"'}
        else part
        for part in parts
    ]


def _shell_reason(step: str, windows: bool) -> str | None:
    """Return why a step cannot run without a shell, or None if it can."""
    if _CMD_BUILTIN.match(step):
        return "uses cmd.exe builtins"
    if _SHELL_SYNTAX.search(step):
        return "Windows-only command" if not windows and _WIN_ENV_VAR.search(step) else "needs a shell"
    return None


def _expand(cmd: str, windows: bool) -> tuple[str, list[str]]:
    """Expand environment variables, returning the command and missing names."""
    names = _ENV_VAR.findall(cmd)
    if windows:
        names += _WIN_ENV_VAR.findall(cmd)
    missing = list(dict.fromkeys(name for name in names if name not in os.environ))
    if missing:
        return cmd, missing

    cmd = _ENV_VAR.sub(lambda match: os.environ[match.group(1)], cmd)
    if windows:
        cmd = _WIN_ENV_VAR.sub(lambda match: os.environ[match.group(1)], cmd)
    return cmd, []


def _secret_values(cmd: str, windows: bool) -> set[str]:
    """Values of secret-looking variables referenced by ``cmd``."""
    names = _ENV_VAR.findall(cmd)
    if windows:
        names += _WIN_ENV_VAR.findall(cmd)
    return {
        os.environ[name]
        for name in names
        if is_secret_name(name) and os.environ.get(name)
    }


def build_agents(agent_cli: str, selected_ids: list[str]) -> CommandPlan:
    agents = data.agents()
    plan = CommandPlan()
    needs_env: list[str] = []
    interactive_only: list[str] = []
    manual: list[str] = []

    for pkg_id in selected_ids:
        entry = agents.get(pkg_id)
        if not entry:
            continue
        name = entry.get("name", pkg_id)
        inst = _resolve_install(entry, agent_cli)
        if not inst or not inst.get("cmd"):
            plan.non_installable.append(name)
            continue

        original = inst["cmd"]
        windows_only = bool(_WIN_ENV_VAR.search(original))
        if windows_only and not _WINDOWS:
            manual.append(f"{name} (Windows-only command)")
            continue

        cmd, missing = _expand(original, _WINDOWS)
        if missing:
            needs_env.append(f"{name} ({', '.join(f'${v}' for v in missing)})")
            continue
        plan.secrets |= _secret_values(original, _WINDOWS)

        # Some entries are slash-commands meant to be pasted into an already-running
        # agent session (e.g. Claude Code's `/plugin ...`), not a shell command -
        # there is nothing this CLI runner can execute for those.
        steps = _split_steps(cmd)
        if any(step.startswith("/") for step in steps):
            interactive_only.append(name)
            continue

        reason = next(
            (reason for step in steps if (reason := _shell_reason(step, _WINDOWS))),
            None,
        )
        if reason:
            manual.append(f"{name} ({reason})")
            continue

        try:
            plan.commands.extend(_split_argv(step, _WINDOWS) for step in steps)
        except ValueError:
            manual.append(f"{name} (could not parse the command)")
            continue

    notes = []
    if needs_env:
        notes.append(f"Skipped (missing env var): {', '.join(needs_env)}")
    if interactive_only:
        notes.append(
            f"Skipped (paste into a running agent session instead): {', '.join(interactive_only)}"
        )
    if manual:
        notes.append(f"Skipped (run manually): {', '.join(manual)}")
    if notes:
        plan.note = "\n".join(notes)
    return plan


# --------------------------------------------------------------------------- #
# Mobile (Android via adb): open each app's store page on the device.
# adb cannot silently install Play Store apps, so we deep-link to the store.
# --------------------------------------------------------------------------- #
def build_mobile(serial: str, selected_ids: list[str]) -> CommandPlan:
    packages = data.mobile_packages()
    plan = CommandPlan()
    for pkg_id in selected_ids:
        info = packages.get(pkg_id)
        if not info:
            continue
        app_id = info.get("package_manager", {}).get("android_pkg")
        if not app_id:
            plan.non_installable.append(info.get("name", pkg_id))
            continue
        plan.commands.append([
            "adb", "-s", serial, "shell", "am", "start",
            "-a", "android.intent.action.VIEW",
            "-d", f"market://details?id={app_id}",
        ])
    if plan.commands:
        plan.note = "Opens each Play Store page on the device — tap Install there."
    return plan


# --------------------------------------------------------------------------- #
# Browser extensions: download the packaged extension and open it so the
# browser installs it. Firefox ships .xpi (from AMO), Chromium ships .crx
# (from Google's update service).
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Download:
    name: str  # display name
    url: str  # source URL
    filename: str  # suggested local filename


# A recent-enough version string keeps Google's crx endpoint happy.
_CRX_PRODVERSION = "120.0"


def browser_downloads(selected_ids: list[str], browser: str) -> tuple[list[Download], list[str]]:
    """Return (downloads, skipped_names) for the chosen browser ('firefox'|'chromium')."""
    extensions = data.browser_extensions()
    downloads: list[Download] = []
    skipped: list[str] = []
    for ext_id in selected_ids:
        info = extensions.get(ext_id)
        if not info:
            continue
        name = info.get("name", ext_id)
        if browser == "firefox" and info.get("firefox_slug"):
            slug = info["firefox_slug"]
            downloads.append(Download(
                name,
                # AMO "latest" endpoint 302-redirects to the signed .xpi.
                f"https://addons.mozilla.org/firefox/downloads/latest/{slug}/",
                f"{slug}.xpi",
            ))
        elif browser == "chromium" and info.get("chromium_id"):
            cid = info["chromium_id"]
            downloads.append(Download(
                name,
                "https://clients2.google.com/service/update2/crx"
                "?response=redirect&acceptformat=crx2,crx3"
                f"&prodversion={_CRX_PRODVERSION}"
                f"&x=id%3D{cid}%26installsource%3Dondemand%26uc",
                f"{cid}.crx",
            ))
        else:
            skipped.append(name)
    return downloads, skipped
