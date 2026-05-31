"""Smoke tests for the Interneto · Toolbox Installer.

These are deliberately lightweight: they exercise the data layer, command
builders, favorites round-trip and a headless run of the Textual app. The app
tests drive the real UI via Textual's test pilot, wrapped in ``asyncio.run`` so
no pytest-asyncio plugin is required.
"""

from __future__ import annotations

import asyncio
import json

from interneto_install import commands, data, detect, favorites, icons
from interneto_install.__main__ import _version
from interneto_install.app import InternetoInstallApp, PackagePicker, desktop_items
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


# --------------------------------------------------------------------------- #
# Data layer
# --------------------------------------------------------------------------- #
def test_all_package_data_loads():
    assert data.desktop_packages()
    assert data.vscode_extensions()
    assert data.browser_extensions()
    assert data.mobile_packages()
    assert data.lib_languages()


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
