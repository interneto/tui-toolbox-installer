"""Copy the toolbox package data from the website's public/pkgs into the bundled
package data, so the TUI ships the same packages as the web toolbox.

This project lives alongside the website repo. By default it looks for a sibling
``interneto-website/public/pkgs``; pass an explicit source dir to override:

    python scripts/sync_pkgs.py
    python scripts/sync_pkgs.py /path/to/interneto-website/public/pkgs
"""

from __future__ import annotations

import sys
from pathlib import Path
from shutil import copy2

FILES = [
    "config.json",
    "desktop-pkgs.json",
    "mobile-pkgs.json",
    "browser-extensions-pkgs.json",
    "vscode-extensions-pkgs.json",
    "lib-pkgs.json",
]


def default_source() -> Path:
    project_root = Path(__file__).resolve().parents[1]
    return project_root.parent / "interneto-website" / "public" / "pkgs"


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else default_source()
    if not src.is_dir():
        raise SystemExit(
            f"Source pkgs dir not found: {src}\n"
            "Pass the path to the website's public/pkgs as an argument."
        )
    dest = Path(__file__).resolve().parents[1] / "interneto_install" / "data"
    dest.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        copy2(src / name, dest / name)
        print(f"synced {name}")
    print(f"\nSynced {len(FILES)} files from {src}")


if __name__ == "__main__":
    main()
