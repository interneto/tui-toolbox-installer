"""User-customizable 'favorites' selections, per installer surface.

A favorites set maps a surface key to a list of package ids::

    {"desktop": ["firefox", ...], "vscode": [...], "lib": [...],
     "browser": [...], "mobile": [...]}

Defaults ship in ``data/favorites.json``. A user can override them by exporting
their own selection to a JSON file under the platform config dir; when that file
exists it takes precedence over the bundled defaults, *per surface*. Surfaces
the user file does not mention keep their bundled defaults, so hand-editing a
single surface never silently empties the others.

Set ``INTERNETO_FAVORITES`` (or pass ``--favorites PATH``) to use a file
somewhere else, e.g. the curated profile kept in the toolbox repo.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import platformdirs

from . import data

SURFACES = ("desktop", "vscode", "lib", "browser", "mobile")

# Set by load() when a user file exists but could not be used, so the UI can
# explain the fallback instead of silently installing a different set.
last_error: str | None = None


def user_path() -> Path:
    """Location of the per-user favorites file (may not exist yet)."""
    override = os.environ.get("INTERNETO_FAVORITES")
    if override:
        return Path(override).expanduser()
    # platformdirs uses LOCALAPPDATA on Windows (not APPDATA/Roaming).
    return Path(platformdirs.user_config_dir("interneto-install")) / "favorites.json"


def _sanitize(raw: object) -> dict[str, list[str]]:
    """Keep known surfaces whose value is a list of strings."""
    if not isinstance(raw, dict):
        return {}
    cleaned: dict[str, list[str]] = {}
    for surface, ids in raw.items():
        if surface in SURFACES and isinstance(ids, list):
            cleaned[surface] = [item for item in ids if isinstance(item, str)]
    return cleaned


def load() -> dict[str, list[str]]:
    """Return bundled defaults overlaid with the user's file, per surface."""
    global last_error
    last_error = None

    result = _sanitize(data.bundled_favorites())
    path = user_path()
    if not path.is_file():
        if os.environ.get("INTERNETO_FAVORITES"):
            last_error = f"Favorites file not found: {path}"
        return result

    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        last_error = f"Could not read favorites from {path}: {exc}"
        return result

    user = _sanitize(loaded)
    if not user:
        last_error = (
            f"{path} has no usable surface keys; using the bundled favorites. "
            f"Expected one or more of: {', '.join(SURFACES)}."
        )
        return result

    result.update(user)
    return result


def save(favorites: dict[str, list[str]]) -> Path:
    """Write the favorites set atomically and return its path."""
    path = user_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(favorites, indent=2, ensure_ascii=False) + "\n")
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return path
