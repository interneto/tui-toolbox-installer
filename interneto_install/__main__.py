"""Console entry point: ``python -m interneto_install`` / ``interneto-install``."""

from __future__ import annotations

import argparse
from importlib import metadata

from . import detect


def _version() -> str:
    try:
        return metadata.version("interneto-install")
    except metadata.PackageNotFoundError:  # running from a source checkout
        return "0.0.0+dev"


def _print_detection() -> None:
    info = detect.detect_system()
    print(f"OS:              {info.os_label} ({info.os_name})")
    print(f"Package manager: {info.pm_label} [{info.pm_key}]")
    if info.pm_fallbacks:
        print(f"Fallbacks:       {', '.join(info.pm_fallbacks)}")
    print(f"Android devices: {', '.join(detect.adb_devices()) or 'none'}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="interneto-install",
        description="Cross-platform TUI that autodetects your OS and installs "
        "Interneto toolbox packages.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {_version()}"
    )
    parser.add_argument(
        "--detect",
        action="store_true",
        help="print the detected OS, package manager and Android devices, then exit",
    )
    args = parser.parse_args()

    if args.detect:
        _print_detection()
        return

    from .app import run

    run()


if __name__ == "__main__":
    main()
