"""Autodetection of the host operating system and package manager.

Maps the running system to one of the ``package_manager`` keys used in the
toolbox data (e.g. ``windows_winget``, ``macos_brew``, ``linux_debian_apt``,
``freebsd_pkg``). On Linux several managers may be present, so we return the
detected primary plus any fallbacks the user can switch to.
"""

from __future__ import annotations

import platform
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Ordered: native distro managers first, then universal fallbacks. The
# distro preference in _distro_preference() reorders these per /etc/os-release.
_LINUX_MANAGERS: list[tuple[str, str]] = [
    ("pacman", "linux_arch_pacman"),
    ("apt", "linux_debian_apt"),
    ("dnf", "linux_fedora_rpm"),
    ("zypper", "linux_opensuse_zypper"),
    ("emerge", "linux_gentoo_emerge"),
    ("apk", "linux_alpine_apk"),
    ("xbps-install", "linux_void_xbps"),
    ("rpm-ostree", "linux_fedora_rpm_ostree"),
    ("nix-env", "unix_nix_env"),
    ("flatpak", "linux_flatpak"),
    ("snap", "linux_snap"),
]

# Human labels for the package-manager keys.
PM_LABELS: dict[str, str] = {
    "linux_arch_pacman": "pacman (Arch)",
    "linux_debian_apt": "apt (Debian/Ubuntu)",
    "linux_fedora_rpm": "dnf (Fedora/RHEL)",
    "linux_opensuse_zypper": "zypper (openSUSE)",
    "linux_gentoo_emerge": "emerge (Gentoo)",
    "linux_alpine_apk": "apk (Alpine)",
    "linux_void_xbps": "xbps (Void)",
    "linux_fedora_rpm_ostree": "rpm-ostree (Fedora Atomic)",
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
    distro_id: str | None = None  # Linux ID from /etc/os-release, if any.

    @property
    def is_desktop(self) -> bool:
        return self.os_name in {"windows", "macos", "linux", "freebsd"}

    @property
    def available_managers(self) -> list[str]:
        """Primary manager first, then the fallbacks found on this host."""
        if self.pm_key is None:
            return list(self.pm_fallbacks)
        return [self.pm_key, *self.pm_fallbacks]

    @property
    def pm_label(self) -> str:
        if self.pm_key is None:
            return "no package manager detected"
        return PM_LABELS.get(self.pm_key, self.pm_key)


def detect_system() -> SystemInfo:
    system = platform.system()

    if system == "Windows":
        has = shutil.which("winget") is not None
        release = platform.release()
        # platform.release() reports "10" on Windows 11 too; use the build
        # number (11 ships as build >= 22000) to disambiguate.
        if release == "10" and sys.getwindowsversion().build >= 22000:
            release = "11"
        return SystemInfo(
            os_name="windows",
            os_label=f"Windows ({release})",
            pm_key="windows_winget" if has else None,
        )

    if system == "Darwin":
        has = shutil.which("brew") is not None
        return SystemInfo(
            os_name="macos",
            os_label=f"macOS {platform.mac_ver()[0]}".strip(),
            pm_key="macos_brew" if has else None,
        )

    if system == "FreeBSD":
        has = shutil.which("pkg") is not None
        return SystemInfo(
            os_name="freebsd",
            os_label=f"{system} {platform.release()}",
            pm_key="freebsd_pkg" if has else None,
        )

    if system == "Linux":
        release = _os_release()
        distro_id = release.get("ID", "").lower() or None
        present = [key for binary, key in _LINUX_MANAGERS if shutil.which(binary)]
        preferred = _distro_preference(distro_id, release.get("ID_LIKE", ""))
        ordered = _linux_order(present, preferred, distro_id)
        primary = ordered[0] if ordered else None
        return SystemInfo(
            os_name="linux",
            os_label=release.get("PRETTY_NAME") or "Linux",
            pm_key=primary,
            pm_fallbacks=ordered[1:],
            distro_id=distro_id,
        )

    return SystemInfo(os_name="other", os_label=system or "Unknown", pm_key=None)


def _os_release() -> dict[str, str]:
    """Parse /etc/os-release into a dict (PRETTY_NAME, ID, ID_LIKE, ...)."""
    release: dict[str, str] = {}
    try:
        with open("/etc/os-release", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                release[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return release


def _distro_preference(distro_id: str | None, id_like: str) -> list[str]:
    """Package-manager keys the distro expects, most specific first."""
    mapping = {
        "arch": "linux_arch_pacman",
        "manjaro": "linux_arch_pacman",
        "endeavouros": "linux_arch_pacman",
        "debian": "linux_debian_apt",
        "ubuntu": "linux_debian_apt",
        "linuxmint": "linux_debian_apt",
        "pop": "linux_debian_apt",
        "fedora": "linux_fedora_rpm",
        "rhel": "linux_fedora_rpm",
        "centos": "linux_fedora_rpm",
        "rocky": "linux_fedora_rpm",
        "almalinux": "linux_fedora_rpm",
        "opensuse-leap": "linux_opensuse_zypper",
        "opensuse-tumbleweed": "linux_opensuse_zypper",
        "opensuse": "linux_opensuse_zypper",
        "suse": "linux_opensuse_zypper",
        "gentoo": "linux_gentoo_emerge",
        "alpine": "linux_alpine_apk",
        "void": "linux_void_xbps",
        "nixos": "unix_nix_env",
    }
    preferred: list[str] = []
    for name in [distro_id or "", *id_like.lower().split()]:
        key = mapping.get(name)
        if key and key not in preferred:
            preferred.append(key)
    return preferred


def _ostree_booted() -> bool:
    """True on Fedora Atomic/Silverblue-style immutable hosts."""
    return Path("/run/ostree-booted").exists()


def _linux_order(
    present: list[str], preferred: list[str], distro_id: str | None
) -> list[str]:
    """Order of usable managers: distro preference, then the rest.

    Special cases:
    - Immutable Fedora: never use dnf for layering; prefer flatpak, then
      rpm-ostree (which needs a reboot).
    - A non-NixOS box with nix-env installed: nix-env goes last, because
      ``nixos.*`` attributes are not reliable outside NixOS.
    """
    ordered = [key for key in preferred if key in present]
    ordered += [key for key in present if key not in ordered]

    if _ostree_booted():
        ordered = [key for key in ordered if key != "linux_fedora_rpm"]
        if "linux_flatpak" in ordered:
            ordered.remove("linux_flatpak")
            ordered.insert(0, "linux_flatpak")
        elif "linux_fedora_rpm_ostree" in ordered:
            ordered.remove("linux_fedora_rpm_ostree")
            ordered.insert(0, "linux_fedora_rpm_ostree")

    if distro_id != "nixos" and "unix_nix_env" in ordered:
        ordered.remove("unix_nix_env")
        ordered.append("unix_nix_env")

    return ordered


def _linux_distro_label() -> str:
    """Best-effort pretty name from /etc/os-release."""
    return _os_release().get("PRETTY_NAME") or "Linux"


# CLI binary -> agent key used in agents-pkgs.json installs (see commands.build_agents).
_AGENT_CLIS: list[tuple[str, str]] = [
    ("claude", "claude"),
    ("codex", "codex"),
    ("copilot", "copilot"),
]


def detect_agent_clis() -> list[str]:
    """Agent CLIs (claude/codex/copilot) found on PATH, in a stable order."""
    return [agent for binary, agent in _AGENT_CLIS if shutil.which(binary)]


@dataclass(frozen=True)
class AdbDevice:
    serial: str
    model: str | None = None

    @property
    def label(self) -> str:
        return f"{self.serial} ({self.model})" if self.model else self.serial


def _parse_adb_devices(output: str) -> list[AdbDevice]:
    """Parse ``adb devices -l`` (only lines in the 'device' state)."""
    devices: list[AdbDevice] = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 2 or parts[1] != "device":
            continue
        model = None
        for token in parts[2:]:
            if token.startswith("model:"):
                model = token.split(":", 1)[1].replace("_", " ")
                break
        devices.append(AdbDevice(parts[0], model))
    return devices


def adb_device_entries() -> list[AdbDevice]:
    """Connected Android devices with their model labels."""
    if shutil.which("adb") is None:
        return []
    import subprocess

    try:
        completed = subprocess.run(
            ["adb", "devices", "-l"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if completed.returncode != 0:
        return []
    return _parse_adb_devices(completed.stdout)


def adb_devices() -> list[str]:
    """Return serials of connected Android devices (empty if adb missing)."""
    return [device.serial for device in adb_device_entries()]
