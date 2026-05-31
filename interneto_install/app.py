"""Textual TUI for the Interneto toolbox installer."""

from __future__ import annotations

from dataclasses import dataclass

from rich.syntax import Syntax
from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Collapsible,
    Footer,
    Header,
    Input,
    Label,
    RichLog,
    Select,
    SelectionList,
    Static,
    TabbedContent,
    TabPane,
)
from textual.widgets.selection_list import Selection

from . import commands, data, detect, favorites, icons, runner

# Maps each tab to the favorites surface key it manages.
_SURFACE_BY_TAB = {
    "tab-desktop": "desktop",
    "tab-vscode": "vscode",
    "tab-lib": "lib",
    "tab-browser": "browser",
    "tab-mobile": "mobile",
}


@dataclass(frozen=True)
class Item:
    value: str
    label: str
    category: str

    @property
    def search(self) -> str:
        return f"{self.label} {self.category}".lower()


# --------------------------------------------------------------------------- #
# Data adapters: turn the toolbox JSON into pickable items per surface.
# --------------------------------------------------------------------------- #
def desktop_items(pm_key: str | None) -> list[Item]:
    items: list[Item] = []
    for pkg_id, info in data.desktop_packages().items():
        managers = info.get("package_manager", {})
        installable = bool(pm_key) and (
            managers.get(pm_key)
            or (pm_key == "linux_arch_pacman" and managers.get("linux_arch_aur"))
        )
        if not installable:
            continue
        items.append(Item(pkg_id, info.get("name", pkg_id), info.get("category", "Other")))
    return sorted(items, key=lambda i: (i.category, i.label.lower()))


def vscode_items() -> list[Item]:
    items = [
        Item(ext_id, info.get("name", ext_id), info.get("category", "Other"))
        for ext_id, info in data.vscode_extensions().items()
    ]
    return sorted(items, key=lambda i: (i.category, i.label.lower()))


def browser_items() -> list[Item]:
    items = [
        Item(ext_id, info.get("name", ext_id), info.get("category", "Other"))
        for ext_id, info in data.browser_extensions().items()
    ]
    return sorted(items, key=lambda i: (i.category, i.label.lower()))


def mobile_items() -> list[Item]:
    items = []
    for pkg_id, info in data.mobile_packages().items():
        if info.get("package_manager", {}).get("android_pkg"):
            items.append(Item(pkg_id, info.get("name", pkg_id), info.get("category", "Other")))
    return sorted(items, key=lambda i: (i.category, i.label.lower()))


def lib_items(language: str) -> list[Item]:
    lang = data.lib_languages().get(language, {})
    items = []
    for category, libs in lang.get("categories", {}).items():
        for lib in libs:
            items.append(Item(lib["name"], lib.get("display", lib["name"]), category))
    return sorted(items, key=lambda i: (i.category, i.label.lower()))


# --------------------------------------------------------------------------- #
# Reusable multi-select picker (search box + checkbox list).
# --------------------------------------------------------------------------- #
class SelectionCountChanged(Message):
    """Posted by a picker whenever its persistent selection size changes."""

    def __init__(self, count: int) -> None:
        super().__init__()
        self.count = count


class PackagePicker(Vertical):
    def __init__(self, items: list[Item], placeholder: str = "Search…") -> None:
        super().__init__()
        self._items = items
        self._placeholder = placeholder
        self._selected: set[str] = set()
        self._query = ""

    def compose(self) -> ComposeResult:
        yield Input(placeholder=self._placeholder, classes="picker-search")
        yield Vertical(classes="picker-groups")

    def on_mount(self) -> None:
        self._rebuild()

    def set_items(self, items: list[Item], keep_selection: bool = False) -> None:
        self._items = items
        if not keep_selection:
            self._selected.clear()
        self._query = ""
        self.query_one(Input).value = ""
        self._rebuild()
        self.post_message(SelectionCountChanged(len(self._selected)))

    def _visible_items(self) -> list[Item]:
        if not self._query:
            return self._items
        return [i for i in self._items if self._query in i.search]

    def _grouped(self) -> dict[str, list[Item]]:
        # Items arrive pre-sorted by (category, label), so insertion order keeps
        # categories together and alphabetical.
        groups: dict[str, list[Item]] = {}
        for item in self._visible_items():
            groups.setdefault(item.category, []).append(item)
        return groups

    def on_resize(self) -> None:
        self._apply_columns(len(self.query(Collapsible)))

    def _apply_columns(self, section_count: int) -> None:
        # Flexbox-style responsive grid: up to 5 columns, fewer on narrow
        # terminals (each category card wants ~24 cells of width).
        width = self.size.width or 80
        cols = max(1, min(5, width // 24, section_count or 1))
        self.query_one(".picker-groups", Vertical).styles.grid_size_columns = cols

    def _rebuild(self) -> None:
        container = self.query_one(".picker-groups", Vertical)
        container.remove_children()
        groups = self._grouped()
        if not groups:
            self._apply_columns(1)
            container.mount(Label("No matches.", classes="pane-note"))
            return
        sections = []
        for category, cat_items in groups.items():
            sel_list = SelectionList[str](
                *[
                    Selection(
                        f"{icons.icon_for_category(item.category)}  {item.label}",
                        item.value,
                        item.value in self._selected,
                    )
                    for item in cat_items
                ],
                classes="picker-list",
            )
            # Sections are expanded by default; collapse a header to hide its list.
            sections.append(
                Collapsible(
                    sel_list,
                    title=f"{category}  ({len(cat_items)})",
                    collapsed=False,
                )
            )
        self._apply_columns(len(sections))
        container.mount(*sections)

    @on(Input.Changed)
    def _filter(self, event: Input.Changed) -> None:
        self._query = event.value.strip().lower()
        self._rebuild()

    @on(SelectionList.SelectedChanged)
    def _track(self) -> None:
        # Reconcile the currently-visible selections back into the persistent set
        # without disturbing selections that are filtered out of view. All mounted
        # lists together show exactly the visible (filtered) items.
        visible = {i.value for i in self._visible_items()}
        current: set[str] = set()
        for sel_list in self.query(SelectionList):
            current |= set(sel_list.selected)
        self._selected = (self._selected - visible) | current
        self.post_message(SelectionCountChanged(len(self._selected)))

    def apply_favorites(self, ids: list[str]) -> int:
        """Add favorites that exist in this surface to the selection.

        Returns how many applicable favorites were selected.
        """
        available = {item.value for item in self._items}
        to_add = available & set(ids)
        if to_add:
            self._selected |= to_add
            self._rebuild()
            self.post_message(SelectionCountChanged(len(self._selected)))
        return len(to_add)

    def selected_ids(self) -> list[str]:
        return list(self._selected)


# --------------------------------------------------------------------------- #
# Confirm + run modals.
# --------------------------------------------------------------------------- #
class ConfirmScreen(ModalScreen[bool]):
    def __init__(
        self, title: str, preview: str, footnote: str = "", language: str | None = "bash"
    ) -> None:
        super().__init__()
        self._title = title
        self._preview = preview
        self._footnote = footnote
        self._language = language

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Label(self._title, id="confirm-title")
            if self._preview and self._language:
                # Syntax-highlight and wrap so long command lists stay readable.
                body = Syntax(
                    self._preview,
                    self._language,
                    theme="ansi_dark",
                    word_wrap=True,
                    background_color="default",
                )
                yield Static(body, id="confirm-preview")
            else:
                yield Static(self._preview or "(nothing to run)", id="confirm-preview")
            if self._footnote:
                yield Label(self._footnote, id="confirm-foot")
            with Horizontal(id="confirm-buttons"):
                yield Button("Run", variant="success", id="confirm-run")
                yield Button("Cancel", variant="default", id="confirm-cancel")

    @on(Button.Pressed, "#confirm-run")
    def _run(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#confirm-cancel")
    def _cancel(self) -> None:
        self.dismiss(False)


class RunScreen(ModalScreen[None]):
    BINDINGS = [("escape", "close", "Close")]

    def __init__(self, lines, title: str = "Installing…") -> None:
        super().__init__()
        self._lines = lines  # any iterable yielding log strings
        self._title = title

    def compose(self) -> ComposeResult:
        with Vertical(id="run-box"):
            yield Label(self._title, id="run-title")
            yield RichLog(id="run-log", wrap=True, highlight=False, markup=False)
            yield Button("Close", variant="primary", id="run-close", disabled=True)

    def on_mount(self) -> None:
        self._execute()

    @work(thread=True)
    def _execute(self) -> None:
        log = self.query_one(RichLog)
        for line in self._lines:
            self.app.call_from_thread(log.write, line)
        self.app.call_from_thread(self._finish)

    def _finish(self) -> None:
        self.query_one("#run-title", Label).update("Finished")
        self.query_one("#run-close", Button).disabled = False

    @on(Button.Pressed, "#run-close")
    def action_close(self) -> None:
        self.dismiss(None)


# --------------------------------------------------------------------------- #
# Main app.
# --------------------------------------------------------------------------- #
class InternetoInstallApp(App[None]):
    TITLE = "Interneto · Toolbox Installer"
    CSS = """
    #system-bar { height: auto; padding: 0 1; background: $panel; color: $text; }
    #system-bar .ok { color: $success; }
    #system-bar .warn { color: $warning; }
    TabbedContent { height: 1fr; }
    PackagePicker { height: 1fr; }
    .picker-search { margin: 0 0 1 0; }
    .picker-groups {
        layout: grid; grid-size: 5; grid-gutter: 1; grid-rows: auto;
        height: 1fr; overflow-y: auto;
    }
    .picker-groups Collapsible { height: auto; margin: 0; border: round $primary; }
    /* Cap each card so a long category scrolls in place instead of stretching
       its whole grid row — keeps the expanded grid compact and even. */
    .picker-list {
        height: auto; max-height: 14; overflow-y: auto;
        border: none; background: transparent; padding: 0;
    }
    .lib-lang, .browser-target { margin: 0 0 1 0; width: 40; }
    #toolbar { height: auto; padding: 0 1; align-horizontal: left; }
    #toolbar Button { margin: 0 1 0 0; min-width: 14; }
    #count-bar { height: auto; padding: 0 1; background: $boost; }
    #confirm-box, #run-box {
        width: 90; max-width: 100%; height: auto; max-height: 80%;
        padding: 1 2; border: thick $primary; background: $surface;
    }
    #confirm-preview { padding: 1; background: $panel; height: auto; max-height: 18; overflow-y: auto; }
    #confirm-foot { color: $text-muted; margin: 1 0 0 0; }
    #confirm-buttons { height: auto; margin: 1 0 0 0; }
    #confirm-buttons Button { margin: 0 1 0 0; }
    #run-log { height: 24; border: round $primary; }
    #run-close { margin: 1 0 0 0; }
    .pane-note { color: $text-muted; padding: 0 0 1 0; }
    """

    BINDINGS = [
        ("i", "install", "Install selected"),
        ("f", "favorites", "Favorites ✨"),
        ("ctrl+r", "rescan", "Rescan devices"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.system = detect.detect_system()
        self.lib_lang = next(iter(data.lib_languages()), "javascript")
        self.browser_target = "firefox"
        self.favorites = favorites.load()

    def compose(self) -> ComposeResult:
        yield Header()
        sys = self.system
        pm_class = "ok" if sys.pm_key else "warn"
        yield Static(
            f"Detected: [b]{sys.os_label}[/b]   ·   package manager: "
            f"[{pm_class}]{sys.pm_label}[/{pm_class}]",
            id="system-bar",
        )

        with TabbedContent(initial="tab-desktop"):
            with TabPane("Desktop apps", id="tab-desktop"):
                if not sys.pm_key:
                    yield Label(
                        "No supported package manager found — desktop installs are disabled.",
                        classes="pane-note",
                    )
                yield PackagePicker(desktop_items(sys.pm_key), "Search desktop apps")
            with TabPane("Browser ext", id="tab-browser"):
                yield Select(
                    [("Firefox", "firefox"), ("Chromium / Chrome", "chromium")],
                    value="firefox", allow_blank=False, classes="browser-target",
                    id="browser-select",
                )
                yield Label(
                    "Browser stores have no CLI install — selected pages open in your browser.",
                    classes="pane-note",
                )
                yield PackagePicker(browser_items(), "Search browser extensions")
            with TabPane("Libraries", id="tab-lib"):
                yield Select(
                    [(f"{l.get('emoji','')} {l.get('label', k)}".strip(), k)
                     for k, l in data.lib_languages().items()],
                    value=self.lib_lang, allow_blank=False, classes="lib-lang",
                    id="lib-select",
                )
                yield PackagePicker(lib_items(self.lib_lang), "Search libraries")
            with TabPane("VS Code", id="tab-vscode"):
                yield PackagePicker(vscode_items(), "Search VS Code extensions")
            with TabPane("Mobile (adb)", id="tab-mobile"):
                yield Label("", id="mobile-status", classes="pane-note")
                yield PackagePicker(mobile_items(), "Search mobile apps")

        with Horizontal(id="toolbar"):
            yield Button("✨ Favorites", id="fav-apply", variant="primary")
            yield Button("★ Export", id="fav-export")
            yield Button("⭳ Import", id="fav-import")
        yield Static("Nothing selected", id="count-bar")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_mobile_status()

    # ---- helpers -------------------------------------------------------- #
    def _active_picker(self) -> PackagePicker | None:
        pane = self.query_one(TabbedContent).active_pane
        if pane is None:
            return None
        pickers = pane.query(PackagePicker)
        return pickers.first() if pickers else None

    def _refresh_mobile_status(self) -> None:
        devices = detect.adb_devices()
        status = self.query_one("#mobile-status", Label)
        if devices:
            status.update(f"Connected device(s): {', '.join(devices)} — Ctrl+R to rescan.")
        else:
            status.update("No Android device detected (need adb + USB debugging). Ctrl+R to rescan.")

    @on(SelectionCountChanged)
    def _update_count(self, event: SelectionCountChanged) -> None:
        self.query_one("#count-bar", Static).update(
            f"{event.count} selected — press [b]i[/b] to install"
            if event.count else "Nothing selected"
        )

    @on(Select.Changed, "#lib-select")
    def _change_lang(self, event: Select.Changed) -> None:
        self.lib_lang = str(event.value)
        pane = self.query_one("#tab-lib", TabPane)
        pane.query_one(PackagePicker).set_items(lib_items(self.lib_lang))

    @on(Select.Changed, "#browser-select")
    def _change_browser(self, event: Select.Changed) -> None:
        self.browser_target = str(event.value)

    # ---- favorites ------------------------------------------------------ #
    def _active_surface(self) -> str | None:
        return _SURFACE_BY_TAB.get(self.query_one(TabbedContent).active)

    def action_favorites(self) -> None:
        surface = self._active_surface()
        picker = self._active_picker()
        if not surface or picker is None:
            return
        added = picker.apply_favorites(self.favorites.get(surface, []))
        if added:
            self.notify(f"✨ Selected {added} favorite(s) in this section.")
        else:
            self.notify("No favorites available for this section.", severity="warning")

    @on(Button.Pressed, "#fav-apply")
    def _fav_apply(self) -> None:
        self.action_favorites()

    @on(Button.Pressed, "#fav-export")
    def _fav_export(self) -> None:
        surface = self._active_surface()
        picker = self._active_picker()
        if not surface or picker is None:
            return
        selected = sorted(picker.selected_ids())
        if not selected:
            self.notify("Nothing selected to export as favorites.", severity="warning")
            return
        self.favorites[surface] = selected
        try:
            path = favorites.save(self.favorites)
        except OSError as exc:
            self.notify(f"Could not save favorites: {exc}", severity="error")
            return
        self.notify(f"★ Saved {len(selected)} favorite(s) for '{surface}' → {path}")

    @on(Button.Pressed, "#fav-import")
    def _fav_import(self) -> None:
        self.favorites = favorites.load()
        path = favorites.user_path()
        source = str(path) if path.is_file() else "bundled defaults"
        self.notify(f"Imported favorites from {source}.")
        self.action_favorites()

    # ---- actions -------------------------------------------------------- #
    def action_rescan(self) -> None:
        self._refresh_mobile_status()

    def action_install(self) -> None:
        active_id = self.query_one(TabbedContent).active
        picker = self._active_picker()
        if picker is None:
            return
        selected = picker.selected_ids()
        if not selected:
            self.notify("Nothing selected in this tab.", severity="warning")
            return

        if active_id == "tab-browser":
            self._install_browser(selected)
            return

        if active_id == "tab-desktop":
            if not self.system.pm_key:
                self.notify("No package manager available.", severity="error")
                return
            plan = commands.build_desktop(self.system.pm_key, selected)
        elif active_id == "tab-vscode":
            plan = commands.build_vscode(selected)
        elif active_id == "tab-lib":
            plan = commands.build_lib(self.lib_lang, selected)
        elif active_id == "tab-mobile":
            devices = detect.adb_devices()
            if not devices:
                self.notify("No Android device connected.", severity="error")
                return
            plan = commands.build_mobile(devices[0], selected)
        else:
            return

        if not plan.has_commands:
            self.notify("Nothing installable for this system.", severity="warning")
            return

        footnote = plan.note or ""
        if plan.non_installable:
            skipped = ", ".join(plan.non_installable[:8])
            extra = "…" if len(plan.non_installable) > 8 else ""
            footnote = (footnote + "\n" if footnote else "") + f"Skipped (unavailable): {skipped}{extra}"

        def _on_confirm(confirmed: bool | None) -> None:
            if confirmed:
                self.push_screen(RunScreen(runner.run_commands(plan.commands)))

        self.push_screen(
            ConfirmScreen("Review the commands that will run:", plan.preview(), footnote),
            _on_confirm,
        )

    def _install_browser(self, selected: list[str]) -> None:
        downloads, skipped = commands.browser_downloads(selected, self.browser_target)
        if not downloads:
            self.notify("No downloadable extensions for the chosen browser.", severity="warning")
            return
        ext = "xpi" if self.browser_target == "firefox" else "crx"
        preview = "\n".join(f"{d.name}\n  {d.filename}  ←  {d.url}" for d in downloads)
        foot = f"Downloads {len(downloads)} .{ext} file(s) and opens each to finish installing."
        if skipped:
            foot += f"  Skipped: {', '.join(skipped[:6])}"
        if self.browser_target == "chromium":
            foot += "\nChrome may refuse a .crx that wasn't installed from the Web Store."

        def _on_confirm(confirmed: bool | None) -> None:
            if confirmed:
                self.push_screen(
                    RunScreen(
                        runner.run_browser_installs(downloads),
                        title=f"Downloading .{ext} extensions…",
                    )
                )

        self.push_screen(
            ConfirmScreen("Download and install these extensions?", preview, foot, language=None),
            _on_confirm,
        )


def run() -> None:
    InternetoInstallApp().run()
