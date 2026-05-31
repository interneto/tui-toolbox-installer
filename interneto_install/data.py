"""Loading of the bundled package data.

The JSON files are the exact same ones the web toolbox ships in
``public/pkgs/``. They are bundled inside the package (``interneto_install/data``)
so the TUI works when installed standalone, and fall back to the repository copy
during local development.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

_DATA_FILES = {
    "config": "config.json",
    "desktop": "desktop-pkgs.json",
    "mobile": "mobile-pkgs.json",
    "browser": "browser-extensions-pkgs.json",
    "vscode": "vscode-extensions-pkgs.json",
    "lib": "lib-pkgs.json",
}


def _repo_pkgs_dir() -> Path | None:
    """Locate ``public/pkgs`` by walking up from this file (dev fallback)."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "public" / "pkgs"
        if candidate.is_dir():
            return candidate
    return None


def _load(name: str) -> Any:
    filename = _DATA_FILES[name]
    # 1. Bundled package data (works when pip-installed).
    try:
        data_pkg = resources.files(__package__) / "data" / filename
        if data_pkg.is_file():
            return json.loads(data_pkg.read_text(encoding="utf-8"))
    except (FileNotFoundError, ModuleNotFoundError):
        pass
    # 2. Repository copy (dev fallback).
    repo = _repo_pkgs_dir()
    if repo is not None:
        path = repo / filename
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    raise FileNotFoundError(
        f"Could not find package data file {filename!r}. "
        "Re-run from the repo or reinstall the package."
    )


@lru_cache(maxsize=None)
def config() -> dict[str, Any]:
    return _load("config")


@lru_cache(maxsize=None)
def distro_prefixes() -> dict[str, str]:
    return config().get("distroPrefixes", {})


@lru_cache(maxsize=None)
def desktop_packages() -> dict[str, Any]:
    return _load("desktop").get("packages", {})


@lru_cache(maxsize=None)
def mobile_packages() -> dict[str, Any]:
    return _load("mobile").get("packages", {})


@lru_cache(maxsize=None)
def browser_extensions() -> dict[str, Any]:
    return _load("browser").get("extensions", {})


@lru_cache(maxsize=None)
def vscode_extensions() -> dict[str, Any]:
    return _load("vscode").get("extensions", {})


@lru_cache(maxsize=None)
def lib_languages() -> dict[str, Any]:
    # Top-level keys are language ids; each holds label/emoji/manager/categories.
    return _load("lib")
