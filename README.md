# Interneto Install (TUI)

A cross-platform terminal app that brings the Interneto toolbox installers to
your terminal. It **autodetects your operating system and package manager**,
lets you multi-select packages just like the web UI, and then **actually runs the
install** instead of handing you a command to copy/paste.

## What it installs

| Surface            | How it installs                                                                                              | Availability                   |
|--------------------|--------------------------------------------------------------------------------------------------------------|--------------------------------|
| Desktop apps       | Native package manager (`pacman`, `apt`, `dnf`, `emerge`, `pkg`, `brew`, `winget`, `flatpak`, `snap`, `nix`) | Autodetected desktop OS        |
| Libraries          | Per-language manager (`npm`, `pip`, …)                                                                       | Desktop                        |
| VS Code extensions | `code --install-extension`                                                                                   | Desktop (needs the `code` CLI) |
| Browser extensions | Downloads the `.xpi` (Firefox) / `.crx` (Chromium) and opens it so the browser installs it                  | Desktop                        |
| Mobile (Android)   | Deep-links each Play Store page on a connected device over `adb`                                             | When a device is attached      |

The package lists are the **same JSON** the web toolbox ships in its
`public/pkgs/`, bundled into the app. Re-sync them from a sibling
`interneto-website/` checkout via `python scripts/sync_pkgs.py`.

## Run it

```bash
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
interneto-install            # launch the TUI
interneto-install --detect   # just print what was autodetected
```

## Keys

- Packages are grouped into collapsible category sections (with an icon per row).
  Sections start collapsed; typing in the search box auto-expands the ones that match.
- Type to search, `space` to toggle a package, `enter` to expand/collapse a section, arrows to move.
- `i` — install the selected packages in the active tab (shows the exact commands first).
- `Ctrl+R` — rescan for Android devices.
- `q` — quit.

## Notes

- Desktop installs use your system package manager and may prompt for `sudo`.
  The app always shows the exact commands and asks for confirmation before running.
- Browser extensions are downloaded as `.xpi` (Firefox, from addons.mozilla.org)
  or `.crx` (Chromium, from Google's update service) into your Downloads folder,
  then opened so the browser runs its own install prompt. Firefox asks you to
  confirm the add-on; Chrome may refuse a `.crx` that didn't come from the Web Store.
- Android apps can't be silently installed from the CLI, so that surface opens the
  official Play Store pages for the final one-tap install.
