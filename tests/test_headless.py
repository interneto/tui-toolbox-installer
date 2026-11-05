"""Tests for the non-interactive mode.

Nothing here runs a real package manager: execution tests swap in Python
one-liners, and ``--only-missing`` inventories are monkeypatched. The surface
planners are the real ones.
"""

from __future__ import annotations

import argparse
import json
import sys

import pytest

from interneto_install import commands, data, detect, headless
from interneto_install.__main__ import main

APT = detect.SystemInfo(
    os_name="linux",
    os_label="Debian test",
    pm_key="linux_debian_apt",
    pm_fallbacks=["linux_flatpak"],
)


def _ns(**overrides) -> argparse.Namespace:
    defaults = dict(
        favorites=None,
        yes=False,
        dry_run=False,
        only_missing=False,
        surface=None,
        browser="firefox",
        lib_lang="javascript",
        fail_fast=False,
        json=False,
        log=None,
        state=None,
        resume=False,
        android_serial=None,
        detect=False,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _profile(tmp_path, monkeypatch, payload: dict) -> None:
    path = tmp_path / "favorites.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("INTERNETO_FAVORITES", str(path))


def _json(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def test_dry_run_json_does_not_execute(tmp_path, monkeypatch, capsys):
    _profile(tmp_path, monkeypatch, {"desktop": ["firefox", "vlc"]})
    monkeypatch.setattr(headless.detect, "detect_system", lambda: APT)

    def explode(*args, **kwargs):
        raise AssertionError("dry-run must not execute anything")

    monkeypatch.setattr(headless.runner, "run_commands", explode)

    code = headless.run_headless(_ns(dry_run=True, json=True, surface=["desktop"]))
    payload = _json(capsys)

    assert code == headless.EXIT_OK
    assert payload["dry_run"] is True
    assert payload["executed"] is False
    surface = payload["surfaces"][0]
    assert surface["surface"] == "desktop"
    assert surface["commands"]
    assert "firefox" in " ".join(surface["commands"][0])


def test_refuses_to_run_without_yes(tmp_path, monkeypatch, capsys):
    _profile(tmp_path, monkeypatch, {"desktop": ["firefox"]})
    monkeypatch.setattr(headless.detect, "detect_system", lambda: APT)

    code = headless.run_headless(_ns(json=True, surface=["desktop"]))
    payload = _json(capsys)

    assert code == headless.EXIT_USAGE
    assert payload["executed"] is False
    assert payload["needs_yes"] is True


def test_only_missing_filters_installed_packages(tmp_path, monkeypatch, capsys):
    _profile(tmp_path, monkeypatch, {"desktop": ["firefox", "vlc"]})
    monkeypatch.setattr(headless.detect, "detect_system", lambda: APT)
    monkeypatch.setattr(
        headless,
        "_desktop_inventory",
        lambda key: {"firefox"} if key == "linux_debian_apt" else set(),
    )

    code = headless.run_headless(
        _ns(only_missing=True, dry_run=True, json=True, surface=["desktop"])
    )
    payload = _json(capsys)
    surface = payload["surfaces"][0]

    assert code == headless.EXIT_OK
    assert surface["already_installed"] == ["firefox"]
    flat = " ".join(surface["commands"][0])
    assert "vlc" in flat
    assert "firefox" not in flat.split()


def test_mobile_multiple_devices_requires_serial(tmp_path, monkeypatch, capsys):
    _profile(tmp_path, monkeypatch, {"mobile": ["bitwarden"]})
    monkeypatch.setattr(headless.detect, "detect_system", lambda: APT)
    monkeypatch.setattr(headless.detect, "adb_devices", lambda: ["A", "B"])
    monkeypatch.setattr(
        headless.detect,
        "adb_device_entries",
        lambda: [detect.AdbDevice("A"), detect.AdbDevice("B")],
    )

    code = headless.run_headless(_ns(dry_run=True, json=True, surface=["mobile"]))
    captured = capsys.readouterr()

    assert code == headless.EXIT_USAGE
    assert "multiple Android devices" in captured.err


def test_mobile_uses_the_selected_serial(tmp_path, monkeypatch, capsys):
    _profile(tmp_path, monkeypatch, {"mobile": ["bitwarden"]})
    monkeypatch.setattr(headless.detect, "detect_system", lambda: APT)
    monkeypatch.setattr(headless.detect, "adb_devices", lambda: ["A", "B"])
    monkeypatch.setattr(
        headless.detect,
        "adb_device_entries",
        lambda: [detect.AdbDevice("A"), detect.AdbDevice("B")],
    )

    code = headless.run_headless(
        _ns(dry_run=True, json=True, surface=["mobile"], android_serial="B")
    )
    payload = _json(capsys)
    surface = payload["surfaces"][0]

    assert code == headless.EXIT_OK
    assert surface["commands"]
    assert surface["commands"][0][:4] == ["adb", "-s", "B", "shell"]


def test_mobile_serial_not_connected_is_an_error(tmp_path, monkeypatch, capsys):
    _profile(tmp_path, monkeypatch, {"mobile": ["bitwarden"]})
    monkeypatch.setattr(headless.detect, "detect_system", lambda: APT)
    monkeypatch.setattr(headless.detect, "adb_devices", lambda: ["A"])
    monkeypatch.setattr(
        headless.detect, "adb_device_entries", lambda: [detect.AdbDevice("A")]
    )

    code = headless.run_headless(
        _ns(dry_run=True, json=True, surface=["mobile"], android_serial="Z")
    )
    captured = capsys.readouterr()

    assert code == headless.EXIT_USAGE
    assert "not connected" in captured.err


def test_only_missing_uses_the_manager_that_will_install(tmp_path, monkeypatch, capsys):
    packages = data.desktop_packages()
    flatpak_pkg = next(
        pid
        for pid, info in packages.items()
        if info["package_manager"].get("linux_flatpak")
        and not info["package_manager"].get("linux_debian_apt")
    )
    apt_pkg = next(
        pid
        for pid, info in packages.items()
        if info["package_manager"].get("linux_debian_apt")
    )
    _profile(tmp_path, monkeypatch, {"desktop": [apt_pkg, flatpak_pkg]})
    monkeypatch.setattr(headless.detect, "detect_system", lambda: APT)

    apt_value = packages[apt_pkg]["package_manager"]["linux_debian_apt"]
    flatpak_value = packages[flatpak_pkg]["package_manager"]["linux_flatpak"]

    def inventory(key: str):
        if key == "linux_debian_apt":
            return {apt_value}
        if key == "linux_flatpak":
            return {flatpak_value}
        return None

    monkeypatch.setattr(headless, "_desktop_inventory", inventory)

    code = headless.run_headless(
        _ns(only_missing=True, dry_run=True, json=True, surface=["desktop"])
    )
    payload = _json(capsys)
    surface = payload["surfaces"][0]

    assert code == headless.EXIT_OK
    assert set(surface["already_installed"]) == {apt_pkg, flatpak_pkg}
    assert surface["commands"] == []


def test_log_contains_plan(tmp_path, monkeypatch):
    _profile(tmp_path, monkeypatch, {"desktop": ["firefox"]})
    monkeypatch.setattr(headless.detect, "detect_system", lambda: APT)
    log = tmp_path / "rebuild.log"

    code = headless.run_headless(
        _ns(dry_run=True, surface=["desktop"], log=str(log))
    )
    text = log.read_text(encoding="utf-8")

    assert code == headless.EXIT_OK
    assert "# interneto-install" in text
    assert "== desktop ==" in text
    assert "$ " in text
    assert "dry run" in text


def _fake_plan(fail_first: bool = False) -> commands.CommandPlan:
    ok = [sys.executable, "-c", "print('first ok')"]
    failing = [sys.executable, "-c", "import sys; sys.exit(3)"]
    return commands.CommandPlan(
        commands=[failing, ok] if fail_first else [ok, failing]
    )


def test_execution_continues_and_reports_failure(tmp_path, monkeypatch, capsys):
    _profile(tmp_path, monkeypatch, {"desktop": ["firefox", "vlc"]})
    monkeypatch.setattr(headless.detect, "detect_system", lambda: APT)
    monkeypatch.setattr(headless.commands, "build_desktop", lambda pm, ids: _fake_plan())

    code = headless.run_headless(_ns(yes=True, json=True, surface=["desktop"]))
    payload = _json(capsys)
    surface = payload["surfaces"][0]

    assert code == headless.EXIT_FAILED
    assert [item["returncode"] for item in surface["results"]] == [0, 3]
    assert payload["summary"]["failed"] == 1
    assert "first ok" in "\n".join(surface["output"])


def test_fail_fast_stops_after_first_failure(tmp_path, monkeypatch, capsys):
    _profile(tmp_path, monkeypatch, {"desktop": ["firefox", "vlc"]})
    monkeypatch.setattr(headless.detect, "detect_system", lambda: APT)
    monkeypatch.setattr(
        headless.commands, "build_desktop", lambda pm, ids: _fake_plan(fail_first=True)
    )

    code = headless.run_headless(
        _ns(yes=True, json=True, surface=["desktop"], fail_fast=True)
    )
    payload = _json(capsys)
    surface = payload["surfaces"][0]

    assert code == headless.EXIT_FAILED
    assert len(surface["results"]) == 1
    assert surface["results"][0]["returncode"] == 3


def test_state_is_written_and_resume_skips_completed(tmp_path, monkeypatch, capsys):
    _profile(tmp_path, monkeypatch, {"desktop": ["firefox"]})
    monkeypatch.setattr(headless.detect, "detect_system", lambda: APT)
    monkeypatch.setattr(headless.commands, "build_desktop", lambda pm, ids: _fake_plan())
    state = tmp_path / "state.json"

    code = headless.run_headless(
        _ns(yes=True, json=True, surface=["desktop"], state=str(state))
    )
    _json(capsys)

    assert code == headless.EXIT_FAILED
    saved = json.loads(state.read_text(encoding="utf-8"))
    completed = saved["surfaces"]["desktop"]["commands"]
    assert len(completed) == 1, "only the successful command is recorded"

    code = headless.run_headless(
        _ns(yes=True, json=True, surface=["desktop"], state=str(state), resume=True)
    )
    payload = _json(capsys)
    surface = payload["surfaces"][0]

    assert code == headless.EXIT_FAILED
    assert surface["resumed"] == 1
    assert [item["returncode"] for item in surface["results"]] == [3]
    assert payload["resuming"] is True


def test_resume_without_state_starts_fresh(tmp_path, monkeypatch, capsys):
    _profile(tmp_path, monkeypatch, {"desktop": ["firefox"]})
    monkeypatch.setattr(headless.detect, "detect_system", lambda: APT)

    code = headless.run_headless(
        _ns(
            dry_run=True,
            json=True,
            surface=["desktop"],
            resume=True,
            state=str(tmp_path / "missing.json"),
        )
    )
    payload = _json(capsys)

    assert code == headless.EXIT_OK
    assert payload["resuming"] is True
    assert payload["summary"]["resumed"] == 0


def test_resume_with_invalid_state_exits_2(tmp_path, monkeypatch, capsys):
    _profile(tmp_path, monkeypatch, {"desktop": ["firefox"]})
    state = tmp_path / "state.json"
    state.write_text("{not json", encoding="utf-8")

    code = headless.run_headless(
        _ns(
            dry_run=True,
            json=True,
            surface=["desktop"],
            resume=True,
            state=str(state),
        )
    )
    captured = capsys.readouterr()

    assert code == headless.EXIT_USAGE
    assert "could not read resume state" in captured.err
    assert captured.out == ""


def test_dry_run_does_not_touch_state(tmp_path, monkeypatch):
    _profile(tmp_path, monkeypatch, {"desktop": ["firefox"]})
    monkeypatch.setattr(headless.detect, "detect_system", lambda: APT)
    state = tmp_path / "state.json"
    original = '{"version": 1, "surfaces": {}}\n'
    state.write_text(original, encoding="utf-8")

    code = headless.run_headless(
        _ns(dry_run=True, surface=["desktop"], state=str(state))
    )

    assert code == headless.EXIT_OK
    assert state.read_text(encoding="utf-8") == original


def test_missing_explicit_favorites_is_a_usage_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("INTERNETO_FAVORITES", str(tmp_path / "typo.json"))

    code = headless.run_headless(_ns(dry_run=True, json=True, surface=["desktop"]))
    captured = capsys.readouterr()

    assert code == headless.EXIT_USAGE
    assert "not found" in captured.err
    assert captured.out == ""


def test_unknown_lib_language_is_rejected(tmp_path, monkeypatch, capsys):
    _profile(tmp_path, monkeypatch, {"lib": ["react"]})

    code = headless.run_headless(
        _ns(dry_run=True, json=True, surface=["lib"], lib_lang="nope")
    )

    assert code == headless.EXIT_USAGE
    assert "unknown language" in capsys.readouterr().err


def test_main_routes_to_headless_with_yes(monkeypatch):
    calls = []
    monkeypatch.setattr(
        headless, "run_headless", lambda args: calls.append(args) or 0
    )
    monkeypatch.setattr(sys, "argv", ["interneto-install", "--yes", "--dry-run"])

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 0
    assert calls and calls[0].yes is True


def test_desktop_inventory_parsers(monkeypatch):
    monkeypatch.setattr(
        headless, "_capture", lambda argv, timeout=90: "firefox\nvlc\n"
    )
    assert headless._desktop_inventory("linux_debian_apt") == {"firefox", "vlc"}
    assert headless._desktop_inventory("linux_arch_pacman") == {"firefox", "vlc"}

    monkeypatch.setattr(
        headless, "_capture", lambda argv, timeout=90: "Name Version\nfirefox 1\nvlc 2\n"
    )
    assert headless._desktop_inventory("linux_snap") == {"firefox", "vlc"}
