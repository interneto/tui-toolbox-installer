"""User-customizable 'favorites' selections, per installer surface.

A favorites set maps a surface key to a list of package ids::

    {"desktop": ["firefox", ...], "vscode": [...], "lib": [...],
     "browser": [...], "mobile": [...]}

Defaults ship in ``data/favorites.json``. A user can override them by exporting
their own selection to a JSON file under the platform config dir; when that file
exists it takes precedence over the bundled defaults.
"""

from __future__ import annotations

import json
from pathlib import Path

import platformdirs

from . import data

SURFACES = ("desktop", "vscode", "lib", "browser", "mobile")


def user_path() -> Path:
    """Location of the per-user favorites file (may not exist yet)."""
    return Path(platformdirs.user_config_dir("interneto-install")) / "favorites.json"


def load() -> dict[str, list[str]]:
    """Return the user's favorites if present, else the bundled defaults."""
    path = user_path()
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            loaded = None
        if isinstance(loaded, dict):
            return {k: list(v) for k, v in loaded.items() if isinstance(v, list)}
    return {k: list(v) for k, v in data.bundled_favorites().items()}


def save(favorites: dict[str, list[str]]) -> Path:
    """Write the favorites set to the user file and return its path."""
    path = user_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(favorites, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path
