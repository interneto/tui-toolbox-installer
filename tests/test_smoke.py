"""Smoke tests for the Interneto · Toolbox Installer.

These are deliberately lightweight: they exercise the data layer, command
builders, favorites round-trip and a headless run of the Textual app. The app
tests drive the real UI via Textual's test pilot, wrapped in ``asyncio.run`` so
no pytest-asyncio plugin is required.
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import sys
import threading

from interneto_install import commands, data, detect, favorites, icons, runner
from interneto_install.__main__ import _version
from interneto_install.app import (
    InternetoInstallApp,
    PackagePicker,
    RunScreen,
    desktop_items,
)
from textual.widgets import Collapsible, TabbedContent


# --------------------------------------------------------------------------- #
# Metadata / detection
# --------------------------------------------------------------------------- #
def test_version_is_a_string():
    assert isinstance(_version(), str) and _version()


def test_detect_returns_system_info():
    info = detect.detect_system()
    assert info.os_name in {"windows", "macos", "linux", "freebsd", "other"}
    assert isinstance(info.pm_label, str)


def _fake_which(*present: str):
    def which(name: str):
        return f"/usr/bin/{name}" if name in present else None

    return which


def test_linux_detection_prefers_the_distro_manager(monkeypatch):
    monkeypatch.setattr(detect.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        detect,
        "_os_release",
        lambda: {"ID": "ubuntu", "ID_LIKE": "debian", "PRETTY_NAME": "Ubuntu Test"},
    )
    monkeypatch.setattr(detect.shutil, "which", _fake_which("apt", "flatpak", "snap"))
    monkeypatch.setattr(detect, "_ostree_booted", lambda: False)

    info = detect.detect_system()

    assert info.pm_key == "linux_debian_apt"
    assert info.distro_id == "ubuntu"
    assert info.pm_fallbacks[:2] == ["linux_flatpak", "linux_snap"]


def test_linux_detection_openSUSE(monkeypatch):
    monkeypatch.setattr(detect.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        detect,
        "_os_release",
        lambda: {
            "ID": "opensuse-tumbleweed",
            "ID_LIKE": "suse",
            "PRETTY_NAME": "openSUSE Tumbleweed",
        },
    )
    monkeypatch.setattr(detect.shutil, "which", _fake_which("zypper", "flatpak"))
    monkeypatch.setattr(detect, "_ostree_booted", lambda: False)

    info = detect.detect_system()

    assert info.pm_key == "linux_opensuse_zypper"
    assert "linux_flatpak" in info.pm_fallbacks


def test_linux_detection_atomic_fedora_prefers_flatpak(monkeypatch):
    monkeypatch.setattr(detect.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        detect,
        "_os_release",
        lambda: {"ID": "fedora", "ID_LIKE": "fedora", "PRETTY_NAME": "Fedora Atomic"},
    )
    monkeypatch.setattr(
        detect.shutil, "which", _fake_which("dnf", "rpm-ostree", "flatpak")
    )
    monkeypatch.setattr(detect, "_ostree_booted", lambda: True)

    info = detect.detect_system()

    assert info.pm_key == "linux_flatpak"
    assert "linux_fedora_rpm" not in [info.pm_key, *info.pm_fallbacks]
    assert "linux_fedora_rpm_ostree" in info.pm_fallbacks


def test_linux_detection_moves_nix_last_outside_nixos(monkeypatch):
    monkeypatch.setattr(detect.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        detect,
        "_os_release",
        lambda: {"ID": "debian", "ID_LIKE": "debian", "PRETTY_NAME": "Debian"},
    )
    monkeypatch.setattr(
        detect.shutil, "which", _fake_which("apt", "nix-env", "flatpak")
    )
    monkeypatch.setattr(detect, "_ostree_booted", lambda: False)

    info = detect.detect_system()

    assert info.pm_key == "linux_debian_apt"
    assert info.pm_fallbacks[-1] == "unix_nix_env"


def test_parse_adb_devices():
    output = (
        "List of devices attached\n"
        "R58M123 device product:beyond1q model:SM_G973F device:beyond1q transport_id:1\n"
        "emulator-5554 offline\n"
    )

    devices = detect._parse_adb_devices(output)

    assert [device.serial for device in devices] == ["R58M123"]
    assert devices[0].model == "SM G973F"
    assert "SM G973F" in devices[0].label


# --------------------------------------------------------------------------- #
# Data layer
# --------------------------------------------------------------------------- #
def test_all_package_data_loads():
    assert data.desktop_packages()
    assert data.vscode_extensions()
    assert data.browser_extensions()
    assert data.mobile_packages()
    assert data.lib_languages()
    assert data.agents()


def test_icons_and_favorites_bundled():
    table = data.icons()
    assert "default" in table and "categories" in table
    favs = data.bundled_favorites()
    assert set(favs) >= {"desktop", "vscode", "lib", "browser", "mobile"}


def test_icon_for_unknown_category_uses_default():
    assert icons.icon_for_category("No Such Category") == data.icons()["default"]


# --------------------------------------------------------------------------- #
# Command builders
# --------------------------------------------------------------------------- #
def test_build_desktop_winget_one_per_package():
    pkg = next(
        pid
        for pid, info in data.desktop_packages().items()
        if info.get("package_manager", {}).get("windows_winget")
    )
    plan = commands.build_desktop("windows_winget", [pkg])
    assert plan.has_commands
    assert all(cmd[:2] == ["winget", "install"] for cmd in plan.commands)


def test_build_desktop_winget_is_non_interactive():
    pkg = next(
        pid
        for pid, info in data.desktop_packages().items()
        if info.get("package_manager", {}).get("windows_winget")
    )
    cmd = commands.build_desktop("windows_winget", [pkg]).commands[0]
    for flag in (
        "--accept-package-agreements",
        "--accept-source-agreements",
        "--disable-interactivity",
        "--silent",
    ):
        assert flag in cmd


def _flatpak_only_package() -> str:
    return next(
        pid
        for pid, info in data.desktop_packages().items()
        if info["package_manager"].get("linux_flatpak")
        and not info["package_manager"].get("linux_debian_apt")
    )


def test_build_desktop_uses_fallback_manager():
    pkg = _flatpak_only_package()
    plan = commands.build_desktop(["linux_debian_apt", "linux_flatpak"], [pkg])

    assert plan.has_commands
    assert plan.commands[0][:2] == ["flatpak", "install"]


def test_build_desktop_groups_native_and_fallback():
    flatpak_pkg = _flatpak_only_package()
    apt_pkg = next(
        pid
        for pid, info in data.desktop_packages().items()
        if info["package_manager"].get("linux_debian_apt")
    )
    plan = commands.build_desktop(
        ["linux_debian_apt", "linux_flatpak"], [flatpak_pkg, apt_pkg]
    )

    assert len(plan.commands) == 2
    assert plan.commands[0][0] == "sudo" and "apt-get" in plan.commands[0]
    assert plan.commands[1][0] == "flatpak"
    assert plan.non_installable == []
    assert "Installs via" in (plan.note or "")


def test_desktop_items_include_fallback_only_packages():
    flatpak_pkg = _flatpak_only_package()
    primary = {item.value for item in desktop_items(["linux_debian_apt"])}
    both = {
        item.value
        for item in desktop_items(["linux_debian_apt", "linux_flatpak"])
    }

    assert flatpak_pkg not in primary
    assert flatpak_pkg in both
    assert both > primary


def test_brew_cask_data_matches_the_catalog():
    casks = data.brew_casks()
    assert "firefox" in casks
    assert "git" not in casks


def test_build_desktop_macos_splits_formulae_and_casks():
    plan = commands.build_desktop("macos_brew", ["firefox", "git"])

    assert ["brew", "install", "git"] in plan.commands
    assert ["brew", "install", "--cask", "firefox"] in plan.commands
    assert len(plan.commands) == 2


def test_build_desktop_notes_external_apt_repos():
    plan = commands.build_desktop("linux_debian_apt", ["visual-studio-code"])

    assert "Microsoft apt repository" in (plan.note or "")


def test_linux_and_bsd_prefixes_do_not_stop_for_confirmation():
    expected = {
        "linux_debian_apt": "-y",
        "linux_fedora_rpm": "-y",
        "freebsd_pkg": "-y",
        "linux_arch_pacman": "--noconfirm",
        "linux_gentoo_emerge": "--ask=n",
        "linux_flatpak": "--noninteractive",
    }
    prefixes = data.distro_prefixes()
    for key, flag in expected.items():
        assert flag in shlex.split(prefixes[key]), f"{key} would prompt interactively"


def test_build_agents_splits_multi_step_command():
    # code-simplifier's claude install is "marketplace add X && plugin install Y"
    plan = commands.build_agents("claude", ["code-simplifier"])
    assert len(plan.commands) == 2
    assert plan.commands[0][:3] == ["claude", "plugin", "marketplace"]
    assert plan.commands[1][:3] == ["claude", "plugin", "install"]


def test_build_agents_skips_interactive_only_slash_command():
    # design's claude install is a `/plugin ...` Claude Code REPL command, not
    # runnable as a subprocess; its npx install is a real shell command.
    claude_plan = commands.build_agents("claude", ["design"])
    assert not claude_plan.has_commands
    assert "Design" in claude_plan.note

    npx_plan = commands.build_agents("npx", ["design"])
    assert npx_plan.has_commands


def test_build_agents_substitutes_or_skips_env_var(monkeypatch):
    monkeypatch.delenv("AFFINITY_MCP_URL", raising=False)
    skipped = commands.build_agents("claude", ["affinity"])
    assert not skipped.has_commands
    assert "AFFINITY_MCP_URL" in skipped.note

    monkeypatch.setenv("AFFINITY_MCP_URL", "https://example.com/mcp")
    filled = commands.build_agents("claude", ["affinity"])
    assert filled.has_commands
    assert "https://example.com/mcp" in shlex.join(filled.commands[0])


def test_build_agents_lists_every_missing_env_var(monkeypatch):
    # grafana's claude install needs two env vars - both should be named, not just one.
    monkeypatch.delenv("GRAFANA_URL", raising=False)
    monkeypatch.delenv("GRAFANA_SERVICE_ACCOUNT_TOKEN", raising=False)
    plan = commands.build_agents("claude", ["grafana"])
    assert not plan.has_commands
    assert "GRAFANA_URL" in plan.note
    assert "GRAFANA_SERVICE_ACCOUNT_TOKEN" in plan.note


def test_build_agents_does_not_run_another_clis_command():
    # daw-mcp has Claude and Copilot installs only. Asking for Codex must skip
    # it, not execute Claude's command (which the old fallback did).
    plan = commands.build_agents("codex", ["daw-mcp"])
    assert not plan.has_commands
    assert "DAW MCP" in plan.non_installable


def test_build_agents_keeps_windows_paths_intact(monkeypatch):
    monkeypatch.setattr(commands, "_WINDOWS", True)
    monkeypatch.setenv("USERPROFILE", r"C:\Users\tester")
    plan = commands.build_agents("claude", ["daw-mcp"])
    assert plan.has_commands
    assert plan.commands[0][-1] == (
        r"C:\Users\tester\.local\daw-mcp\mcp-server\dist\mcp-server.js"
    )


def test_build_agents_skips_windows_only_command_elsewhere(monkeypatch):
    monkeypatch.setattr(commands, "_WINDOWS", False)
    plan = commands.build_agents("claude", ["daw-mcp"])
    assert not plan.has_commands
    assert "Windows-only" in plan.note


def test_build_agents_skips_commands_that_need_a_shell():
    # codebase-memory-mcp pipes a PowerShell download into iex; the runner
    # executes argv, not a shell, so this must be reported as manual.
    plan = commands.build_agents("claude", ["codebase-memory-mcp"])
    assert not plan.has_commands
    assert "run manually" in plan.note


def test_build_agents_redacts_secret_values_in_preview(monkeypatch):
    monkeypatch.setenv("GRAFANA_URL", "https://example.com/mcp")
    monkeypatch.setenv("GRAFANA_SERVICE_ACCOUNT_TOKEN", "super-secret-token")
    plan = commands.build_agents("claude", ["grafana"])
    assert plan.has_commands
    assert "super-secret-token" in shlex.join(plan.commands[0])
    assert "super-secret-token" not in plan.preview()
    assert "***" in plan.preview()


def test_browser_downloads_xpi_and_crx():
    ff, _ = commands.browser_downloads(["bitwarden"], "firefox")
    assert ff and ff[0].filename.endswith(".xpi")
    assert "addons.mozilla.org" in ff[0].url
    ch, _ = commands.browser_downloads(["bitwarden"], "chromium")
    assert ch and ch[0].filename.endswith(".crx")
    assert "clients2.google.com" in ch[0].url


# --------------------------------------------------------------------------- #
# Favorites round-trip
# --------------------------------------------------------------------------- #
def test_favorites_save_and_load(tmp_path, monkeypatch):
    target = tmp_path / "favorites.json"
    monkeypatch.setattr(favorites, "user_path", lambda: target)
    payload = {"desktop": ["firefox", "vlc"], "vscode": []}
    saved = favorites.save(payload)
    assert saved == target and target.is_file()
    assert json.loads(target.read_text(encoding="utf-8"))["desktop"] == ["firefox", "vlc"]
    assert favorites.load()["desktop"] == ["firefox", "vlc"]


def test_favorites_fall_back_to_bundled(tmp_path, monkeypatch):
    monkeypatch.setattr(favorites, "user_path", lambda: tmp_path / "missing.json")
    loaded = favorites.load()
    assert loaded["desktop"] == list(data.bundled_favorites()["desktop"])


def test_favorites_merge_one_surface_over_bundled(tmp_path, monkeypatch):
    target = tmp_path / "favorites.json"
    target.write_text(json.dumps({"desktop": ["firefox"]}), encoding="utf-8")
    monkeypatch.setattr(favorites, "user_path", lambda: target)
    loaded = favorites.load()
    assert loaded["desktop"] == ["firefox"]
    # Surfaces the file doesn't mention keep the bundled defaults instead of
    # becoming empty.
    assert loaded["vscode"] == list(data.bundled_favorites()["vscode"])


def test_favorites_invalid_json_reports_error(tmp_path, monkeypatch):
    target = tmp_path / "favorites.json"
    target.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(favorites, "user_path", lambda: target)
    loaded = favorites.load()
    assert loaded["desktop"] == list(data.bundled_favorites()["desktop"])
    assert favorites.last_error and "Could not read" in favorites.last_error


def test_favorites_user_path_env_override(tmp_path, monkeypatch):
    target = tmp_path / "perfil.json"
    monkeypatch.setenv("INTERNETO_FAVORITES", str(target))
    assert favorites.user_path() == target


def test_favorites_missing_override_reports_error(tmp_path, monkeypatch):
    monkeypatch.setenv("INTERNETO_FAVORITES", str(tmp_path / "typo.json"))
    loaded = favorites.load()
    assert loaded["desktop"] == list(data.bundled_favorites()["desktop"])
    assert favorites.last_error and "not found" in favorites.last_error


def test_favorites_save_leaves_no_temp_files(tmp_path, monkeypatch):
    target = tmp_path / "favorites.json"
    monkeypatch.setattr(favorites, "user_path", lambda: target)
    favorites.save({"desktop": ["firefox"]})
    assert target.is_file()
    assert not list(tmp_path.glob("*.tmp"))


# --------------------------------------------------------------------------- #
# Runner: no invisible prompts, no leaked secrets
# --------------------------------------------------------------------------- #
def test_run_commands_closes_stdin():
    lines = list(
        runner.run_commands(
            [[sys.executable, "-c", "import sys; print(sys.stdin.isatty())"]]
        )
    )
    assert "False" in lines


def test_run_commands_redacts_secret_output():
    lines = list(
        runner.run_commands(
            [[sys.executable, "-c", "print('super-secret-token')"]],
            secrets=["super-secret-token"],
        )
    )
    assert not any("super-secret-token" in line for line in lines)
    assert any("***" in line for line in lines)


def test_run_commands_can_be_cancelled():
    control = runner.RunControl()
    timer = threading.Timer(0.3, control.request_stop)
    timer.start()
    try:
        lines = list(
            runner.run_commands(
                [[sys.executable, "-c", "import time; time.sleep(30)"]],
                control=control,
            )
        )
    finally:
        timer.cancel()

    assert control.cancelled
    assert any("Cancelled" in line for line in lines)


def test_run_commands_stops_before_start_when_cancelled():
    control = runner.RunControl()
    control.request_stop()

    lines = list(
        runner.run_commands(
            [[sys.executable, "-c", "print('must not run')"]], control=control
        )
    )

    assert lines == ["✗ Cancelled."]


def test_run_commands_calls_on_result():
    seen: list[runner.CommandResult] = []
    list(
        runner.run_commands(
            [[sys.executable, "-c", "print('ok')"]], on_result=seen.append
        )
    )

    assert len(seen) == 1
    assert seen[0].returncode == 0


def test_run_screen_stop_requests_cancellation():
    control = runner.RunControl()
    screen = RunScreen([], control=control)
    screen._stop_pressed()

    assert control.cancelled


def test_refresh_path_adds_known_dir_once(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    runner.refresh_path(extra_dirs=[tmp_path])
    entries = os.environ["PATH"].split(os.pathsep)
    assert str(tmp_path) in entries

    runner.refresh_path(extra_dirs=[tmp_path])
    entries = os.environ["PATH"].split(os.pathsep)
    assert entries.count(str(tmp_path)) == 1


# --------------------------------------------------------------------------- #
# Picker (pure logic, no app)
# --------------------------------------------------------------------------- #
def test_desktop_items_sorted_and_nonempty():
    items = desktop_items("windows_winget")
    assert items
    assert items == sorted(items, key=lambda i: (i.category, i.label.lower()))


# --------------------------------------------------------------------------- #
# Headless app smoke tests
# --------------------------------------------------------------------------- #
def _run(coro):
    return asyncio.run(coro)


def test_app_mounts_with_collapsible_grid():
    async def scenario():
        app = InternetoInstallApp()
        async with app.run_test(size=(130, 40)):
            picker = app._active_picker()
            sections = list(picker.query(Collapsible))
            assert sections, "expected category sections"
            assert all(not c.collapsed for c in sections), "sections open by default"
            cols = picker.query_one(".picker-groups").styles.grid_size_columns
            assert 1 <= cols <= 5

    _run(scenario())


def test_app_favorites_apply_selects_packages():
    async def scenario():
        app = InternetoInstallApp()
        async with app.run_test(size=(130, 40)) as pilot:
            assert app._active_surface() == "desktop"
            app.action_favorites()
            await pilot.pause()
            selected = app._active_picker().selected_ids()
            assert selected, "favorites should select something"

    _run(scenario())


def test_app_search_filters_sections():
    async def scenario():
        app = InternetoInstallApp()
        async with app.run_test(size=(130, 40)) as pilot:
            picker = app._active_picker()
            picker.query_one("Input").focus()
            await pilot.press("g", "i", "t")
            await pilot.pause()
            sections = list(picker.query(Collapsible))
            assert 0 < len(sections) < 14, "search should narrow the sections"

    _run(scenario())


def test_app_agents_tab_lists_packages_and_has_no_favorites():
    async def scenario():
        app = InternetoInstallApp()
        async with app.run_test(size=(130, 40)) as pilot:
            app.query_one(TabbedContent).active = "tab-agents"
            await pilot.pause()
            picker = app._active_picker()
            assert picker is not None and picker.selected_ids() == []
            assert app._active_surface() is None  # agents has no favorites, like the web toolbox

    _run(scenario())


def test_app_responsive_columns_shrink():
    async def scenario():
        app = InternetoInstallApp()
        async with app.run_test(size=(130, 40)) as pilot:
            picker = app._active_picker()
            groups = picker.query_one(".picker-groups")
            wide = groups.styles.grid_size_columns
            await pilot.resize_terminal(60, 30)
            await pilot.pause()
            narrow = groups.styles.grid_size_columns
            assert narrow < wide, "fewer columns on a narrow terminal"

    _run(scenario())
