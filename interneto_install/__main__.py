"""Console entry point: ``python -m interneto_install`` / ``interneto-install``."""

from __future__ import annotations

import argparse
import os
from importlib import metadata

from . import detect


def _version() -> str:
    try:
        return metadata.version("interneto-install")
    except metadata.PackageNotFoundError:  # running from a source checkout
        return "0.0.0+dev"


def _print_detection() -> None:
    from . import favorites

    info = detect.detect_system()
    print(f"OS:              {info.os_label} ({info.os_name})")
    print(f"Package manager: {info.pm_label} [{info.pm_key}]")
    if info.pm_fallbacks:
        print(f"Fallbacks:       {', '.join(info.pm_fallbacks)}")
    print(f"Android devices: {', '.join(detect.adb_devices()) or 'none'}")
    path = favorites.user_path()
    state = "found" if path.is_file() else "missing — bundled defaults"
    print(f"Favorites file:  {path} ({state})")
    from .headless import default_state_path

    print(f"Resume state:    {default_state_path()}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="interneto-install",
        description="Cross-platform TUI installer with a headless mode for "
        "clean reinstalls.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Headless examples:\n"
            "  interneto-install --favorites perfil.json --surface desktop --dry-run --json\n"
            "  interneto-install --favorites perfil.json --surface desktop --only-missing --yes --log rebuild.log\n"
            "  interneto-install --favorites perfil.json --surface all --yes\n"
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {_version()}"
    )
    parser.add_argument(
        "--detect",
        action="store_true",
        help="print the detected OS, package manager and Android devices, then exit",
    )
    parser.add_argument(
        "--favorites",
        metavar="PATH",
        help="use this favorites JSON instead of the per-user config file",
    )
    headless_group = parser.add_argument_group("headless mode")
    headless_group.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="execute the plan without asking (required to install)",
    )
    headless_group.add_argument(
        "--dry-run",
        action="store_true",
        help="print the plan (and download URLs) without running anything",
    )
    headless_group.add_argument(
        "--only-missing",
        action="store_true",
        help="skip packages already installed where the manager can report it",
    )
    headless_group.add_argument(
        "--surface",
        action="append",
        choices=("desktop", "vscode", "lib", "browser", "mobile", "all"),
        help="surface to apply (repeatable; default: desktop)",
    )
    headless_group.add_argument(
        "--browser",
        choices=("firefox", "chromium"),
        default="firefox",
        help="browser for the browser surface (default: firefox)",
    )
    headless_group.add_argument(
        "--lib-lang",
        metavar="LANG",
        default="javascript",
        help="language for the lib surface (default: javascript)",
    )
    headless_group.add_argument(
        "--fail-fast",
        action="store_true",
        help="stop at the first failed command instead of continuing",
    )
    headless_group.add_argument(
        "--json",
        action="store_true",
        help="print a machine-readable report on stdout",
    )
    headless_group.add_argument(
        "--log",
        metavar="PATH",
        help="write the full text log to PATH",
    )
    headless_group.add_argument(
        "--state",
        metavar="PATH",
        help="persist completed commands to PATH (for --resume)",
    )
    headless_group.add_argument(
        "--resume",
        action="store_true",
        help="skip commands completed in the --state file (default: last-run.json)",
    )
    headless_group.add_argument(
        "--android-serial",
        metavar="SERIAL",
        help="Android device serial for the mobile surface (needed with several devices)",
    )
    args = parser.parse_args()

    if args.favorites:
        os.environ["INTERNETO_FAVORITES"] = os.path.abspath(
            os.path.expanduser(args.favorites)
        )

    if args.detect:
        _print_detection()
        return

    if any(
        (
            args.yes,
            args.dry_run,
            args.only_missing,
            args.surface,
            args.json,
            args.log,
            args.state,
            args.resume,
            args.android_serial,
        )
    ):
        from .headless import run_headless

        raise SystemExit(run_headless(args))

    from .app import run

    run()


if __name__ == "__main__":
    main()
