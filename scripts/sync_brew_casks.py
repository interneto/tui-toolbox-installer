"""Regenerate ``interneto_install/data/brew-casks.json``.

Homebrew installs GUI apps from casks and CLI tools from formulae, and the
catalog only stores one ``macos_brew`` name per package. This script resolves
which of those names are casks using the public Homebrew API, so the app can
emit ``brew install --cask`` for the right ones.

Run after the desktop catalog changes:

    python scripts/sync_brew_casks.py

It needs network access to https://formulae.brew.sh/api. Names that are in
neither list are printed: those are usually taps (``user/tap/tool``) or
renamed packages and are left as formulae, which will fail visibly instead of
silently installing the wrong thing.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "interneto_install" / "data"
FORMULA_API = "https://formulae.brew.sh/api/formula.json"
CASK_API = "https://formulae.brew.sh/api/cask.json"


def _tokens(url: str, key: str) -> set[str]:
    with urllib.request.urlopen(url, timeout=120) as response:
        return {entry[key] for entry in json.load(response)}


def main() -> None:
    catalog = json.loads(
        (DATA / "desktop-pkgs.json").read_text(encoding="utf-8")
    )["packages"]
    brew_names = {
        info["package_manager"]["macos_brew"]
        for info in catalog.values()
        if info.get("package_manager", {}).get("macos_brew")
    }

    formulae = _tokens(FORMULA_API, "name")
    casks = _tokens(CASK_API, "token")

    cask_names = sorted(name for name in brew_names if name in casks and name not in formulae)
    unknown = sorted(name for name in brew_names if name not in casks and name not in formulae)

    target = DATA / "brew-casks.json"
    target.write_text(
        json.dumps(
            {
                "source": "https://formulae.brew.sh/api",
                "casks": cask_names,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"{len(cask_names)} cask(s) of {len(brew_names)} brew names -> {target}")
    if unknown:
        print("Not in either list (left as formulae):")
        for name in unknown:
            print(f"  {name}")


if __name__ == "__main__":
    main()
