"""Autodetection of the host operating system and package manager.

Maps the running system to one of the ``package_manager`` keys used in the
toolbox data (e.g. ``windows_winget``, ``macos_brew``, ``linux_debian_apt``,
``freebsd_pkg``). On Linux several managers may be present, so we return the
detected primary plus any fallbacks the user can switch to.
"""

from __future__ import annotations

import platform
import shutil
from dataclasses import dataclass, field

# Ordered: native distro managers first, then universal fallbacks.
_LINUX_MANAGERS: list[tuple[str, str]] = [
    ("pacman", "linux_arch_pacman"),
    ("apt", "linux_debian_apt"),
    ("dnf", "linux_fedora_rpm"),
    ("emerge", "linux_gentoo_emerge"),
    ("nix-env", "unix_nix_env"),
    ("flatpak", "linux_flatpak"),
    ("snap", "linux_snap"),
]

# Human labels for the package-manager keys.
PM_LABELS: dict[str, str] = {
    "linux_arch_pacman": "pacman (Arch)",
    "linux_debian_apt": "apt (Debian/Ubuntu)",
    "linux_fedora_rpm": "dnf (Fedora/RHEL)",
    "linux_gentoo_emerge": "emerge (Gentoo)",
    "unix_nix_env": "nix-env (Nix)",
    "linux_flatpak": "flatpak",
    "linux_snap": "snap",
    "freebsd_pkg": "pkg (FreeBSD)",
    "macos_brew": "Homebrew (macOS)",
    "windows_winget": "winget (Windows)",
    "android_pkg": "adb (Android device)",
}


@dataclass
class SystemInfo:
    os_name: str  # windows | macos | linux | freebsd | other
    os_label: str  # Friendly label for the header.
    pm_key: str | None  # Primary package-manager key, or None if unknown.
    pm_fallbacks: list[str] = field(default_factory=list)  # Alternatives present.

    @property
    def is_desktop(self) -> bool:
        return self.os_name in {"windows", "macos", "linux", "freebsd"}

    @property
    def pm_label(self) -> str:
        if self.pm_key is None:
            return "no package manager detected"
        return PM_LABELS.get(self.pm_key, self.pm_key)


def detect_system() -> SystemInfo:
    system = platform.system()

    if system == "Windows":
        has = shutil.which("winget") is not None
        return SystemInfo(
            os_name="windows",
            os_label=f"Windows ({platform.release()})",
            pm_key="windows_winget" if has else None,
        )

    if system == "Darwin":
        has = shutil.which("brew") is not None
        return SystemInfo(
            os_name="macos",
            os_label=f"macOS {platform.mac_ver()[0]}".strip(),
            pm_key="macos_brew" if has else None,
        )

    if system == "FreeBSD" or system.endswith("BSD"):
        has = shutil.which("pkg") is not None
        return SystemInfo(
            os_name="freebsd",
            os_label=f"{system} {platform.release()}",
            pm_key="freebsd_pkg" if has else None,
        )

    if system == "Linux":
        present = [(binary, key) for binary, key in _LINUX_MANAGERS if shutil.which(binary)]
        primary = present[0][1] if present else None
        fallbacks = [key for _, key in present[1:]]
        return SystemInfo(
            os_name="linux",
            os_label=_linux_distro_label(),
            pm_key=primary,
            pm_fallbacks=fallbacks,
        )

    return SystemInfo(os_name="other", os_label=system or "Unknown", pm_key=None)


def _linux_distro_label() -> str:
    """Best-effort pretty name from /etc/os-release."""
    try:
        with open("/etc/os-release", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return "Linux"


def adb_devices() -> list[str]:
    """Return serials of connected Android devices (empty if adb missing)."""
    if shutil.which("adb") is None:
        return []
    import subprocess

    try:
        out = subprocess.run(
            ["adb", "devices"], capture_output=True, text=True, timeout=10, check=False
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    devices = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])
    return devices
