# Interneto Install (TUI)

A cross-platform terminal app that brings the Interneto toolbox installers to
your terminal. It **autodetects your operating system and package manager**,
lets you multi-select packages just like the web UI, and then **actually runs the
install** instead of handing you a command to copy/paste.

## What it installs

| Surface | How it installs | Availability |
| --- | --- | --- |
| Desktop apps | Native package manager (`pacman`, `apt`, `dnf`, `emerge`, `pkg`, `brew`, `winget`, `flatpak`, `snap`, `nix`) | Autodetected desktop OS |
| Libraries | Per-language manager (`npm`, `pip`, …) | Desktop |
| VS Code extensions | `code --install-extension` | Desktop (needs the `code` CLI) |
| Browser extensions | Opens the Firefox/Chromium store page (no CLI install exists) | Desktop |
| Mobile (Android) | Deep-links each Play Store page on a connected device over `adb` | When a device is attached |

The package lists are the **same JSON** the web toolbox ships in its
`public/pkgs/`, bundled into the app. Re-sync them from a sibling
`interneto-website/` checkout via `python scripts/sync_pkgs.py`.

## Run it

```bash
cd tui-installer
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
interneto-install            # launch the TUI
interneto-install --detect   # just print what was autodetected
```

## Keys

- Type to search, `space` to toggle a package, arrows to move.
- `i` — install the selected packages in the active tab (shows the exact commands first).
- `Ctrl+R` — rescan for Android devices.
- `q` — quit.

## Notes

- Desktop installs use your system package manager and may prompt for `sudo`.
  The app always shows the exact commands and asks for confirmation before running.
- Browser extensions and Android apps can't be silently installed from the CLI,
  so those surfaces open the official store pages for the final one-tap install.
