"""Steam-inspired Tkinter control panel for the donation bot."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

from loguru import logger

from coc_bot import __version__
from coc_bot.calibration.wizard import (
    STEP_IDS,
    STEPS,
    CalibrationWizard,
    parent_step_id,
    part_is_configured,
)
from coc_bot.config import load_config, project_root, user_settings_path
from coc_bot.gui.calib_backup import (
    CalibrationBackup,
    create_backup,
    list_backups,
    restore_backup,
)
from coc_bot.gui.debug_actions import DEBUG_GROUPS, DebugSession, run_debug_action
from coc_bot.gui.debug_export import export_debug_bundle
from coc_bot.gui.notify import notify
import coc_bot.gui.theme as theme
from coc_bot.gui.settings_fields import (
    SETTINGS,
    current_setting_values,
    is_raw_timing_field,
    save_settings_from_gui,
)
from coc_bot.gui.setup_calib import calibrate_part_in_app, part_supports_in_app
from coc_bot.gui.theme import (
    active_layout,
    apply_theme,
    finish_scrollable,
    make_scrollable,
    normalize_theme_id,
    theme_label,
    ui_font,
)
from coc_bot.gui.ui_helpers import (
    GuiWindowState,
    adb_status_label,
    format_countdown,
    humanize_setting_value,
    load_gui_window_state,
    save_gui_window_state,
)
from coc_bot.gui.util import calibrate_script, open_in_terminal
from coc_bot.gui.widgets import ToggleSwitch

PAGES = (
    ("home", "Home", "Start the bot, farm, and watch activity"),
    ("settings", "Settings", "Timing, donations, farm, and breaks"),
    ("setup", "Setup", "Teach the bot where buttons are on your screen"),
    ("tools", "Tools", "One-shot tests when something looks wrong"),
)

# Matches loguru sink output: "HH:mm:ss | LEVEL   | message".
_LOG_LINE_RE = re.compile(r"^(\d{2}:\d{2}:\d{2})\s*\|\s*([A-Za-z]+)\s*\|\s*(.*)$")
_LOG_LEVEL_TAGS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


class BotControlApp(tk.Tk):
    def __init__(
        self,
        *,
        dry_run: bool = False,
        debug_save_frames: bool = False,
        debug: bool = False,
    ) -> None:
        super().__init__()
        self.title("CoC Donation Bot")
        self.geometry("1040x720")
        self.minsize(860, 600)
        self._gui_state: GuiWindowState = load_gui_window_state(self._window_geometry_path())
        if self._gui_state.geometry:
            try:
                self.geometry(self._gui_state.geometry)
            except tk.TclError:
                pass
        self._theme_id = normalize_theme_id(load_config().gui_theme)
        apply_theme(self, self._theme_id)

        self._dry_run = dry_run
        self._debug_save_frames = debug_save_frames
        self._debug = debug
        self._bot = None
        self._bot_thread: threading.Thread | None = None
        self._farm_oneshot_thread: threading.Thread | None = None
        self._farm_oneshot_stop = threading.Event()
        self._log_sink_id: int | None = None
        self._setting_vars: dict[str, tk.Variable] = {}
        self._setting_hint_labels: dict[str, tk.Label] = {}
        self._debug_busy = False
        self._page = "home"
        self._nav_buttons: dict[str, ttk.Button] = {}
        self._nav_accents: dict[str, tk.Frame] = {}
        self._pages: dict[str, ttk.Frame] = {}
        self._page_title = tk.StringVar(value="Home")
        self._page_subtitle = tk.StringVar(value=PAGES[0][2])
        self._status = tk.StringVar(
            value="Ready — open Waydroid and Clash of Clans, then press Start"
        )
        self._adb_status_var = tk.StringVar(value="ADB · …")
        self._last_adb_ok: bool | None = None
        self._adb_banner: tk.Frame | None = None
        self._onboarding_frame: tk.Frame | None = None
        self._onboarding_checklist_var = tk.StringVar(value="")
        self._home_anchor: tk.Misc | None = None
        self._log_lines: list[str] = []
        self._run_chip_var = tk.StringVar(value="Stopped")
        self._farm_timer_var = tk.StringVar(value="—")
        self._break_timer_var = tk.StringVar(value="—")
        # Frozen farm countdown while the bot is stopped (wall clock still advances).
        self._farm_timer_frozen_text: str | None = None
        self._calib_progress = tk.StringVar(value="")
        self._log_autoscroll = tk.BooleanVar(value=True)
        self._section_collapsed: dict[str, bool] = {}
        self._tool_buttons: list[ttk.Button] = []
        self._settings_canvas: tk.Canvas | None = None
        self._tools_canvas: tk.Canvas | None = None
        self._sidebar_chrome: list[tk.Misc] = []
        self._statusbar_chrome: list[tk.Misc] = []
        # (page_id, label, horizontal reserve px) — wraplength tracks content width.
        self._wrap_labels: list[tuple[str, tk.Label, int]] = []

        shell = ttk.Frame(self)
        shell.pack(fill=tk.BOTH, expand=True)

        self._build_sidebar(shell)
        right = ttk.Frame(shell)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        header = ttk.Frame(right, padding=(24, 18, 24, 8))
        header.pack(fill=tk.X)
        ttk.Label(header, textvariable=self._page_title, style="PageTitle.TLabel").pack(
            anchor=tk.W
        )
        ttk.Label(header, textvariable=self._page_subtitle, style="Subtitle.TLabel").pack(
            anchor=tk.W, pady=(4, 0)
        )

        self._content = ttk.Frame(right, padding=(16, 4, 16, 8))
        self._content.pack(fill=tk.BOTH, expand=True)
        self._content.bind("<Configure>", self._on_content_configure, add="+")

        for page_id, _label, _subtitle in PAGES:
            page = ttk.Frame(self._content)
            self._pages[page_id] = page

        self._build_home_page()
        self._build_settings_page()
        self._build_setup_page()
        self._build_tools_page()

        status = ttk.Frame(right, style="StatusBar.TFrame", padding=(16, 8))
        status.pack(fill=tk.X, side=tk.BOTTOM)
        self._adb_status_label = tk.Label(
            status,
            textvariable=self._adb_status_var,
            bg=theme.STATUS_BAR,
            fg=theme.TEXT_SECONDARY,
            font=ui_font(10),
        )
        self._adb_status_label.pack(side=tk.RIGHT)
        ttk.Label(status, textvariable=self._status, style="Status.TLabel").pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )
        self._statusbar_chrome.append(status)
        self._statusbar_chrome.append(self._adb_status_label)

        start_page = self._gui_state.last_page if self._gui_state.last_page in self._pages else "home"
        self._show_page(start_page)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(400, self._refresh_calib_status)
        self.after(1000, self._refresh_farm_status)
        self.after(1500, self._poll_adb_status)
        self._install_log_sink()

    @staticmethod
    def _window_geometry_path() -> Path:
        return project_root() / "data" / "gui_window.json"

    def _build_sidebar(self, parent: ttk.Frame) -> None:
        self._sidebar_chrome.clear()
        self._nav_buttons.clear()
        self._nav_accents.clear()
        side = tk.Frame(parent, bg=theme.SIDEBAR, width=200)
        side.pack(side=tk.LEFT, fill=tk.Y)
        side.pack_propagate(False)
        self._sidebar_chrome.append(side)

        brand = tk.Frame(side, bg=theme.SIDEBAR)
        brand.pack(fill=tk.X, padx=16, pady=(20, 24))
        self._sidebar_chrome.append(brand)
        for text, size, weight, pady in (
            ("CoC Bot", 13, "bold", (0, 0)),
            (f"v{__version__}", 9, "normal", (4, 0)),
        ):
            lab = tk.Label(
                brand,
                text=text,
                bg=theme.SIDEBAR,
                fg=theme.TEXT if weight == "bold" else theme.TEXT_SECONDARY,
                font=ui_font(size, weight),
                anchor="w",
            )
            lab.pack(fill=tk.X, pady=pady)
            self._sidebar_chrome.append(lab)

        nav_wrap = tk.Frame(side, bg=theme.SIDEBAR)
        nav_wrap.pack(fill=tk.X, padx=8, pady=(4, 0))
        self._sidebar_chrome.append(nav_wrap)

        for page_id, label, _subtitle in PAGES:
            row = tk.Frame(nav_wrap, bg=theme.SIDEBAR)
            row.pack(fill=tk.X, pady=1)
            self._sidebar_chrome.append(row)
            accent = tk.Frame(row, bg=theme.SIDEBAR, width=3)
            accent.pack(side=tk.LEFT, fill=tk.Y)
            self._nav_accents[page_id] = accent
            btn = ttk.Button(
                row,
                text=label,
                style="Nav.TButton",
                command=lambda pid=page_id: self._show_page(pid),
            )
            btn.pack(side=tk.LEFT, fill=tk.X, expand=True)
            self._nav_buttons[page_id] = btn

        self._update_nav_accents()

    def _update_nav_accents(self) -> None:
        for pid, accent in self._nav_accents.items():
            try:
                if accent.winfo_exists():
                    accent.configure(bg=theme.ACCENT if pid == self._page else theme.SIDEBAR)
            except tk.TclError:
                continue

    def _show_page(self, page_id: str) -> None:
        self._page = page_id
        for pid, frame in self._pages.items():
            if pid == page_id:
                frame.pack(fill=tk.BOTH, expand=True)
            else:
                frame.pack_forget()
        for pid, btn in self._nav_buttons.items():
            btn.configure(style="NavSelected.TButton" if pid == page_id else "Nav.TButton")
        self._update_nav_accents()
        for pid, label, subtitle in PAGES:
            if pid == page_id:
                self._page_title.set(label)
                self._page_subtitle.set(subtitle)
                break
        self.after_idle(self._sync_wrap_lengths)
        self._gui_state.last_page = page_id
        self._save_gui_state()

    def _save_gui_state(self) -> None:
        try:
            self._gui_state.geometry = self.geometry()
        except tk.TclError:
            pass
        try:
            save_gui_window_state(self._window_geometry_path(), self._gui_state)
        except OSError as exc:
            logger.warning("Could not save GUI window state: {}", exc)

    def _on_content_configure(self, event: tk.Event) -> None:
        if event.widget is not self._content:
            return
        if event.width >= 120:
            self._sync_wrap_lengths(event.width)

    def _poll_adb_status(self) -> None:
        def worker() -> None:
            try:
                from coc_bot.adb.client import AdbClient

                config = load_config()
                ok = AdbClient(device=config.adb_device).get_state() == "device"
            except Exception:  # noqa: BLE001
                ok = None
            self.after(0, lambda: self._set_adb_status(ok))

        threading.Thread(target=worker, daemon=True).start()
        self.after(8000, self._poll_adb_status)

    def _set_adb_status(self, ok: bool | None) -> None:
        previous = self._last_adb_ok
        self._last_adb_ok = ok
        label, role = adb_status_label(ok)
        self._adb_status_var.set(label)
        color = {
            "ok": theme.SUCCESS,
            "bad": theme.DANGER,
            "unknown": theme.TEXT_SECONDARY,
        }.get(role, theme.TEXT_SECONDARY)
        try:
            if self._adb_status_label.winfo_exists():
                self._adb_status_label.configure(fg=color)
        except tk.TclError:
            pass
        if previous is True and ok is False and self._bot_running():
            notify("ADB disconnected", "The bot may not be able to control the device.")
        self._refresh_home_status()

    @property
    def _modern(self) -> bool:
        """True when the active theme uses row/toggle settings layout."""
        return active_layout() == "modern"

    def _recolor_sidebar(self) -> None:
        for widget in self._sidebar_chrome:
            try:
                if not widget.winfo_exists():
                    continue
                widget.configure(bg=theme.SIDEBAR)
                if "fg" in widget.keys():
                    current = str(widget.cget("text") or "")
                    if current == "CoC Bot":
                        widget.configure(fg=theme.TEXT)
                    else:
                        widget.configure(fg=theme.TEXT_SECONDARY)
            except tk.TclError:
                continue
        self._update_nav_accents()
        self._recolor_statusbar()

    def _recolor_statusbar(self) -> None:
        for widget in self._statusbar_chrome:
            try:
                if not widget.winfo_exists():
                    continue
                if isinstance(widget, ttk.Frame):
                    continue
                widget.configure(bg=theme.STATUS_BAR)
            except tk.TclError:
                continue
        self._set_adb_status(self._last_adb_ok)

    def _rebuild_pages_for_theme(self) -> None:
        """Rebuild page contents after a theme/layout change."""
        current = self._page
        self._wrap_labels.clear()
        for frame in self._pages.values():
            for child in frame.winfo_children():
                child.destroy()
        self._build_home_page()
        self._build_settings_page()
        self._build_setup_page()
        self._build_tools_page()
        self._show_page(current)
        self.after(100, self._refresh_calib_status)

    def _apply_theme_id(self, theme_id: str) -> None:
        self._theme_id = normalize_theme_id(theme_id)
        apply_theme(self, self._theme_id)
        self._recolor_sidebar()
        self._rebuild_pages_for_theme()

    def _clear_wrap_labels(self, page_id: str) -> None:
        self._wrap_labels = [(p, lab, r) for p, lab, r in self._wrap_labels if p != page_id]

    def _track_wrap_label(
        self, label: tk.Label, *, reserve: int = 48, page_id: str | None = None
    ) -> None:
        """Register a label whose wraplength should follow the content width."""
        page = page_id or self._page
        self._wrap_labels.append((page, label, max(0, int(reserve))))

    def _bind_wrap_to_width(self, label: tk.Label, host: tk.Misc, *, pad: int = 8) -> None:
        """Keep label wraplength equal to *host*'s actual width."""

        def _apply(width: int) -> None:
            try:
                if label.winfo_exists():
                    label.configure(wraplength=max(100, int(width) - pad))
            except tk.TclError:
                return

        def _on_configure(event: tk.Event) -> None:
            if event.widget is not host:
                return
            if event.width >= 80:
                _apply(event.width)

        host.bind("<Configure>", _on_configure, add="+")
        self.after_idle(lambda: _apply(max(host.winfo_width(), 80)))

    def _bind_modern_row_wrap(
        self,
        labels: list[tk.Label],
        row: tk.Misc,
        right: tk.Misc,
        *,
        gap: int = 16,
    ) -> None:
        """
        Wrap modern-row labels to (row width − control column width).

        Binding only to the left frame fails because its width is still driven by
        unwrapped text request size; subtracting the right column fixes that.
        """

        def _apply() -> None:
            try:
                if not row.winfo_exists() or not right.winfo_exists():
                    return
                row.update_idletasks()
                right_w = max(right.winfo_reqwidth(), right.winfo_width())
                available = int(row.winfo_width()) - int(right_w) - gap
                wrap = max(100, available)
                for label in labels:
                    if label.winfo_exists():
                        label.configure(wraplength=wrap)
            except tk.TclError:
                return

        def _on_configure(event: tk.Event) -> None:
            if event.widget is not row:
                return
            if event.width >= 120:
                _apply()

        row.bind("<Configure>", _on_configure, add="+")
        self.after_idle(_apply)

    def _sync_wrap_lengths(self, width: int | None = None) -> None:
        """Recompute wraplength for tracked labels from the available content width."""
        if width is None or width < 80:
            try:
                width = int(self._content.winfo_width())
            except tk.TclError:
                width = 0
        if width < 80:
            return

        # Content frame padding is already outside widgets; leave a little slack.
        usable = max(140, int(width) - 8)
        alive: list[tuple[str, tk.Label, int]] = []
        for page_id, label, reserve in self._wrap_labels:
            try:
                if not label.winfo_exists():
                    continue
                label.configure(wraplength=max(140, usable - reserve))
                alive.append((page_id, label, reserve))
            except tk.TclError:
                continue
        self._wrap_labels = alive

    def _btn_style(self, kind: str) -> str:
        """Map Accent/Secondary/Danger/Play/HomeStop → modern or classic ttk style."""
        if self._modern:
            return {
                "Accent": "Modern.Accent.TButton",
                "Secondary": "Modern.Secondary.TButton",
                "Danger": "Modern.Danger.TButton",
                "Play": "Modern.Play.TButton",
                "HomeStop": "Modern.HomeStop.TButton",
            }.get(kind, "Modern.Secondary.TButton")
        return {
            "Accent": "Accent.TButton",
            "Secondary": "Secondary.TButton",
            "Danger": "Danger.TButton",
            "Play": "Play.TButton",
            "HomeStop": "HomeStop.TButton",
        }.get(kind, "Secondary.TButton")

    def _card(
        self, parent: tk.Misc, *, return_outer: bool = False, **pack_opts
    ) -> tk.Frame | tuple[tk.Frame, tk.Frame]:
        outer = tk.Frame(
            parent,
            bg=theme.SURFACE,
            bd=0,
            highlightbackground=theme.BORDER,
            highlightcolor=theme.BORDER,
            highlightthickness=1,
        )
        fill = pack_opts.pop("fill", tk.X)
        outer.pack(fill=fill, **pack_opts)
        inner = tk.Frame(outer, bg=theme.SURFACE_2, bd=0, highlightthickness=0)
        inner.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        if return_outer:
            return outer, inner
        return inner

    def _section_header(self, parent: tk.Misc, section_key: str, title: str) -> tk.Frame:
        """
        Pack a clickable collapsible section header and return its body frame.

        Toggle only shows/hides the body (no page rebuild). Collapse state is
        kept in ``self._section_collapsed`` across rebuilds.
        """
        collapsed = self._section_collapsed.get(section_key, False)
        title_upper = title.upper()
        header = tk.Label(
            parent,
            text=f"{'▸' if collapsed else '▾'} {title_upper}",
            bg=theme.BG,
            fg=theme.ACCENT,
            font=ui_font(10, "bold"),
            anchor="w",
            cursor="hand2",
        )
        header.pack(fill=tk.X, padx=8, pady=(18, 8))
        body = tk.Frame(parent, bg=theme.BG)
        if not collapsed:
            body.pack(fill=tk.X)

        def _toggle(_event: tk.Event | None = None) -> None:
            now_collapsed = not self._section_collapsed.get(section_key, False)
            self._section_collapsed[section_key] = now_collapsed
            header.configure(text=f"{'▸' if now_collapsed else '▾'} {title_upper}")
            if now_collapsed:
                body.pack_forget()
            else:
                body.pack(fill=tk.X, after=header)
            self._refresh_scroll_regions()

        header.bind("<Button-1>", _toggle)
        return body

    def _refresh_scroll_regions(self) -> None:
        """Update scrollregion for Settings/Tools canvases after collapse toggles."""
        for canvas in (self._settings_canvas, self._tools_canvas):
            if canvas is None:
                continue
            try:
                if canvas.winfo_exists():
                    canvas.update_idletasks()
                    canvas.configure(scrollregion=canvas.bbox("all"))
            except tk.TclError:
                continue

    def _build_home_page(self) -> None:
        page = self._pages["home"]

        banner_outer, banner_inner = self._card(page, pady=(0, 12), return_outer=True)
        self._adb_banner = banner_outer
        banner_pad = tk.Frame(banner_inner, bg=theme.SURFACE_2)
        banner_pad.pack(fill=tk.X, padx=16, pady=12)
        banner_label = tk.Label(
            banner_pad,
            text="⚠ ADB is offline — the bot can't see your device.",
            bg=theme.SURFACE_2,
            fg=theme.DANGER,
            font=ui_font(11, "bold"),
            anchor="w",
            justify=tk.LEFT,
            wraplength=360,
        )
        banner_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._track_wrap_label(banner_label, reserve=280, page_id="home")
        banner_btns = tk.Frame(banner_pad, bg=theme.SURFACE_2)
        banner_btns.pack(side=tk.RIGHT)
        ttk.Button(
            banner_btns,
            text="Connect ADB",
            style=self._btn_style("Accent"),
            command=self.connect_adb,
        ).pack(side=tk.LEFT)
        ttk.Button(
            banner_btns,
            text="Open Tools",
            style=self._btn_style("Secondary"),
            command=lambda: self._show_page("tools"),
        ).pack(side=tk.LEFT, padx=(8, 0))
        banner_outer.pack_forget()

        onboarding_outer, onboarding_inner = self._card(page, pady=(0, 12), return_outer=True)
        self._onboarding_frame = onboarding_outer
        ob_pad = tk.Frame(onboarding_inner, bg=theme.SURFACE_2)
        ob_pad.pack(fill=tk.X, padx=18, pady=14)
        tk.Label(
            ob_pad,
            text="Get started",
            bg=theme.SURFACE_2,
            fg=theme.TEXT,
            font=ui_font(13, "bold"),
            anchor="w",
        ).pack(anchor=tk.W)
        checklist_label = tk.Label(
            ob_pad,
            textvariable=self._onboarding_checklist_var,
            bg=theme.SURFACE_2,
            fg=theme.TEXT_SECONDARY,
            font=ui_font(10),
            justify=tk.LEFT,
            anchor="w",
        )
        checklist_label.pack(anchor=tk.W, fill=tk.X, pady=(6, 12))
        self._track_wrap_label(checklist_label, reserve=40, page_id="home")
        ob_btns = tk.Frame(ob_pad, bg=theme.SURFACE_2)
        ob_btns.pack(fill=tk.X)
        ttk.Button(
            ob_btns,
            text="Connect ADB",
            style=self._btn_style("Secondary"),
            command=self.connect_adb,
        ).pack(side=tk.LEFT)
        ttk.Button(
            ob_btns,
            text="Go to Setup",
            style=self._btn_style("Accent"),
            command=lambda: self._show_page("setup"),
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            ob_btns,
            text="Dismiss",
            style=self._btn_style("Secondary"),
            command=self._dismiss_onboarding,
        ).pack(side=tk.RIGHT)
        onboarding_outer.pack_forget()

        actions_outer, actions = self._card(page, pady=(0, 12), return_outer=True)
        self._home_anchor = actions_outer
        pad = tk.Frame(actions, bg=theme.SURFACE_2)
        pad_x = 18 if self._modern else 16
        pad_y = 16 if self._modern else 14
        pad.pack(fill=tk.X, padx=pad_x, pady=pad_y)

        play_header = tk.Frame(pad, bg=theme.SURFACE_2)
        play_header.pack(fill=tk.X)
        tk.Label(
            play_header,
            text="Play",
            bg=theme.SURFACE_2,
            fg=theme.TEXT,
            font=ui_font(13, "bold"),
            anchor="w",
        ).pack(side=tk.LEFT)
        self._run_chip = tk.Label(
            play_header,
            textvariable=self._run_chip_var,
            bg=theme.SURFACE,
            fg=theme.TEXT_SECONDARY,
            font=ui_font(10, "bold"),
            padx=10,
            pady=3,
        )
        self._run_chip.pack(side=tk.RIGHT)

        primary = tk.Frame(pad, bg=theme.SURFACE_2)
        primary.pack(fill=tk.X, pady=(12, 0))
        primary.columnconfigure(0, weight=1, uniform="home_play")
        primary.columnconfigure(1, weight=1, uniform="home_play")
        self._start_btn = ttk.Button(
            primary, text="▶  Start", style=self._btn_style("Play"), command=self.start_bot
        )
        self._start_btn.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self._stop_btn = ttk.Button(
            primary,
            text="Stop",
            style=self._btn_style("HomeStop"),
            command=self.stop_bot,
            state=tk.DISABLED,
        )
        self._stop_btn.grid(row=0, column=1, sticky="nsew", padx=(5, 0))

        secondary = tk.Frame(pad, bg=theme.SURFACE_2)
        secondary.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(
            secondary,
            text="View screenshot",
            style=self._btn_style("Secondary"),
            command=self.view_bot_screenshot,
        ).pack(side=tk.LEFT)
        ttk.Button(
            secondary,
            text="Farm attack now",
            style=self._btn_style("Secondary"),
            command=self.request_farm_attack,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            secondary,
            text="Close Waydroid + Clash",
            style=self._btn_style("Danger"),
            command=self.close_waydroid_and_coc,
        ).pack(side=tk.RIGHT)

        timers = tk.Frame(pad, bg=theme.SURFACE_2)
        timers.pack(fill=tk.X, pady=(14, 0))
        timers.columnconfigure(0, weight=1, uniform="home_timer")
        timers.columnconfigure(1, weight=1, uniform="home_timer")
        for col, title, var in (
            (0, "FARM", self._farm_timer_var),
            (1, "BREAK", self._break_timer_var),
        ):
            cell = tk.Frame(timers, bg=theme.SURFACE_2)
            cell.grid(row=0, column=col, sticky="w", padx=(0 if col == 0 else 16, 0))
            tk.Label(
                cell,
                text=title,
                bg=theme.SURFACE_2,
                fg=theme.TEXT_SECONDARY,
                font=ui_font(9, "bold"),
                anchor="w",
            ).pack(anchor=tk.W)
            tk.Label(
                cell,
                textvariable=var,
                bg=theme.SURFACE_2,
                fg=theme.TEXT,
                font=ui_font(12, "bold"),
                anchor="w",
            ).pack(anchor=tk.W)

        log_card = self._card(page, fill=tk.BOTH, expand=True)
        log_pad = tk.Frame(log_card, bg=theme.SURFACE_2)
        log_pad.pack(fill=tk.BOTH, expand=True, padx=16, pady=14)
        log_header = tk.Frame(log_pad, bg=theme.SURFACE_2)
        log_header.pack(fill=tk.X)
        tk.Label(
            log_header,
            text="Activity",
            bg=theme.SURFACE_2,
            fg=theme.TEXT,
            font=ui_font(13, "bold"),
            anchor="w",
        ).pack(side=tk.LEFT)
        header_actions = tk.Frame(log_header, bg=theme.SURFACE_2)
        header_actions.pack(side=tk.RIGHT)
        ttk.Button(
            header_actions,
            text="Copy logs",
            style=self._btn_style("Secondary"),
            command=self._copy_logs,
        ).pack(side=tk.LEFT)
        ttk.Button(
            header_actions,
            text="Export debug",
            style=self._btn_style("Secondary"),
            command=self._export_debug,
        ).pack(side=tk.LEFT, padx=(8, 0))
        autoscroll_row = tk.Frame(header_actions, bg=theme.SURFACE_2)
        autoscroll_row.pack(side=tk.LEFT, padx=(12, 0))
        tk.Label(
            autoscroll_row,
            text="Auto-scroll",
            bg=theme.SURFACE_2,
            fg=theme.TEXT_SECONDARY,
            font=ui_font(10),
        ).pack(side=tk.LEFT, padx=(0, 8))
        ToggleSwitch(autoscroll_row, self._log_autoscroll, bg=theme.SURFACE_2).pack(
            side=tk.LEFT
        )
        self._log = scrolledtext.ScrolledText(
            log_pad,
            height=18,
            state=tk.DISABLED,
            wrap=tk.WORD,
            font=ui_font(10),
            bg=theme.LOG_BG,
            fg=theme.LOG_FG,
            insertbackground=theme.LOG_FG,
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=0,
            padx=12,
            pady=10,
        )
        self._log.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        self._configure_log_tags()
        self._refresh_home_status()

    def _refresh_home_status(self) -> None:
        """Update the ADB offline banner and Get-started checklist visibility/text."""
        if self._adb_banner is None or self._onboarding_frame is None or self._home_anchor is None:
            return
        try:
            config = load_config()
        except Exception:  # noqa: BLE001
            config = None
        adb_ok = self._last_adb_ok is True
        calib_ok = bool(config.calibrated) if config is not None else False

        try:
            if self._last_adb_ok is False:
                if not self._adb_banner.winfo_ismapped():
                    self._adb_banner.pack(fill=tk.X, pady=(0, 12), before=self._home_anchor)
            else:
                self._adb_banner.pack_forget()
        except tk.TclError:
            pass

        self._onboarding_checklist_var.set(
            f"{'✓' if adb_ok else '✗'}  ADB connected\n"
            f"{'✓' if calib_ok else '✗'}  Required calibration (Setup)\n"
            "•  Farm attacks are optional — set them up any time in Setup → Farm"
        )
        show_onboarding = not self._gui_state.onboarding_dismissed
        try:
            if show_onboarding:
                if not self._onboarding_frame.winfo_ismapped():
                    self._onboarding_frame.pack(fill=tk.X, pady=(0, 12), before=self._home_anchor)
            else:
                self._onboarding_frame.pack_forget()
        except tk.TclError:
            pass

    def _dismiss_onboarding(self) -> None:
        self._gui_state.onboarding_dismissed = True
        self._save_gui_state()
        self._refresh_home_status()

    def _copy_logs(self) -> None:
        text = "\n".join(self._log_lines)
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
        except tk.TclError as exc:
            messagebox.showerror("Copy failed", str(exc))
            return
        self._append_log(f"==> Copied {len(self._log_lines)} log line(s) to clipboard")

    def _export_debug(self) -> None:
        try:
            out_dir = export_debug_bundle(self._log_lines)
        except OSError as exc:
            messagebox.showerror("Export failed", str(exc))
            return
        self._append_log(f"==> Exported debug bundle to {out_dir}")
        messagebox.showinfo("Debug bundle exported", f"Saved to:\n{out_dir}")

    def connect_adb(self) -> None:
        self._append_log("==> Connecting to ADB…")

        def worker() -> None:
            try:
                from coc_bot.adb.client import AdbClient

                config = load_config()
                ok = AdbClient(device=config.adb_device).connect()
            except Exception as exc:  # noqa: BLE001
                logger.warning("ADB connect failed: {}", exc)
                ok = False

            def done() -> None:
                self._set_adb_status(ok)
                if ok:
                    self._append_log("==> ADB connected")
                    notify("ADB connected", "The bot can see your device again.")
                else:
                    self._append_log("==> ADB connect failed")
                    notify("ADB connect failed", "Check Waydroid/emulator and try again.")

            self.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    def _build_settings_page(self) -> None:
        page = self._pages["settings"]
        for child in page.winfo_children():
            child.destroy()
        self._setting_vars.clear()
        self._setting_hint_labels.clear()
        self._clear_wrap_labels("settings")

        footer = tk.Frame(page, bg=theme.BG)
        footer.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=(8, 12))
        ttk.Button(
            footer,
            text="Reload",
            style=self._btn_style("Secondary"),
            command=self._reload_settings_fields,
        ).pack(side=tk.LEFT)
        ttk.Button(
            footer,
            text="Save Settings",
            style=self._btn_style("Accent"),
            command=self._save_settings,
        ).pack(side=tk.LEFT, padx=(8, 0))

        canvas, inner = make_scrollable(page)
        self._settings_canvas = canvas

        intro = tk.Frame(inner, bg=theme.BG)
        intro.pack(fill=tk.X, padx=8, pady=(4, 4))
        intro_label = tk.Label(
            intro,
            text="Changes are saved to data/user_settings.yaml. Stop and Start the bot "
            "after saving so a running loop picks them up. Theme under Interface "
            f"is currently {theme_label(self._theme_id)}.",
            bg=theme.BG,
            fg=theme.TEXT_SECONDARY,
            font=ui_font(10),
            wraplength=400,
            justify=tk.LEFT,
            anchor="w",
        )
        intro_label.pack(fill=tk.X, pady=(0, 8))
        self._track_wrap_label(intro_label, reserve=40, page_id="settings")

        values = current_setting_values()
        dev = bool(values.get("gui_dev_options", False))
        current_section = None
        section_body: tk.Frame | None = None
        for field in SETTINGS:
            if is_raw_timing_field(field.key) and not dev:
                continue
            if field.section != current_section:
                current_section = field.section
                section_body = self._section_header(
                    inner,
                    f"settings:{current_section}",
                    current_section,
                )

            assert section_body is not None
            if self._modern:
                self._add_setting_row_modern(section_body, field, values[field.key])
            else:
                self._add_setting_row_classic(section_body, field, values[field.key])

        finish_scrollable(inner, canvas)
        self.after_idle(self._sync_wrap_lengths)

    def _attach_setting_hint(
        self, parent: tk.Misc, field, var: tk.Variable, *, side: str
    ) -> None:
        """Small secondary hint (e.g. "≈ 4h") that follows a timing/ms field's value."""
        if field.kind not in ("int", "float", "str"):
            return
        hint = tk.Label(
            parent,
            text="",
            bg=theme.SURFACE_2,
            fg=theme.TEXT_SECONDARY,
            font=ui_font(9),
            anchor="w",
        )
        if side == "right":
            hint.pack(side=tk.LEFT, padx=(6, 0))
        else:
            hint.pack(anchor=tk.W, pady=(2, 0))
        self._setting_hint_labels[field.key] = hint

        def _update(*_args) -> None:
            try:
                if not hint.winfo_exists():
                    return
                hint.configure(text=humanize_setting_value(field.key, var.get()) or "")
            except tk.TclError:
                pass

        var.trace_add("write", _update)
        _update()

    def _add_setting_row_classic(self, parent: tk.Misc, field, value) -> None:
        """Original stacked card: label → description → control."""
        card = self._card(parent, padx=8, pady=5)
        block = tk.Frame(card, bg=theme.SURFACE_2)
        block.pack(fill=tk.X, padx=14, pady=12)

        tk.Label(
            block,
            text=field.label,
            bg=theme.SURFACE_2,
            fg=theme.TEXT,
            font=ui_font(11, "bold"),
            anchor="w",
        ).pack(fill=tk.X)
        desc = tk.Label(
            block,
            text=field.description,
            bg=theme.SURFACE_2,
            fg=theme.TEXT_SECONDARY,
            font=ui_font(10),
            wraplength=400,
            justify=tk.LEFT,
            anchor="w",
        )
        desc.pack(fill=tk.X, pady=(4, 8))
        # Card padding + scrollbar.
        self._track_wrap_label(desc, reserve=56, page_id="settings")

        if field.kind == "bool":
            var: tk.Variable = tk.BooleanVar(value=bool(value))
            ttk.Checkbutton(block, text="Enabled", variable=var).pack(anchor=tk.W)
            self._setting_vars[field.key] = var
        elif field.kind == "choice":
            var = tk.StringVar(value=str(value))
            box = ttk.Combobox(
                block,
                textvariable=var,
                values=list(field.choices),
                state="readonly",
                width=20,
            )
            box.pack(anchor=tk.W)
            self._setting_vars[field.key] = var
        else:
            var = tk.StringVar(value=str(value))
            entry = ttk.Entry(block, textvariable=var, width=42)
            entry.pack(anchor=tk.W, ipady=2)
            self._setting_vars[field.key] = var
            self._attach_setting_hint(block, field, var, side="below")

    def _add_setting_row_modern(self, parent: tk.Misc, field, value) -> None:
        """Cursor-like row: title/description left, control right."""
        card = self._card(parent, padx=8, pady=4)
        block = tk.Frame(card, bg=theme.SURFACE_2)
        block.pack(fill=tk.X, padx=16, pady=14)
        block.columnconfigure(0, weight=1)
        block.columnconfigure(1, weight=0)

        left = tk.Frame(block, bg=theme.SURFACE_2)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 16))

        title = tk.Label(
            left,
            text=field.label,
            bg=theme.SURFACE_2,
            fg=theme.TEXT,
            font=ui_font(12),
            anchor="w",
            justify=tk.LEFT,
            wraplength=200,
        )
        title.pack(anchor=tk.W)
        desc = tk.Label(
            left,
            text=field.description,
            bg=theme.SURFACE_2,
            fg=theme.TEXT_SECONDARY,
            font=ui_font(10),
            wraplength=200,
            justify=tk.LEFT,
            anchor="w",
        )
        desc.pack(anchor=tk.W, pady=(4, 0))

        right = tk.Frame(block, bg=theme.SURFACE_2)
        right.grid(row=0, column=1, sticky="ne")

        if field.kind == "bool":
            var = tk.BooleanVar(value=bool(value))
            ToggleSwitch(right, var, bg=theme.SURFACE_2).pack(anchor=tk.E, pady=(2, 0))
            self._setting_vars[field.key] = var
        elif field.kind == "choice":
            var = tk.StringVar(value=str(value))
            box = ttk.Combobox(
                right,
                textvariable=var,
                values=list(field.choices),
                state="readonly",
                width=14,
                style="Modern.TCombobox",
                justify=tk.RIGHT,
            )
            box.pack(anchor=tk.E)
            self._setting_vars[field.key] = var
        else:
            var = tk.StringVar(value=str(value))
            width = 12 if field.kind in ("int", "float") else 18
            control_row = tk.Frame(right, bg=theme.SURFACE_2)
            control_row.pack(anchor=tk.E)
            entry = ttk.Entry(
                control_row,
                textvariable=var,
                width=width,
                style="Modern.TEntry",
                justify=tk.RIGHT,
            )
            entry.pack(side=tk.LEFT)
            self._setting_vars[field.key] = var
            self._attach_setting_hint(control_row, field, var, side="right")

        self._bind_modern_row_wrap([title, desc], block, right, gap=20)

    def _reload_settings_fields(self) -> None:
        values = current_setting_values()
        for field in SETTINGS:
            var = self._setting_vars.get(field.key)
            if var is None:
                continue
            if field.kind == "bool":
                var.set(bool(values[field.key]))
            else:
                var.set(str(values[field.key]))
        self._append_log("==> Settings reloaded from disk")
        self._install_log_sink()

    def _save_settings(self) -> None:
        previous_theme = self._theme_id
        previous_dev = load_config().gui_dev_options
        try:
            values: dict[str, str | bool] = {}
            current = current_setting_values()
            for field in SETTINGS:
                var = self._setting_vars.get(field.key)
                if var is None:
                    # Hidden field (e.g. raw timing while Dev options is off) — keep as-is.
                    values[field.key] = current[field.key]
                    continue
                values[field.key] = bool(var.get()) if field.kind == "bool" else str(var.get())
            save_settings_from_gui(values)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Invalid settings", str(exc))
            return
        path = user_settings_path()
        self._install_log_sink()
        self._append_log(f"==> Settings saved to {path}")

        new_theme = normalize_theme_id(values.get("gui_theme", previous_theme))
        theme_changed = new_theme != previous_theme
        new_dev = bool(values.get("gui_dev_options", previous_dev))
        dev_changed = new_dev != previous_dev
        if theme_changed:
            self._apply_theme_id(new_theme)
            self._append_log(f"==> Theme → {theme_label(new_theme)}")
        elif dev_changed:
            self._build_settings_page()
            self._append_log(
                f"==> Dev options {'enabled' if new_dev else 'disabled'} — settings refreshed"
            )

        extra = ""
        if theme_changed:
            extra = f"\n\nTheme switched to {theme_label(new_theme)}."
        messagebox.showinfo(
            "Saved",
            f"Settings saved to:\n{path}\n\nStop and Start the bot to apply them to a running loop.\n"
            f"Activity log DEBUG filter applies immediately.{extra}",
        )

    def _build_setup_page(self) -> None:
        page = self._pages["setup"]
        tk.Label(
            page,
            text="Calibration teaches the bot where buttons and bars are on your screen. "
            "Select a step or part, then Recalibrate Selected — taps, ROIs, and templates "
            "open an in-app picker. Slot colors / grid use Classic terminal calibrator. "
            "Open Waydroid and Clash first. Farm deploy: Farm → Deploy tap sequence "
            "(be in battle first).",
            bg=theme.BG,
            fg=theme.TEXT_SECONDARY,
            font=ui_font(10),
            wraplength=720,
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X, pady=(0, 12))

        tk.Label(
            page,
            textvariable=self._calib_progress,
            bg=theme.BG,
            fg=theme.ACCENT,
            font=ui_font(11, "bold"),
            anchor="w",
        ).pack(fill=tk.X, pady=(0, 8))

        card = self._card(page, pady=(0, 10))
        tree_wrap = tk.Frame(card, bg=theme.SURFACE_2)
        tree_wrap.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        cols = ("item", "status")
        self._calib_tree = ttk.Treeview(
            tree_wrap,
            columns=cols,
            show="tree headings",
            height=14,
            selectmode="browse",
        )
        self._calib_tree.heading("#0", text="Step / part")
        self._calib_tree.heading("item", text="Key")
        self._calib_tree.heading("status", text="Status")
        self._calib_tree.column("#0", width=320, stretch=True)
        self._calib_tree.column("item", width=160, stretch=False)
        self._calib_tree.column("status", width=110, stretch=False)
        scroll = ttk.Scrollbar(tree_wrap, orient=tk.VERTICAL, command=self._calib_tree.yview)
        self._calib_tree.configure(yscrollcommand=scroll.set)
        self._calib_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        row = tk.Frame(page, bg=theme.BG)
        row.pack(fill=tk.X, pady=(4, 0))
        ttk.Button(
            row,
            text="Refresh",
            style=self._btn_style("Secondary"),
            command=self._refresh_calib_status,
        ).pack(side=tk.LEFT)
        ttk.Button(
            row,
            text="Recalibrate Selected",
            style=self._btn_style("Secondary"),
            command=self._recalibrate_selected,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            row,
            text="Recalibrate All",
            style=self._btn_style("Accent"),
            command=self._recalibrate_all,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            row,
            text="Classic terminal calibrator",
            style=self._btn_style("Secondary"),
            command=self._classic_calibrate_selected,
        ).pack(side=tk.LEFT, padx=(8, 0))

        row2 = tk.Frame(page, bg=theme.BG)
        row2.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(
            row2,
            text="Backup calibration",
            style=self._btn_style("Secondary"),
            command=self._backup_calibration,
        ).pack(side=tk.LEFT)
        ttk.Button(
            row2,
            text="Restore calibration",
            style=self._btn_style("Secondary"),
            command=self._restore_calibration,
        ).pack(side=tk.LEFT, padx=(8, 0))

        self._calib_detail = tk.StringVar(value="")
        calib_detail = tk.Label(
            page,
            textvariable=self._calib_detail,
            bg=theme.BG,
            fg=theme.TEXT_SECONDARY,
            font=ui_font(10),
            wraplength=400,
            justify=tk.LEFT,
            anchor="w",
        )
        calib_detail.pack(fill=tk.X, pady=(12, 0))
        self._track_wrap_label(calib_detail, reserve=40, page_id="setup")
        self._calib_tree.bind("<<TreeviewSelect>>", self._on_calib_select)

    def _build_tools_page(self) -> None:
        page = self._pages["tools"]
        for child in page.winfo_children():
            child.destroy()
        self._clear_wrap_labels("tools")
        self._tool_buttons.clear()
        canvas, inner = make_scrollable(page)
        self._tools_canvas = canvas

        intro = tk.Frame(inner, bg=theme.BG)
        intro.pack(fill=tk.X, padx=8, pady=(4, 4))
        intro_label = tk.Label(
            intro,
            text="Run one test at a time. Stop the bot first so tests do not conflict. "
            "Results also appear in the Home activity log.",
            bg=theme.BG,
            fg=theme.TEXT_SECONDARY,
            font=ui_font(10),
            wraplength=400,
            justify=tk.LEFT,
            anchor="w",
        )
        intro_label.pack(fill=tk.X, pady=(0, 8))
        self._track_wrap_label(intro_label, reserve=40, page_id="tools")

        for group_title, actions in DEBUG_GROUPS:
            body = self._section_header(inner, f"tools:{group_title}", group_title)

            for action_id, label, description in actions:
                card = self._card(body, padx=8, pady=4 if self._modern else 5)
                block = tk.Frame(card, bg=theme.SURFACE_2)
                block.pack(fill=tk.X, padx=14, pady=12)
                if self._modern:
                    block.columnconfigure(0, weight=1)
                    left = tk.Frame(block, bg=theme.SURFACE_2)
                    left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
                    tk.Label(
                        left,
                        text=label,
                        bg=theme.SURFACE_2,
                        fg=theme.TEXT,
                        font=ui_font(12),
                        anchor="w",
                    ).pack(fill=tk.X)
                    desc = tk.Label(
                        left,
                        text=description,
                        bg=theme.SURFACE_2,
                        fg=theme.TEXT_SECONDARY,
                        font=ui_font(10),
                        wraplength=320,
                        justify=tk.LEFT,
                        anchor="w",
                    )
                    desc.pack(fill=tk.X, pady=(4, 0))
                    self._track_wrap_label(desc, reserve=180, page_id="tools")
                    run_btn = ttk.Button(
                        block,
                        text="Run",
                        style=self._btn_style("Secondary"),
                        command=lambda aid=action_id: self._run_debug(aid),
                    )
                    run_btn.grid(row=0, column=1, sticky="ne")
                else:
                    run_btn = ttk.Button(
                        block,
                        text=label,
                        style=self._btn_style("Secondary"),
                        command=lambda aid=action_id: self._run_debug(aid),
                    )
                    run_btn.pack(anchor=tk.W)
                    desc = tk.Label(
                        block,
                        text=description,
                        bg=theme.SURFACE_2,
                        fg=theme.TEXT_SECONDARY,
                        font=ui_font(10),
                        wraplength=400,
                        justify=tk.LEFT,
                        anchor="w",
                    )
                    desc.pack(fill=tk.X, pady=(8, 0))
                    self._track_wrap_label(desc, reserve=56, page_id="tools")
                self._tool_buttons.append(run_btn)

        self._debug_result = tk.StringVar(value="")
        result_label = tk.Label(
            inner,
            textvariable=self._debug_result,
            bg=theme.BG,
            fg=theme.ACCENT,
            font=ui_font(11),
            wraplength=400,
            justify=tk.LEFT,
            anchor="w",
        )
        result_label.pack(fill=tk.X, padx=8, pady=(12, 24))
        self._track_wrap_label(result_label, reserve=40, page_id="tools")

        finish_scrollable(inner, canvas)
        self.after_idle(self._sync_wrap_lengths)
        self._update_tool_buttons_state()

    def _run_debug(self, action_id: str) -> None:
        if self._bot_running():
            messagebox.showwarning(
                "Bot running",
                "Stop the bot before running tools so they do not conflict.",
            )
            return
        if self._debug_busy:
            return
        self._set_debug_busy(True)
        self._debug_result.set(f"Running {action_id}…")
        self._append_log(f"==> Tool: {action_id}")

        # Click editor needs the Tk UI thread — pan on a worker, then open here.
        if action_id == "farm_program_deploy":
            self._run_farm_program_deploy_tool()
            return

        def worker() -> None:
            result = run_debug_action(action_id)
            logger.info("Tool {}: {}", action_id, result)

            def done() -> None:
                self._set_debug_busy(False)
                self._debug_result.set(result)
                self._append_log(result)

            self.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    def _set_debug_busy(self, busy: bool) -> None:
        self._debug_busy = busy
        self._update_tool_buttons_state()

    def _update_tool_buttons_state(self) -> None:
        disabled = self._debug_busy or self._bot_running()
        state = tk.DISABLED if disabled else tk.NORMAL
        for btn in self._tool_buttons:
            try:
                if btn.winfo_exists():
                    btn.configure(state=state)
            except tk.TclError:
                continue

    def _run_farm_program_deploy_tool(self) -> None:
        """Pan via ADB off-thread, then open the sequence editor on the UI thread."""

        def worker() -> None:
            try:
                session = DebugSession()
                prep = session.prepare_farm_program_deploy()
            except Exception as exc:  # noqa: BLE001
                logger.exception("Farm program deploy prepare failed")

                def fail() -> None:
                    self._set_debug_busy(False)
                    msg = f"Error preparing farm deploy editor: {exc}"
                    self._debug_result.set(msg)
                    self._append_log(msg)

                self.after(0, fail)
                return

            def open_editor() -> None:
                try:
                    result = session.finish_farm_program_deploy(prep, master=self)
                    logger.info("Tool farm_program_deploy: {}", result)
                    self._debug_result.set(result)
                    self._append_log(result)
                    self._refresh_calib_status()
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Farm program deploy editor failed")
                    msg = f"Error opening farm deploy editor: {exc}"
                    self._debug_result.set(msg)
                    self._append_log(msg)
                    messagebox.showerror("Farm deploy editor", msg)
                finally:
                    self._set_debug_busy(False)

            self.after(0, open_editor)

        threading.Thread(target=worker, daemon=True).start()

    def _install_log_sink(self) -> None:
        if self._log_sink_id is not None:
            try:
                logger.remove(self._log_sink_id)
            except ValueError:
                pass
            self._log_sink_id = None

        show_debug = bool(load_config().gui_show_debug_activity)
        level = "DEBUG" if show_debug else "INFO"

        def sink(message: str) -> None:
            self.after(0, lambda m=message: self._append_log(m.rstrip()))

        self._log_sink_id = logger.add(
            sink,
            level=level,
            format="{time:HH:mm:ss} | {level:<7} | {message}",
        )

    def _configure_log_tags(self) -> None:
        self._log.tag_configure("DEBUG", foreground=theme.TEXT_SECONDARY)
        self._log.tag_configure("INFO", foreground=theme.LOG_FG)
        self._log.tag_configure("WARNING", foreground=theme.ACCENT)
        self._log.tag_configure("ERROR", foreground=theme.DANGER)
        self._log.tag_configure("CRITICAL", foreground=theme.DANGER, font=ui_font(10, "bold"))
        self._log.tag_configure("META", foreground=theme.ACCENT, font=ui_font(10, "bold"))

    def _append_log(self, line: str) -> None:
        self._log_lines.append(line)
        if len(self._log_lines) > 2000:
            del self._log_lines[: len(self._log_lines) - 2000]

        stripped = line.strip()
        tag = None
        match = _LOG_LINE_RE.match(stripped)
        if match:
            level = match.group(2).strip().upper()
            message = match.group(3)
            if message.startswith("==>"):
                tag = "META"
            elif level in _LOG_LEVEL_TAGS:
                tag = level
        elif stripped.startswith("==>"):
            tag = "META"

        self._log.configure(state=tk.NORMAL)
        if tag:
            self._log.insert(tk.END, line + "\n", tag)
        else:
            self._log.insert(tk.END, line + "\n")
        self._cap_log_length()
        if self._log_autoscroll.get():
            self._log.see(tk.END)
        self._log.configure(state=tk.DISABLED)

    def _cap_log_length(self, max_lines: int = 2000) -> None:
        try:
            line_count = int(self._log.index("end-1c").split(".")[0])
        except (tk.TclError, ValueError):
            return
        if line_count > max_lines:
            excess = line_count - max_lines
            self._log.delete("1.0", f"{excess + 1}.0")

    def _bot_running(self) -> bool:
        return self._bot_thread is not None and self._bot_thread.is_alive()

    def _farm_oneshot_running(self) -> bool:
        return self._farm_oneshot_thread is not None and self._farm_oneshot_thread.is_alive()

    def start_bot(self) -> None:
        if self._bot_running():
            return
        if self._farm_oneshot_running():
            messagebox.showinfo(
                "Farm in progress",
                "A one-shot farm attack is running. Press Stop first, or wait for it to finish.",
            )
            return
        self._farm_timer_frozen_text = None
        config = load_config()
        if not config.calibrated:
            messagebox.showerror(
                "Not calibrated",
                "Setup is incomplete. Open Setup in the sidebar and run the missing steps.",
            )
            notify("Start blocked", "Required calibration is incomplete — open Setup.")
            self._gui_state.onboarding_dismissed = False
            self._save_gui_state()
            self._refresh_home_status()
            self._show_page("setup")
            self._refresh_calib_status()
            return

        self._start_btn.configure(state=tk.DISABLED)
        self._stop_btn.configure(state=tk.NORMAL)
        self._status.set("Bot running")
        self._append_log("==> Starting bot")
        self._sync_run_chip()
        self._update_tool_buttons_state()

        def worker() -> None:
            try:
                from coc_bot.main import DonationBot

                self._bot = DonationBot(
                    dry_run=self._dry_run,
                    debug_save_frames=self._debug_save_frames,
                    debug=self._debug,
                )
                self.after(0, lambda: self._status.set("Bot running"))
                self.after(0, self._sync_run_chip)
                self._bot.run()
            except Exception as exc:  # noqa: BLE001
                logger.exception("Bot failed: {}", exc)
                self.after(0, lambda: messagebox.showerror("Bot error", str(exc)))
            finally:
                self._bot = None
                self.after(0, self._on_bot_stopped)

        self._bot_thread = threading.Thread(target=worker, name="donation-bot", daemon=True)
        self._bot_thread.start()

    def stop_bot(self) -> None:
        stopped_something = False
        if self._farm_oneshot_running():
            self._farm_oneshot_stop.set()
            self._status.set("Stopping farm…")
            self._append_log("==> Stop requested (farm one-shot — Clash stays open)")
            stopped_something = True
        bot = self._bot
        if self._bot_running() and bot is not None:
            self._status.set("Stopping…")
            self._append_log("==> Stop requested (Clash stays open)")
            bot.request_stop()
            stopped_something = True
        if not stopped_something:
            self._on_bot_stopped()

    def request_farm_attack(self) -> None:
        """Queue a farm attack on the running bot, or run a one-shot if stopped."""
        config = load_config()
        if not config.farm_calibrated:
            messagebox.showerror(
                "Farm not calibrated",
                "Open Setup → Farm and set attack_button, unranked Battle, and Return Home.\n"
                "Leave your farm army as the active preset, and program a deploy sequence.",
            )
            self._show_page("setup")
            return

        bot = self._bot
        if self._bot_running() and bot is not None:
            bot.request_farm_attack()
            self._append_log("==> Farm attack queued (runs when not mid-donation)")
            self._farm_timer_var.set("due")
            self._sync_run_chip()
            return

        if self._farm_oneshot_running():
            messagebox.showinfo(
                "Farm in progress",
                "A farm attack is already running. Press Stop to cancel it.",
            )
            return

        if not messagebox.askyesno(
            "Farm attack now",
            "Bot is not running. Run one unranked farm attack now?\n\n"
            "This will leave chat, Attack → Battle, deploy along the edge, "
            "and wait for the timer to end.\n\n"
            "You can press Stop to cancel.",
        ):
            return

        self._farm_oneshot_stop.clear()
        self._start_btn.configure(state=tk.DISABLED)
        self._stop_btn.configure(state=tk.NORMAL)
        self._status.set("Farm one-shot running…")
        self._append_log("==> Running one-shot farm attack…")
        self._farm_timer_var.set("running")
        self._sync_run_chip()

        def worker() -> None:
            try:
                success, msg = DebugSession().farm_one_shot(
                    should_stop=self._farm_oneshot_stop.is_set
                )
                logger.info(msg)

                def done() -> None:
                    self._append_log(msg)
                    was_stopped = self._farm_oneshot_stop.is_set()
                    self._on_farm_oneshot_done()
                    if was_stopped:
                        messagebox.showinfo("Farm", "Farm attack stopped.")
                    elif success:
                        messagebox.showinfo("Farm", "Farm attack finished.")
                    else:
                        messagebox.showwarning("Farm", msg)

                self.after(0, done)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Farm one-shot failed")

                def fail() -> None:
                    messagebox.showerror("Farm error", str(exc))
                    self._on_farm_oneshot_done()

                self.after(0, fail)

        self._farm_oneshot_thread = threading.Thread(
            target=worker, name="farm-oneshot", daemon=True
        )
        self._farm_oneshot_thread.start()

    def _on_farm_oneshot_done(self) -> None:
        self._farm_oneshot_thread = None
        self._farm_oneshot_stop.clear()
        if not self._bot_running():
            self._on_bot_stopped()
        self._sync_run_chip()
        self._refresh_farm_status()

    def _farm_timer_text(self) -> str:
        if self._farm_oneshot_running():
            self._farm_timer_frozen_text = None
            return "running"
        config = load_config()
        if not config.farm_enabled:
            self._farm_timer_frozen_text = None
            return "off"
        if not config.farm_calibrated:
            self._farm_timer_frozen_text = None
            return "—"
        from coc_bot.config import normalize_farm_deploy_sequence

        if not normalize_farm_deploy_sequence(config.farm_deploy_sequence).get("taps"):
            self._farm_timer_frozen_text = None
            return "—"

        bot = self._bot
        running = self._bot_running() and bot is not None
        if running:
            self._farm_timer_frozen_text = None
            if getattr(bot, "farm_queued", False):
                return "due"
            tracker = bot.tracker
        else:
            # Auto-farm does not run while stopped — freeze the display so it
            # does not keep counting down from wall-clock time.
            if self._farm_timer_frozen_text is not None:
                return self._farm_timer_frozen_text
            from coc_bot.runtime.tracker import RuntimeTracker

            tracker = RuntimeTracker(config)

        since = tracker.seconds_since_last_farm()
        interval = tracker.effective_farm_interval_seconds()
        if since is None:
            text = "due"
        else:
            remaining = max(0.0, interval - since)
            text = "due" if remaining <= 0 else format_countdown(remaining)

        if not running:
            if text != "due":
                text = f"{text} · paused"
            self._farm_timer_frozen_text = text
        return text

    def _break_timer_text(self) -> str:
        bot = self._bot
        if self._bot_running() and bot is not None:
            tracker = bot.tracker
        else:
            from coc_bot.runtime.tracker import RuntimeTracker

            tracker = RuntimeTracker(load_config())

        if tracker.state.break_until:
            try:
                from datetime import datetime, timezone

                until = datetime.fromisoformat(tracker.state.break_until)
                if until.tzinfo is None:
                    until = until.replace(tzinfo=timezone.utc)
                left = (until - datetime.now(timezone.utc)).total_seconds()
                if left > 0:
                    # Time remaining until the break ends / bot resumes.
                    return format_countdown(left)
            except ValueError:
                pass

        remaining = tracker.remaining_seconds()
        if remaining <= 0:
            return "due"
        return format_countdown(remaining)

    def _refresh_farm_status(self) -> None:
        try:
            self._farm_timer_var.set(self._farm_timer_text())
        except Exception:  # noqa: BLE001
            self._farm_timer_var.set("—")
        try:
            self._break_timer_var.set(self._break_timer_text())
        except Exception:  # noqa: BLE001
            self._break_timer_var.set("—")
        self._sync_run_chip()
        self.after(2000, self._refresh_farm_status)

    def _sync_run_chip(self) -> None:
        if not hasattr(self, "_run_chip"):
            return
        if self._farm_oneshot_running():
            self._set_run_chip("Farming…", "accent")
            return

        # Pending/active session break (even if the process was restarted mid-break).
        try:
            bot = self._bot
            if self._bot_running() and bot is not None:
                tracker = bot.tracker
            else:
                from coc_bot.runtime.tracker import RuntimeTracker

                tracker = RuntimeTracker(load_config())
            if tracker.state.break_until:
                from datetime import datetime, timezone

                until = datetime.fromisoformat(tracker.state.break_until)
                if until.tzinfo is None:
                    until = until.replace(tzinfo=timezone.utc)
                if (until - datetime.now(timezone.utc)).total_seconds() > 0:
                    self._set_run_chip("On break", "accent")
                    return
        except Exception:  # noqa: BLE001
            pass

        bot = self._bot
        if self._bot_running() and bot is not None:
            try:
                from coc_bot.runtime.game_state import GameState

                state = bot.game_state.state
                if state == GameState.ON_BREAK:
                    self._set_run_chip("On break", "accent")
                    return
                if state in (
                    GameState.ATTACK_MENU,
                    GameState.MATCHMAKING,
                    GameState.IN_BATTLE,
                    GameState.BATTLE_RESULTS,
                    GameState.RETURNING_HOME,
                ):
                    self._set_run_chip("Farming…", "accent")
                    return
            except Exception:  # noqa: BLE001
                pass
            self._set_run_chip("Running", "success")
            return
        self._set_run_chip("Stopped", "secondary")

    def _set_run_chip(self, text: str, role: str) -> None:
        self._run_chip_var.set(text)
        color = {
            "secondary": theme.TEXT_SECONDARY,
            "success": theme.SUCCESS,
            "accent": theme.ACCENT,
        }.get(role, theme.TEXT_SECONDARY)
        try:
            if self._run_chip.winfo_exists():
                self._run_chip.configure(fg=color)
        except tk.TclError:
            pass

    def view_bot_screenshot(self) -> None:
        """Grab one ADB frame (what the bot sees) and show it in a preview window."""
        self._append_log("==> Requesting screenshot…")

        def worker() -> None:
            try:
                import cv2
                from PIL import Image, ImageTk

                from coc_bot.adb.capture import ScreenCapture
                from coc_bot.adb.client import AdbClient

                config = load_config()
                client = AdbClient(device=config.adb_device)
                client.ensure_connected()
                frame = ScreenCapture(client).screenshot()
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image = Image.fromarray(rgb)
                image.thumbnail((960, 540), Image.Resampling.LANCZOS)
                h, w = frame.shape[:2]

                def show() -> None:
                    win = tk.Toplevel(self)
                    win.title(f"Bot view — {w}×{h}")
                    win.configure(bg=theme.BG)
                    photo = ImageTk.PhotoImage(image)
                    win._photo = photo  # type: ignore[attr-defined]
                    tk.Label(
                        win,
                        text="Current ADB screencap (same source the bot uses)",
                        bg=theme.BG,
                        fg=theme.TEXT_SECONDARY,
                        font=ui_font(10),
                    ).pack(anchor=tk.W, padx=16, pady=(12, 4))
                    tk.Label(win, image=photo, bg=theme.BG, bd=0).pack(padx=16, pady=(0, 16))
                    self._append_log(f"==> Screenshot preview {w}×{h}")

                self.after(0, show)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Screenshot preview failed: {}", exc)
                self.after(0, lambda: messagebox.showerror("Screenshot failed", str(exc)))
                self.after(0, lambda: self._append_log(f"Screenshot failed: {exc}"))

        threading.Thread(target=worker, daemon=True).start()

    def _on_bot_stopped(self) -> None:
        was_running = self._bot_thread is not None
        self._status.set("Ready — open Waydroid and Clash of Clans, then press Start")
        self._start_btn.configure(state=tk.NORMAL)
        self._stop_btn.configure(state=tk.DISABLED)
        self._bot_thread = None
        # Capture a frozen farm countdown for the stopped state (refreshed once).
        self._farm_timer_frozen_text = None
        try:
            self._farm_timer_var.set(self._farm_timer_text())
        except Exception:  # noqa: BLE001
            pass
        self._sync_run_chip()
        self._update_tool_buttons_state()
        self._refresh_home_status()
        if was_running:
            notify("Bot stopped", "The bot loop is no longer running.")

    def close_waydroid_and_coc(self) -> None:
        if not messagebox.askyesno(
            "Close Waydroid + Clash",
            "Stop the bot (if running), force-stop Clash of Clans, and stop the Waydroid session?",
        ):
            return
        self.stop_bot()
        self._append_log("==> Closing Clash of Clans and Waydroid session")
        threading.Thread(target=self._close_waydroid_worker, daemon=True).start()

    def _close_waydroid_worker(self) -> None:
        config = load_config()
        device = config.adb_device
        pkg = config.coc_package
        env = os.environ.copy()
        env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:" + env.get(
            "PATH", ""
        )
        try:
            subprocess.run(  # noqa: S603
                ["adb", "-s", device, "shell", f"am force-stop {pkg}"],
                check=False,
                env=env,
                timeout=20,
            )
            logger.info("Force-stopped {}", pkg)
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("Could not force-stop CoC: {}", exc)
        try:
            subprocess.run(  # noqa: S603
                ["waydroid", "session", "stop"],
                check=False,
                env=env,
                timeout=60,
            )
            logger.info("Waydroid session stop requested")
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("Could not stop Waydroid session: {}", exc)
        self.after(0, lambda: self._status.set("Waydroid / Clash close requested"))

    def _refresh_calib_status(self) -> None:
        for item in self._calib_tree.get_children():
            self._calib_tree.delete(item)
        try:
            config = load_config()
            wizard = CalibrationWizard(config)
            status = wizard.step_status()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not load calibration status: {}", exc)
            config = load_config()
            status = {sid: False for sid in STEP_IDS}

        done = 0
        for step_id in STEP_IDS:
            step = STEPS[step_id]
            ok = bool(status.get(step_id))
            if ok:
                done += 1
            parent = self._calib_tree.insert(
                "",
                tk.END,
                iid=step_id,
                text=step.title,
                values=(step_id, "Done" if ok else "Missing"),
                open=True,
            )
            for part in step.parts:
                part_ok = part_is_configured(config, part)
                if part.optional and not part_ok:
                    part_status = "Optional"
                elif part_ok:
                    part_status = "Done"
                else:
                    part_status = "Missing"
                label = part.label
                if part.optional:
                    label = f"{label} (optional)"
                self._calib_tree.insert(
                    parent,
                    tk.END,
                    iid=f"{step_id}::{part.key}",
                    text=f"  · {label}",
                    values=(part.key, part_status),
                )
        total = len(STEP_IDS)
        self._calib_progress.set(f"Setup progress: {done} / {total} steps ready")
        self._refresh_home_status()
        self._calib_detail.set(
            f"{done}/{total} steps configured. Expand a step and select a part to "
            "recalibrate only that item (answer n at prompts to keep existing values)."
        )

    def _on_calib_select(self, _event=None) -> None:
        sel = self._calib_tree.selection()
        if not sel:
            return
        iid = sel[0]
        step_id = parent_step_id(iid)
        step = STEPS[step_id]
        if "::" in iid:
            part_key = iid.split("::", 1)[1]
            part = next((p for p in step.parts if p.key == part_key), None)
            if part is None:
                self._calib_detail.set(step.summary)
                return
            status = self._calib_tree.set(iid, "status")
            extra = f"\n{part.description}" if part.description else ""
            opt = " (optional)" if part.optional else ""
            if part_key == "deploy_sequence":
                how = (
                    "Recalibrate Selected opens the farm deploy click editor "
                    "(be on the battlefield first)."
                )
            else:
                how = (
                    f"Recalibrate Selected runs only “{part.label}” "
                    f"(not the whole “{step.title}” step)."
                )
            self._calib_detail.set(
                f"{step.title} → {part.label}{opt}\n"
                f"Status: {status} · key: {part.key} · type: {part.kind}{extra}\n\n"
                f"{how}"
            )
            return
        status = self._calib_tree.set(iid, "status")
        parts_line = ", ".join(p.label for p in step.parts) if step.parts else step.summary
        self._calib_detail.set(
            f"{step.title} — {status}\n{step.summary}\nParts: {parts_line}\n\n"
            "Recalibrate Selected runs this whole step (each item can still be denied)."
        )

    def _recalibrate_selected(self) -> None:
        sel = self._calib_tree.selection()
        if not sel:
            messagebox.showinfo("Select a step", "Select a setup step or part in the list first.")
            return
        iid = sel[0]
        step_id = parent_step_id(iid)
        step = STEPS[step_id]

        if "::" in iid:
            part_key = iid.split("::", 1)[1]
            if part_key == "deploy_sequence":
                if not messagebox.askyesno(
                    "Program farm deploy",
                    "Enter an unranked battle first, then continue.\n\n"
                    "The bot will pan and open the tap editor. Proceed?",
                ):
                    return
                self._run_debug("farm_program_deploy")
                return
            part = next((p for p in step.parts if p.key == part_key), None)
            if part is not None and part_supports_in_app(part):
                self._run_in_app_calibration(step_id, part_key)
                return
            self._launch_calibrate(["--step", step_id, "--part", part_key])
            return

        # Whole step selected — run in-app when every part supports it, else fall
        # back to the terminal wizard (meta/grid/color parts need it).
        in_app_parts = [p.key for p in step.parts if p.kind != "meta" and part_supports_in_app(p)]
        other_parts = [p for p in step.parts if p.kind == "meta" or not part_supports_in_app(p)]
        if step.parts and not other_parts:
            self._run_in_app_calibration_sequence(step_id, in_app_parts)
            return
        self._launch_calibrate(["--step", step_id])

    def _run_in_app_calibration(self, step_id: str, part_key: str) -> None:
        try:
            result = calibrate_part_in_app(self, step_id, part_key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("In-app calibration failed for {}::{}: {}", step_id, part_key, exc)
            self._append_log(f"Calibration cancelled/failed ({part_key}): {exc}")
            return
        self._append_log(f"==> {result}")
        self._refresh_calib_status()

    def _run_in_app_calibration_sequence(self, step_id: str, part_keys: list[str]) -> None:
        if not part_keys:
            return
        for part_key in part_keys:
            try:
                result = calibrate_part_in_app(self, step_id, part_key)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "In-app calibration failed for {}::{}: {}", step_id, part_key, exc
                )
                self._append_log(f"Calibration cancelled/failed ({part_key}): {exc}")
                continue
            self._append_log(f"==> {result}")
        self._refresh_calib_status()

    def _recalibrate_all(self) -> None:
        if not messagebox.askyesno(
            "Recalibrate all",
            "Run the full setup wizard in a new terminal? Existing values can be kept per prompt.",
        ):
            return
        self._launch_calibrate(["--all"])

    def _classic_calibrate_selected(self) -> None:
        """Open the classic terminal calibrator for the current selection (or --all)."""
        sel = self._calib_tree.selection()
        if not sel:
            self._launch_calibrate(["--all"])
            return
        iid = sel[0]
        step_id = parent_step_id(iid)
        if "::" in iid:
            part_key = iid.split("::", 1)[1]
            self._launch_calibrate(["--step", step_id, "--part", part_key])
            return
        self._launch_calibrate(["--step", step_id])

    def _backup_calibration(self) -> None:
        try:
            backup = create_backup()
        except FileNotFoundError:
            messagebox.showinfo(
                "Nothing to back up",
                "No calibrated.yaml or templates found yet.\n"
                "Finish Setup calibration first, then try again.",
            )
            return
        except OSError as exc:
            messagebox.showerror("Backup failed", str(exc))
            return
        self._append_log(f"==> Calibration backed up to {backup.path}")
        messagebox.showinfo(
            "Calibration backed up",
            f"Saved a snapshot of calibrated.yaml and templates to:\n\n{backup.path}",
        )

    def _restore_calibration(self) -> None:
        backups = list_backups()
        if not backups:
            messagebox.showinfo(
                "No backups",
                "No calibration backups found yet.\n"
                "Use Backup calibration first.",
            )
            return
        chosen = self._pick_calibration_backup(backups)
        if chosen is None:
            return
        if not messagebox.askyesno(
            "Restore calibration?",
            f"Replace the live calibration with snapshot:\n\n{chosen.stamp}\n\n"
            "Your current calibration will be auto-saved as a pre_restore_* "
            "backup first. The bot must be Stopped for a clean reload — "
            "Stop and Start after restoring if it is running.",
        ):
            return
        try:
            restore_backup(chosen)
        except (OSError, FileNotFoundError) as exc:
            messagebox.showerror("Restore failed", str(exc))
            return
        self._append_log(f"==> Calibration restored from {chosen.path}")
        self._refresh_calib_status()
        messagebox.showinfo(
            "Calibration restored",
            f"Restored from:\n{chosen.path}\n\n"
            "If the bot is running, Stop and Start so it reloads the files.",
        )

    def _pick_calibration_backup(
        self, backups: list[CalibrationBackup]
    ) -> CalibrationBackup | None:
        """Modal list picker; returns a CalibrationBackup or None if cancelled."""
        win = tk.Toplevel(self)
        win.title("Restore calibration")
        win.transient(self)
        win.grab_set()
        win.configure(bg=theme.BG)
        result: dict[str, CalibrationBackup | None] = {"value": None}

        tk.Label(
            win,
            text="Select a backup to restore (newest first):",
            bg=theme.BG,
            fg=theme.TEXT,
            font=ui_font(11),
            anchor="w",
        ).pack(fill=tk.X, padx=16, pady=(16, 8))

        frame = tk.Frame(win, bg=theme.BG)
        frame.pack(fill=tk.BOTH, expand=True, padx=16)
        listbox = tk.Listbox(
            frame,
            height=min(12, max(4, len(backups))),
            font=ui_font(10),
            bg=theme.SURFACE_2,
            fg=theme.TEXT,
            selectbackground=theme.ACCENT,
            activestyle="none",
            highlightthickness=0,
            borderwidth=0,
        )
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=listbox.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        listbox.configure(yscrollcommand=scroll.set)
        for item in backups:
            listbox.insert(tk.END, item.label)
        listbox.selection_set(0)

        btns = tk.Frame(win, bg=theme.BG)
        btns.pack(fill=tk.X, padx=16, pady=16)

        def accept() -> None:
            sel = listbox.curselection()
            if not sel:
                return
            result["value"] = backups[int(sel[0])]
            win.destroy()

        def cancel() -> None:
            result["value"] = None
            win.destroy()

        ttk.Button(
            btns, text="Cancel", style=self._btn_style("Secondary"), command=cancel
        ).pack(side=tk.RIGHT)
        ttk.Button(
            btns, text="Restore", style=self._btn_style("Accent"), command=accept
        ).pack(side=tk.RIGHT, padx=(0, 8))
        listbox.bind("<Double-Button-1>", lambda _e: accept())
        win.protocol("WM_DELETE_WINDOW", cancel)
        win.wait_window()
        return result["value"]

    def _launch_calibrate(self, extra_args: list[str]) -> None:
        script = calibrate_script()
        if not script.exists():
            messagebox.showerror("Missing script", f"Not found: {script}")
            return
        py = sys.executable
        cmd = (
            f"cd {shlex.quote(str(project_root()))} && {shlex.quote(py)} "
            f"{shlex.quote(str(script))} "
            + " ".join(shlex.quote(a) for a in extra_args)
        )
        self._append_log(f"==> Opening setup terminal: {' '.join(extra_args)}")
        if not open_in_terminal(cmd):
            messagebox.showerror(
                "No terminal",
                "Could not open a terminal emulator.\n"
                f"Run manually:\n{py} {script} {' '.join(extra_args)}",
            )
            return
        messagebox.showinfo(
            "Setup started",
            "A terminal opened for calibration.\n"
            "When finished, click Refresh on the Setup page.",
        )

    def _on_close(self) -> None:
        if self._bot_running() or self._farm_oneshot_running():
            if not messagebox.askyesno("Quit", "Bot is running. Stop it and quit?"):
                return
            self.stop_bot()
            if self._bot_thread is not None:
                self._bot_thread.join(timeout=3.0)
            if self._farm_oneshot_thread is not None:
                self._farm_oneshot_thread.join(timeout=3.0)
        self._gui_state.last_page = self._page
        self._save_gui_state()
        if self._log_sink_id is not None:
            try:
                logger.remove(self._log_sink_id)
            except ValueError:
                pass
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            try:
                self.unbind_all(seq)
            except tk.TclError:
                pass
        self.destroy()


def run_gui(*, dry_run: bool = False, debug_save_frames: bool = False, debug: bool = False) -> None:
    app = BotControlApp(
        dry_run=dry_run,
        debug_save_frames=debug_save_frames,
        debug=debug,
    )
    app.mainloop()
