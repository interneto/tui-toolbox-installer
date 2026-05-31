"""Console entry point: ``python -m interneto_install`` / ``interneto-install``."""

from __future__ import annotations

import sys

from . import detect


def main() -> None:
    if "--detect" in sys.argv:
        info = detect.detect_system()
        print(f"OS:              {info.os_label} ({info.os_name})")
        print(f"Package manager: {info.pm_label} [{info.pm_key}]")
        if info.pm_fallbacks:
            print(f"Fallbacks:       {', '.join(info.pm_fallbacks)}")
        print(f"Android devices: {', '.join(detect.adb_devices()) or 'none'}")
        return

    from .app import run

    run()


if __name__ == "__main__":
    main()
