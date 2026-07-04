"""Emoji icons for package rows, keyed by category.

The mapping lives in ``data/icons.json`` (bundled like the rest of the package
data) so it can be edited without touching code. Unknown categories fall back to
a default glyph, so newly added categories always render something sensible.
"""

from __future__ import annotations

from . import data

# Some package data files (desktop, mobile) store categories as slugs
# (e.g. "audio-and-music") instead of display names. These are display-only
# overrides for slugs the generic title-casing gets wrong; the slug itself
# stays the grouping/lookup key everywhere else.
_LABEL_OVERRIDES = {
    "os-and-utilities": "OS & Utilities",
}


def category_label(category: str) -> str:
    """Human-readable English name for a category, slug or not."""
    if category in _LABEL_OVERRIDES:
        return _LABEL_OVERRIDES[category]
    if category.islower():
        return category.replace("-and-", " & ").replace("-", " ").title()
    return category


def icon_for_category(category: str) -> str:
    table = data.icons()
    categories = table.get("categories", {})
    return (
        categories.get(category)
        or categories.get(category_label(category))
        or table.get("default", "📦")
    )
