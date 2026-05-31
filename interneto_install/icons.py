"""Emoji icons for package rows, keyed by category.

The mapping lives in ``data/icons.json`` (bundled like the rest of the package
data) so it can be edited without touching code. Unknown categories fall back to
a default glyph, so newly added categories always render something sensible.
"""

from __future__ import annotations

from . import data


def icon_for_category(category: str) -> str:
    table = data.icons()
    return table.get("categories", {}).get(category) or table.get("default", "📦")
