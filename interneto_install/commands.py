"""Build the actual install commands for each installer surface.

This mirrors the web toolbox's command-builder logic, but produces ``argv``
lists (no shell) so they can be executed safely and cross-platform.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field

from . import data


@dataclass
class CommandPlan:
    commands: list[list[str]] = field(default_factory=list)  # argv lists, run in order
    non_installable: list[str] = field(default_factory=list)  # display names skipped
    note: str | None = None  # caveats (e.g. assisted install)

    @property
    def has_commands(self) -> bool:
        return bool(self.commands)

    def preview(self) -> str:
        return "\n".join(shlex.join(cmd) for cmd in self.commands)


# --------------------------------------------------------------------------- #
# Desktop applications (native package managers)
# --------------------------------------------------------------------------- #
def build_desktop(pm_key: str, selected_ids: list[str]) -> CommandPlan:
    packages = data.desktop_packages()
    names: list[str] = []
    aur_names: list[str] = []
    non_installable: list[str] = []

    for pkg_id in selected_ids:
        info = packages.get(pkg_id)
        if not info:
            continue
        managers = info.get("package_manager", {})
        value = managers.get(pm_key)
        if value:
            names.append(value)
        elif pm_key == "linux_arch_pacman" and managers.get("linux_arch_aur"):
            aur_names.append(managers["linux_arch_aur"])
        else:
            non_installable.append(info.get("name", pkg_id))

    plan = CommandPlan(non_installable=non_installable)

    if pm_key == "windows_winget":
        # winget installs one package per invocation.
        for name in names:
            plan.commands.append(["winget", "install", "--exact", "--id", name])
    elif names:
        prefix = shlex.split(data.distro_prefixes().get(pm_key, ""))
        if prefix:
            plan.commands.append([*prefix, *names])

    if aur_names:
        plan.commands.append(["yay", "-S", *aur_names])
        plan.note = "AUR packages use yay; make sure it is installed."

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
# Browser extensions: store URLs (no cross-browser CLI install exists).
# --------------------------------------------------------------------------- #
def browser_store_urls(selected_ids: list[str], browser: str) -> tuple[list[str], list[str]]:
    """Return (urls, skipped_names) for the chosen browser ('firefox'|'chromium')."""
    extensions = data.browser_extensions()
    urls: list[str] = []
    skipped: list[str] = []
    for ext_id in selected_ids:
        info = extensions.get(ext_id)
        if not info:
            continue
        if browser == "firefox" and info.get("firefox_slug"):
            urls.append(f"https://addons.mozilla.org/firefox/addon/{info['firefox_slug']}/")
        elif browser == "chromium" and info.get("chromium_id"):
            urls.append(f"https://chromewebstore.google.com/detail/{info['chromium_id']}")
        else:
            skipped.append(info.get("name", ext_id))
    return urls, skipped
