"""Steam-inspired Tkinter control panel for the donation bot."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import threading
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import messagebox, ttk

from loguru import logger

from coc_bot import __version__
from coc_bot.calibration.wizard import (
    STEP_IDS,
    STEPS,
    CalibrationWizard,
    parent_step_id,
    part_is_configured,
)
from coc_bot.config import (
    load_config,
    load_user_settings,
    project_root,
    save_user_settings,
    user_settings_path,
)
from coc_bot.gui.calib_backup import (
    CalibrationBackup,
    clear_live_calibration,
    create_backup,
    delete_backup,
    get_backup,
    list_backups,
    rename_backup,
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
from coc_bot.gui.setup_calib import (
    calibrate_part_in_app,
    part_supports_in_app,
    should_calibrate_part,
)
from coc_bot.gui.theme import (
    active_layout,
    apply_theme,
    bind_yview_mousewheel,
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
from coc_bot.gui.calib_instructions import (
    format_part_instruction,
    format_step_instruction,
    part_instruction,
)
from coc_bot.gui.ux_helpers import (
    FIXIT_RECIPES,
    FarmReadiness,
    FixItRecipe,
    MissingCalibration,
    break_timer_caption,
    farm_readiness,
    live_status_label,
    next_missing_calibration,
    settings_snapshot,
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
        show_startup_splash: bool = False,
    ) -> None:
        super().__init__()
        # Splash teardown can leave tk._default_root pointing at a dead window;
        # force this app to own Variable() defaults for the whole session.
        try:
            tk._default_root = self  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
        self._startup_splash = None
        self._startup_progress: Callable[[float, str], None] | None = None
        if show_startup_splash:
            # Hide the main shell; splash uses its own Tk so the bar stays visible.
            # App StringVars must keep master=self (see _str_var / _bool_var).
            self.withdraw()
            from coc_bot.gui.splash import StartupSplash

            self._startup_splash = StartupSplash()
            self._startup_progress = self._startup_splash.set
            self._report_startup(0.50, "Opening window…")
            # Re-assert ownership after splash creates its temporary Tk.
            try:
                tk._default_root = self  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                pass

        self.title("CoC Donation Bot")
        self.geometry("1040x720")
        self.minsize(860, 600)
        self._gui_state: GuiWindowState = load_gui_window_state(self._window_geometry_path())
        if self._gui_state.geometry:
            try:
                self.geometry(self._gui_state.geometry)
            except tk.TclError:
                pass
        self._report_startup(0.55, "Applying theme…")
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
        # Bind vars to this root explicitly (avoids attaching to a destroyed splash Tk).
        self._page_title = tk.StringVar(master=self, value="Home")
        self._page_subtitle = tk.StringVar(master=self, value=PAGES[0][2])
        self._status = tk.StringVar(
            master=self,
            value="Ready — open Waydroid and Clash of Clans, then press Start",
        )
        self._adb_status_var = tk.StringVar(master=self, value="ADB · …")
        self._last_adb_ok: bool | None = None
        self._adb_banner: tk.Frame | None = None
        self._onboarding_frame: tk.Frame | None = None
        self._onboarding_title_var = tk.StringVar(master=self, value="Get started")
        self._onboarding_checklist_var = tk.StringVar(master=self, value="")
        self._onboarding_dismiss_btn: ttk.Button | None = None
        self._home_anchor: tk.Misc | None = None
        self._log_lines: list[str] = []
        self._run_chip_var = tk.StringVar(master=self, value="Stopped")
        self._farm_timer_var = tk.StringVar(master=self, value="—")
        self._break_timer_var = tk.StringVar(master=self, value="—")
        self._farm_timer_label: tk.Label | None = None
        self._break_timer_label: tk.Label | None = None
        self._break_caption_label: tk.Label | None = None
        # Frozen farm countdown while the bot is stopped (wall clock still advances).
        self._farm_timer_frozen_text: str | None = None
        self._calib_progress = tk.StringVar(master=self, value="")
        self._log_autoscroll = tk.BooleanVar(master=self, value=True)
        self._section_collapsed: dict[str, bool] = {}
        self._tool_buttons: list[ttk.Button] = []
        self._settings_canvas: tk.Canvas | None = None
        self._tools_canvas: tk.Canvas | None = None
        self._setup_canvas: tk.Canvas | None = None
        self._sidebar_chrome: list[tk.Misc] = []
        self._statusbar_chrome: list[tk.Misc] = []
        # (page_id, label, horizontal reserve px) — wraplength tracks content width.
        self._wrap_labels: list[tuple[str, tk.Label, int]] = []

        # UX polish: practice mode, dirty-settings guard, human activity feed,
        # break warnings, and ADB device picker / auto-reconnect state.
        self._practice_var = tk.BooleanVar(
            master=self, value=bool(load_config().gui_practice_mode)
        )
        self._practice_mode = bool(self._practice_var.get())
        self._practice_sync_guard = False
        self._practice_var.trace_add("write", lambda *_a: self._on_practice_toggle())
        self._settings_dirty = False
        self._settings_baseline: dict[str, str] | None = None
        self._break_warn_sent_for: str | None = None
        self._adb_reconnect_attempts = 0
        self._adb_reconnecting = False
        self._farm_ready_var = tk.StringVar(master=self, value="")
        self._farm_ready_outer: tk.Frame | None = None
        self._farm_ready_label: tk.Label | None = None
        self._home_timers_frame: tk.Frame | None = None
        self._break_caption_var = tk.StringVar(master=self, value="NEXT BREAK")

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

        self._report_startup(0.62, "Building Home…")
        self._build_home_page()
        self._report_startup(0.72, "Building Settings…")
        self._build_settings_page()
        self._report_startup(0.82, "Building Setup…")
        self._build_setup_page()
        self._report_startup(0.92, "Building Tools…")
        self._build_tools_page()
        self._report_startup(0.97, "Finishing…")

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
        self._finish_startup_splash()

    def _report_startup(self, fraction: float, message: str) -> None:
        cb = self._startup_progress
        if cb is not None:
            try:
                cb(fraction, message)
            except Exception:  # noqa: BLE001
                pass

    def _str_var(self, value: str = "") -> tk.StringVar:
        """StringVar pinned to this app root (safe after splash teardown)."""
        return tk.StringVar(master=self, value=value)

    def _bool_var(self, value: bool = False) -> tk.BooleanVar:
        """BooleanVar pinned to this app root (safe after splash teardown)."""
        return tk.BooleanVar(master=self, value=bool(value))

    def _finish_startup_splash(self) -> None:
        """Close the overlay splash and show the main window."""
        self._report_startup(1.0, "Ready")
        splash = self._startup_splash
        self._startup_splash = None
        self._startup_progress = None
        if splash is not None:
            splash.close()
        # Recreate Home live vars on this root after any splash teardown.
        self._rebind_home_live_vars()
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
        except tk.TclError:
            pass
        try:
            self._push_home_timers()
            self._sync_run_chip()
        except Exception:  # noqa: BLE001
            pass

    def _rebind_home_live_vars(self) -> None:
        """Point chip/timer labels at fresh StringVars owned by this Tk root."""
        try:
            tk._default_root = self  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
        self._run_chip_var = self._str_var("Stopped")
        self._farm_timer_var = self._str_var("—")
        self._break_timer_var = self._str_var("—")
        self._break_caption_var = self._str_var("NEXT BREAK")
        pairs = (
            ("_run_chip", self._run_chip_var),
            ("_farm_timer_label", self._farm_timer_var),
            ("_break_timer_label", self._break_timer_var),
            ("_break_caption_label", self._break_caption_var),
        )
        for attr, var in pairs:
            widget = getattr(self, attr, None)
            if widget is None:
                continue
            try:
                if widget.winfo_exists():
                    widget.configure(textvariable=var)
            except tk.TclError:
                continue

    def _push_home_timers(self) -> None:
        """Update farm/break timer StringVars once (no reschedule)."""
        try:
            self._farm_timer_var.set(self._farm_timer_text())
        except Exception:  # noqa: BLE001
            try:
                self._farm_timer_var.set("—")
            except tk.TclError:
                pass
        try:
            on_break, remaining = self._break_status()
            self._break_timer_var.set(
                "due" if (not on_break and remaining <= 0) else format_countdown(remaining)
            )
            self._break_caption_var.set(break_timer_caption(on_break=on_break))
            self._maybe_warn_break_soon(on_break=on_break, remaining=remaining)
        except Exception:  # noqa: BLE001
            try:
                self._break_timer_var.set("—")
            except tk.TclError:
                pass

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
        if self._page == "settings" and page_id != "settings" and self._settings_dirty:
            outcome = self._confirm_settings_dirty_leave()
            if outcome == "cancel":
                return
            if outcome == "save":
                self._save_settings()
                if self._settings_dirty:
                    # Save failed validation — stay put so the user can fix it.
                    return
            elif outcome == "discard":
                self._reload_settings_fields()
                self._settings_baseline = settings_snapshot(
                    {key: var.get() for key, var in self._setting_vars.items()}
                )
                self._settings_dirty = False
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

    def _confirm_settings_dirty_leave(self) -> str:
        """Ask Save / Discard / Cancel for unsaved Settings edits. Returns one of those."""
        response = messagebox.askyesnocancel(
            "Unsaved settings",
            "You have unsaved changes in Settings.\n\n"
            "Save them before leaving this page?\n\n"
            "Yes = Save, No = Discard changes, Cancel = stay here.",
        )
        if response is True:
            return "save"
        if response is False:
            return "discard"
        return "cancel"

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
            self._start_adb_auto_reconnect()
        self._refresh_home_status()

    def _start_adb_auto_reconnect(self) -> None:
        """Kick off automatic ADB reconnect attempts while the bot is running."""
        if self._adb_reconnecting:
            return
        self._adb_reconnecting = True
        self._adb_reconnect_attempts = 0
        self._append_log("==> ADB disconnected — attempting to reconnect…")
        self._adb_auto_reconnect()

    def _adb_auto_reconnect(self) -> None:
        if not self._bot_running() or self._last_adb_ok is True:
            self._adb_reconnecting = False
            self._adb_reconnect_attempts = 0
            return
        if self._adb_reconnect_attempts >= 5:
            self._adb_reconnecting = False
            self._append_log("==> ADB auto-reconnect gave up after 5 attempts")
            notify(
                "ADB reconnect failed",
                "Could not reconnect after 5 attempts — check Waydroid/emulator.",
            )
            return
        self._adb_reconnect_attempts += 1
        attempt = self._adb_reconnect_attempts

        def worker() -> None:
            try:
                from coc_bot.adb.client import AdbClient

                config = load_config()
                ok = AdbClient(device=config.adb_device).connect()
            except Exception:  # noqa: BLE001
                ok = False

            def done() -> None:
                self._append_log(
                    f"==> ADB auto-reconnect attempt {attempt}/5: {'ok' if ok else 'failed'}"
                )
                if ok:
                    self._adb_reconnecting = False
                    self._adb_reconnect_attempts = 0
                    self._set_adb_status(True)
                    return
                self.after(8000, self._adb_auto_reconnect)

            self.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

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
        """Update scrollregion for Settings/Tools/Setup canvases after collapse toggles."""
        for canvas in (self._settings_canvas, self._tools_canvas, self._setup_canvas):
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
            text="Pick device",
            style=self._btn_style("Secondary"),
            command=self._pick_adb_device,
        ).pack(side=tk.LEFT, padx=(8, 0))
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
            textvariable=self._onboarding_title_var,
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
            text="Pick device",
            style=self._btn_style("Secondary"),
            command=self._pick_adb_device,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            ob_btns,
            text="Go to Setup",
            style=self._btn_style("Secondary"),
            command=lambda: self._show_page("setup"),
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            ob_btns,
            text="Calibrate what's missing",
            style=self._btn_style("Accent"),
            command=self.calibrate_whats_missing,
        ).pack(side=tk.LEFT, padx=(8, 0))
        self._onboarding_dismiss_btn = ttk.Button(
            ob_btns,
            text="Dismiss",
            style=self._btn_style("Secondary"),
            command=self._exit_first_launch_preview,
        )
        self._onboarding_dismiss_btn.pack(side=tk.RIGHT)
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
        practice_row = tk.Frame(play_header, bg=theme.SURFACE_2)
        practice_row.pack(side=tk.RIGHT, padx=(0, 10))
        tk.Label(
            practice_row,
            text="Practice",
            bg=theme.SURFACE_2,
            fg=theme.TEXT_SECONDARY,
            font=ui_font(10),
        ).pack(side=tk.LEFT, padx=(0, 6))
        ToggleSwitch(practice_row, self._practice_var, bg=theme.SURFACE_2).pack(side=tk.LEFT)

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

        farm_ready_frame = tk.Frame(pad, bg=theme.SURFACE_2)
        farm_ready_frame.pack(fill=tk.X, pady=(12, 0))
        self._farm_ready_outer = farm_ready_frame
        farm_ready_label = tk.Label(
            farm_ready_frame,
            textvariable=self._farm_ready_var,
            bg=theme.SURFACE_2,
            fg=theme.TEXT_SECONDARY,
            font=ui_font(10),
            justify=tk.LEFT,
            anchor="w",
        )
        farm_ready_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._farm_ready_label = farm_ready_label
        self._track_wrap_label(farm_ready_label, reserve=140, page_id="home")
        ttk.Button(
            farm_ready_frame,
            text="Fix in Setup",
            style=self._btn_style("Secondary"),
            command=lambda: self._show_page("setup"),
        ).pack(side=tk.RIGHT)

        timers = tk.Frame(pad, bg=theme.SURFACE_2)
        timers.pack(fill=tk.X, pady=(14, 0))
        self._home_timers_frame = timers
        timers.columnconfigure(0, weight=1, uniform="home_timer")
        timers.columnconfigure(1, weight=1, uniform="home_timer")
        farm_cell = tk.Frame(timers, bg=theme.SURFACE_2)
        farm_cell.grid(row=0, column=0, sticky="w")
        tk.Label(
            farm_cell,
            text="FARM",
            bg=theme.SURFACE_2,
            fg=theme.TEXT_SECONDARY,
            font=ui_font(9, "bold"),
            anchor="w",
        ).pack(anchor=tk.W)
        self._farm_timer_label = tk.Label(
            farm_cell,
            textvariable=self._farm_timer_var,
            bg=theme.SURFACE_2,
            fg=theme.TEXT,
            font=ui_font(12, "bold"),
            anchor="w",
        )
        self._farm_timer_label.pack(anchor=tk.W)

        break_cell = tk.Frame(timers, bg=theme.SURFACE_2)
        break_cell.grid(row=0, column=1, sticky="w", padx=(16, 0))
        self._break_caption_label = tk.Label(
            break_cell,
            textvariable=self._break_caption_var,
            bg=theme.SURFACE_2,
            fg=theme.TEXT_SECONDARY,
            font=ui_font(9, "bold"),
            anchor="w",
        )
        self._break_caption_label.pack(anchor=tk.W)
        self._break_timer_label = tk.Label(
            break_cell,
            textvariable=self._break_timer_var,
            bg=theme.SURFACE_2,
            fg=theme.TEXT,
            font=ui_font(12, "bold"),
            anchor="w",
        )
        self._break_timer_label.pack(anchor=tk.W)

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
        # Use ttk.Scrollbar (themed) instead of ScrolledText's native grey bar.
        log_wrap = tk.Frame(log_pad, bg=theme.SURFACE_2)
        log_wrap.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        self._log = tk.Text(
            log_wrap,
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
        log_scroll = ttk.Scrollbar(log_wrap, orient=tk.VERTICAL, command=self._log.yview)
        self._log.configure(yscrollcommand=log_scroll.set)
        self._log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        bind_yview_mousewheel(self._log)
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

        missing = next_missing_calibration(config) if config is not None else None
        calib_line = f"{'✓' if calib_ok else '✗'}  Required calibration (Setup)"
        if not calib_ok and missing is not None:
            calib_line += f" — next: {missing.label}"
        self._onboarding_checklist_var.set(
            f"{'✓' if adb_ok else '✗'}  ADB connected\n"
            f"{calib_line}\n"
            "•  Farm attacks are optional — set them up any time in Setup → Farm"
        )
        preview = bool(self._gui_state.first_launch_preview)
        stash = self._gui_state.first_launch_calib_stash
        if preview and stash:
            self._onboarding_title_var.set(
                "Get started (first-launch preview · calibration stashed)"
            )
        elif preview:
            self._onboarding_title_var.set("Get started (first-launch preview)")
        else:
            self._onboarding_title_var.set("Get started")
        if self._onboarding_dismiss_btn is not None:
            try:
                self._onboarding_dismiss_btn.configure(
                    text="Exit first-launch preview" if preview else "Dismiss"
                )
            except tk.TclError:
                pass
        show_onboarding = preview or not self._gui_state.onboarding_dismissed
        try:
            if show_onboarding:
                if not self._onboarding_frame.winfo_ismapped():
                    self._onboarding_frame.pack(fill=tk.X, pady=(0, 12), before=self._home_anchor)
            else:
                self._onboarding_frame.pack_forget()
        except tk.TclError:
            pass
        self._refresh_farm_readiness()

    def _refresh_farm_readiness(self) -> None:
        """Show/hide the Home farm-readiness card and update its summary text."""
        outer = self._farm_ready_outer
        label = self._farm_ready_label
        if outer is None or label is None:
            return
        try:
            readiness: FarmReadiness = farm_readiness()
        except Exception:  # noqa: BLE001
            return
        self._farm_ready_var.set("\n".join(readiness.summary_lines()))
        try:
            if label.winfo_exists():
                label.configure(fg=theme.SUCCESS if readiness.ready_for_manual else theme.DANGER)
        except tk.TclError:
            pass
        try:
            if not outer.winfo_exists():
                return
            if readiness.ready_for_manual:
                outer.pack_forget()
            elif not outer.winfo_ismapped():
                before = self._home_timers_frame
                if before is not None and before.winfo_exists():
                    outer.pack(fill=tk.X, pady=(12, 0), before=before)
                else:
                    outer.pack(fill=tk.X, pady=(12, 0))
        except tk.TclError:
            pass

    def _dismiss_onboarding(self) -> None:
        """Hide Get started (same as exiting first-launch preview)."""
        self._exit_first_launch_preview(confirm=False)

    def _enter_first_launch_preview(self) -> None:
        """Show Home Get-started; optionally stash calibration to re-test Setup."""
        if not messagebox.askyesno(
            "First-launch preview",
            "Show the Home “Get started” checklist as if this were the first "
            "time opening the bot?\n\n"
            "Continue?",
            parent=self,
        ):
            return

        stash_stamp: str | None = self._gui_state.first_launch_calib_stash
        if stash_stamp and get_backup(stash_stamp) is not None:
            messagebox.showinfo(
                "Stash already active",
                "Calibration is already stashed from an earlier first-launch "
                f"preview ({stash_stamp}).\n\n"
                "Exit that preview (and choose restore) before stashing again.",
                parent=self,
            )
        else:
            stash = messagebox.askyesno(
                "Test GUI calibration?",
                "Stash your current calibration and clear it so you can walk "
                "through Setup / “Calibrate what’s missing” from scratch?\n\n"
                "Yes = backup then clear live calibration (restored when you exit).\n"
                "No = only show Get started (calibration stays as-is).",
                parent=self,
            )
            if stash:
                try:
                    backup = create_backup(stamp_prefix="first_launch_stash_")
                    clear_live_calibration()
                    stash_stamp = backup.stamp
                    self._append_log(
                        f"==> Stashed calibration as {backup.stamp} and cleared live files"
                    )
                except FileNotFoundError:
                    messagebox.showinfo(
                        "Nothing to stash",
                        "No calibration files found — continuing with an empty Setup.",
                        parent=self,
                    )
                    stash_stamp = None
                except OSError as exc:
                    messagebox.showerror("Stash failed", str(exc), parent=self)
                    return

        self._gui_state.onboarding_dismissed = False
        self._gui_state.first_launch_preview = True
        self._gui_state.first_launch_calib_stash = stash_stamp
        self._gui_state.last_page = "home"
        self._save_gui_state()
        self._append_log("==> First-launch preview ON (Get started shown)")
        restart = messagebox.askyesno(
            "Restart window?",
            "Restart the control window now so it opens on Home like a first launch?\n\n"
            "Yes = quit and relaunch this app.\n"
            "No = switch to Home immediately without restarting.",
            parent=self,
        )
        if restart:
            self._restart_gui_process()
            return
        self._show_page("home")
        self._refresh_home_status()
        self._refresh_calib_status()
        if load_config().gui_dev_options:
            self._build_tools_page()

    def _exit_first_launch_preview(self, *, confirm: bool = True) -> None:
        """Leave first-launch preview / dismiss Get started; optionally restore stash."""
        if confirm and self._gui_state.first_launch_preview:
            if not messagebox.askyesno(
                "Exit first-launch preview",
                "Hide the Get started card and return to normal Home?",
                parent=self,
            ):
                return
        was_preview = bool(self._gui_state.first_launch_preview)
        stash_stamp = self._gui_state.first_launch_calib_stash
        if stash_stamp:
            backup = get_backup(stash_stamp)
            if backup is not None:
                restore = messagebox.askyesno(
                    "Restore stashed calibration?",
                    f"A calibration stash is available ({stash_stamp}).\n\n"
                    "Yes = put your previous calibration back (recommended).\n"
                    "No = keep whatever is live now from this test.",
                    parent=self,
                )
                if restore:
                    try:
                        restore_backup(backup, safety_snapshot=False)
                        self._append_log(f"==> Restored calibration from {stash_stamp}")
                    except (OSError, FileNotFoundError) as exc:
                        messagebox.showerror("Restore failed", str(exc), parent=self)
                        return
            else:
                messagebox.showwarning(
                    "Stash missing",
                    f"Could not find stash “{stash_stamp}”. "
                    "Live calibration was left unchanged.",
                    parent=self,
                )
            self._gui_state.first_launch_calib_stash = None

        self._gui_state.onboarding_dismissed = True
        self._gui_state.first_launch_preview = False
        self._save_gui_state()
        if was_preview:
            self._append_log("==> First-launch preview OFF")
        self._refresh_home_status()
        self._refresh_calib_status()
        if load_config().gui_dev_options:
            self._build_tools_page()

    def _restart_gui_process(self) -> None:
        """Quit and re-exec the same GUI entrypoint (used by first-launch preview)."""
        if self._bot_running() or self._farm_oneshot_running():
            if not messagebox.askyesno(
                "Restart",
                "The bot is running. Stop it and restart the window?",
                parent=self,
            ):
                return
            self.stop_bot()
            if self._bot_thread is not None:
                self._bot_thread.join(timeout=3.0)
            if self._farm_oneshot_thread is not None:
                self._farm_oneshot_thread.join(timeout=3.0)

        self._gui_state.last_page = "home"
        self._save_gui_state()
        cmd = [sys.executable, "-m", "coc_bot"]
        if self._dry_run:
            cmd.append("--dry-run")
        if self._debug_save_frames:
            cmd.append("--debug-save-frames")
        if self._debug:
            cmd.append("--debug")
        try:
            cwd = str(project_root())
            env = os.environ.copy()
            # Ensure `python -m coc_bot` finds src/ layouts.
            src = str(Path(cwd) / "src")
            if Path(src).is_dir():
                existing = env.get("PYTHONPATH", "")
                env["PYTHONPATH"] = src if not existing else f"{src}{os.pathsep}{existing}"
            subprocess.Popen(cmd, cwd=cwd, env=env)  # noqa: S603
        except OSError as exc:
            messagebox.showerror("Restart failed", str(exc), parent=self)
            return
        self._append_log("==> Relaunching control window…")
        self.destroy()

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
        ttk.Button(
            footer,
            text="Detect ADB devices",
            style=self._btn_style("Secondary"),
            command=self._pick_adb_device,
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

        # Dirty guard: snapshot the just-built widget values as the baseline,
        # then watch every var for edits that diverge from it.
        self._settings_baseline = settings_snapshot(
            {key: var.get() for key, var in self._setting_vars.items()}
        )
        self._settings_dirty = False
        for var in self._setting_vars.values():
            var.trace_add("write", lambda *_a: self._mark_settings_dirty())

    def _mark_settings_dirty(self) -> None:
        if self._settings_baseline is None:
            return
        current: dict[str, str | bool] = {}
        for key, var in self._setting_vars.items():
            try:
                current[key] = var.get()
            except tk.TclError:
                continue
        snapshot = settings_snapshot(current)
        baseline = {k: v for k, v in self._settings_baseline.items() if k in snapshot}
        self._settings_dirty = snapshot != baseline

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
            var: tk.Variable = self._bool_var(bool(value))
            ttk.Checkbutton(block, text="Enabled", variable=var).pack(anchor=tk.W)
            self._setting_vars[field.key] = var
        elif field.kind == "choice":
            var = self._str_var(str(value))
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
            var = self._str_var(str(value))
            entry = ttk.Entry(block, textvariable=var, width=42)
            entry.pack(anchor=tk.W, ipady=2)
            self._setting_vars[field.key] = var
            self._attach_setting_hint(block, field, var, side="below")

    def _add_tools_row_modern(
        self,
        block: tk.Frame,
        *,
        title: str,
        description: str,
        button_text: str,
        command,
    ) -> ttk.Button:
        """Settings-style Tools row: wrapped text left, action button right."""
        block.columnconfigure(0, weight=1)
        block.columnconfigure(1, weight=0)

        left = tk.Frame(block, bg=theme.SURFACE_2)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 16))

        title_lbl = tk.Label(
            left,
            text=title,
            bg=theme.SURFACE_2,
            fg=theme.TEXT,
            font=ui_font(12),
            anchor="w",
            justify=tk.LEFT,
            wraplength=200,
        )
        title_lbl.pack(anchor=tk.W, fill=tk.X)
        desc_lbl = tk.Label(
            left,
            text=description,
            bg=theme.SURFACE_2,
            fg=theme.TEXT_SECONDARY,
            font=ui_font(10),
            wraplength=200,
            justify=tk.LEFT,
            anchor="w",
        )
        desc_lbl.pack(anchor=tk.W, fill=tk.X, pady=(4, 0))

        right = tk.Frame(block, bg=theme.SURFACE_2)
        right.grid(row=0, column=1, sticky="ne")
        btn = ttk.Button(
            right,
            text=button_text,
            style=self._btn_style("Secondary"),
            command=command,
        )
        btn.pack(anchor=tk.E)
        self._bind_modern_row_wrap([title_lbl, desc_lbl], block, right, gap=20)
        return btn

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
            var = self._bool_var(bool(value))
            ToggleSwitch(right, var, bg=theme.SURFACE_2).pack(anchor=tk.E, pady=(2, 0))
            self._setting_vars[field.key] = var
        elif field.kind == "choice":
            var = self._str_var(str(value))
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
            var = self._str_var(str(value))
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
        self._settings_baseline = settings_snapshot(
            {key: var.get() for key, var in self._setting_vars.items()}
        )
        self._settings_dirty = False
        self._set_practice_var_silent(bool(values.get("gui_practice_mode", self._practice_mode)))
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
            self._build_tools_page()
            self._append_log(
                f"==> Dev options {'enabled' if new_dev else 'disabled'} — "
                "Settings/Tools refreshed"
            )
        else:
            # Rebuild paths above already refresh the dirty baseline themselves.
            self._settings_dirty = False
            self._settings_baseline = settings_snapshot(
                {key: var.get() for key, var in self._setting_vars.items()}
            )

        self._set_practice_var_silent(bool(values.get("gui_practice_mode", self._practice_mode)))

        extra = ""
        if theme_changed:
            extra = f"\n\nTheme switched to {theme_label(new_theme)}."
        messagebox.showinfo(
            "Saved",
            f"Settings saved to:\n{path}\n\nStop and Start the bot to apply them to a running loop.\n"
            f"Activity log DEBUG filter applies immediately.{extra}",
        )

        if self._bot_running() and messagebox.askyesno(
            "Apply now?", "Apply & restart the bot now with these settings?"
        ):
            self._restart_bot()

    def _build_setup_page(self) -> None:
        page = self._pages["setup"]
        for child in page.winfo_children():
            child.destroy()
        self._clear_wrap_labels("setup")

        canvas, inner = make_scrollable(page)
        self._setup_canvas = canvas

        intro = tk.Frame(inner, bg=theme.BG)
        intro.pack(fill=tk.X, padx=8, pady=(4, 4))
        intro_label = tk.Label(
            intro,
            text="Teach the bot where buttons and bars are on your screen. "
            "Open Waydroid and Clash first, pick a step or part below, then "
            "Recalibrate Selected. Everything runs in-app; Classic terminal is optional.",
            bg=theme.BG,
            fg=theme.TEXT_SECONDARY,
            font=ui_font(10),
            wraplength=400,
            justify=tk.LEFT,
            anchor="w",
        )
        intro_label.pack(fill=tk.X, pady=(0, 4))
        self._track_wrap_label(intro_label, reserve=40, page_id="setup")
        progress_label = tk.Label(
            intro,
            textvariable=self._calib_progress,
            bg=theme.BG,
            fg=theme.ACCENT,
            font=ui_font(11, "bold"),
            anchor="w",
        )
        progress_label.pack(fill=tk.X, pady=(0, 8))

        checklist_body = self._section_header(inner, "setup:checklist", "Checklist")
        tree_card = self._card(checklist_body, padx=8, pady=4 if self._modern else 5)
        tree_wrap = tk.Frame(tree_card, bg=theme.SURFACE_2)
        tree_wrap.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        cols = ("status",)
        self._calib_tree = ttk.Treeview(
            tree_wrap,
            columns=cols,
            show="tree headings",
            height=12,
            selectmode="browse",
        )
        self._calib_tree.heading("#0", text="Step / part")
        self._calib_tree.heading("status", text="Status")
        self._calib_tree.column("#0", width=420, stretch=True)
        self._calib_tree.column("status", width=110, stretch=False)
        tree_scroll = ttk.Scrollbar(
            tree_wrap, orient=tk.VERTICAL, command=self._calib_tree.yview
        )
        self._calib_tree.configure(yscrollcommand=tree_scroll.set)
        self._calib_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self._calib_detail = self._str_var("")
        detail_pad = tk.Frame(tree_card, bg=theme.SURFACE_2)
        detail_pad.pack(fill=tk.X, padx=14, pady=(0, 12))
        calib_detail = tk.Label(
            detail_pad,
            textvariable=self._calib_detail,
            bg=theme.SURFACE_2,
            fg=theme.TEXT_SECONDARY,
            font=ui_font(10),
            wraplength=400,
            justify=tk.LEFT,
            anchor="w",
        )
        calib_detail.pack(fill=tk.X)
        self._track_wrap_label(calib_detail, reserve=56, page_id="setup")
        self._calib_tree.bind("<<TreeviewSelect>>", self._on_calib_select)

        actions_body = self._section_header(inner, "setup:actions", "Calibrate")
        actions_card = self._card(actions_body, padx=8, pady=4 if self._modern else 5)
        actions_pad = tk.Frame(actions_card, bg=theme.SURFACE_2)
        actions_pad.pack(fill=tk.X, padx=14, pady=12)
        ttk.Button(
            actions_pad,
            text="Calibrate what's missing",
            style=self._btn_style("Accent"),
            command=self.calibrate_whats_missing,
        ).pack(side=tk.LEFT)
        ttk.Button(
            actions_pad,
            text="Recalibrate Selected",
            style=self._btn_style("Secondary"),
            command=self._recalibrate_selected,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            actions_pad,
            text="Recalibrate All",
            style=self._btn_style("Secondary"),
            command=self._recalibrate_all,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            actions_pad,
            text="Refresh",
            style=self._btn_style("Secondary"),
            command=self._refresh_calib_status,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            actions_pad,
            text="Classic terminal calibrator",
            style=self._btn_style("Secondary"),
            command=self._classic_calibrate_selected,
        ).pack(side=tk.LEFT, padx=(8, 0))

        backups_body = self._section_header(inner, "setup:backups", "Backups")
        backups_card = self._card(backups_body, padx=8, pady=4 if self._modern else 5)
        backups_pad = tk.Frame(backups_card, bg=theme.SURFACE_2)
        backups_pad.pack(fill=tk.X, padx=14, pady=12)
        backups_hint = tk.Label(
            backups_pad,
            text="Snapshots of calibrated.yaml + templates under data/calibration_backups/.",
            bg=theme.SURFACE_2,
            fg=theme.TEXT_SECONDARY,
            font=ui_font(10),
            wraplength=400,
            justify=tk.LEFT,
            anchor="w",
        )
        backups_hint.pack(fill=tk.X, pady=(0, 10))
        self._track_wrap_label(backups_hint, reserve=56, page_id="setup")
        btn_row = tk.Frame(backups_pad, bg=theme.SURFACE_2)
        btn_row.pack(fill=tk.X)
        ttk.Button(
            btn_row,
            text="Backup",
            style=self._btn_style("Secondary"),
            command=self._backup_calibration,
        ).pack(side=tk.LEFT)
        ttk.Button(
            btn_row,
            text="Restore",
            style=self._btn_style("Secondary"),
            command=self._restore_calibration,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            btn_row,
            text="Rename",
            style=self._btn_style("Secondary"),
            command=self._rename_calibration_backup,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            btn_row,
            text="Delete",
            style=self._btn_style("Secondary"),
            command=self._delete_calibration_backup,
        ).pack(side=tk.LEFT, padx=(8, 0))

        finish_scrollable(inner, canvas)
        self.after_idle(self._sync_wrap_lengths)

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

        fixit_body = self._section_header(inner, "tools:fixit", "If something's wrong")
        for recipe in FIXIT_RECIPES:
            card = self._card(fixit_body, padx=8, pady=4 if self._modern else 5)
            block = tk.Frame(card, bg=theme.SURFACE_2)
            block.pack(fill=tk.X, padx=14, pady=12)
            if self._modern:
                self._add_tools_row_modern(
                    block,
                    title=recipe.title,
                    description=recipe.body,
                    button_text=recipe.action_label,
                    command=lambda r=recipe: self._run_fixit(r),
                )
            else:
                ttk.Button(
                    block,
                    text=recipe.title,
                    style=self._btn_style("Secondary"),
                    command=lambda r=recipe: self._run_fixit(r),
                ).pack(anchor=tk.W)
                desc = tk.Label(
                    block,
                    text=f"{recipe.body}\n→ {recipe.action_label}",
                    bg=theme.SURFACE_2,
                    fg=theme.TEXT_SECONDARY,
                    font=ui_font(10),
                    wraplength=400,
                    justify=tk.LEFT,
                    anchor="w",
                )
                desc.pack(fill=tk.X, pady=(8, 0))
                self._track_wrap_label(desc, reserve=56, page_id="tools")

        for group_title, actions in DEBUG_GROUPS:
            body = self._section_header(inner, f"tools:{group_title}", group_title)

            for action_id, label, description in actions:
                card = self._card(body, padx=8, pady=4 if self._modern else 5)
                block = tk.Frame(card, bg=theme.SURFACE_2)
                block.pack(fill=tk.X, padx=14, pady=12)
                allow_while_running = action_id == "install_desktop_shortcut"
                if self._modern:
                    run_btn = self._add_tools_row_modern(
                        block,
                        title=label,
                        description=description,
                        button_text="Run",
                        command=lambda aid=action_id: self._run_debug(aid),
                    )
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
                run_btn._allow_while_running = allow_while_running  # type: ignore[attr-defined]
                self._tool_buttons.append(run_btn)

        if bool(load_config().gui_dev_options):
            self._build_tools_dev_section(inner)

        self._debug_result = self._str_var("")
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

    def _build_tools_dev_section(self, inner: tk.Frame) -> None:
        """Dev-only Tools rows (Settings → Interface → Dev options)."""
        body = self._section_header(inner, "tools:Dev", "Dev")
        preview_on = bool(self._gui_state.first_launch_preview)
        status = "ON" if preview_on else "off"
        stash = self._gui_state.first_launch_calib_stash
        stash_note = f" Stash: {stash}." if stash else ""
        rows = (
            (
                "Simulate first launch",
                "Show Home “Get started”, then optionally stash & clear calibration "
                "so you can re-test Setup / Calibrate what’s missing from scratch. "
                "Exit restores the stash.",
                "Enter",
                self._enter_first_launch_preview,
                True,
            ),
            (
                "Exit first-launch preview",
                f"Hide Get started (currently {status}).{stash_note} "
                "Offers to restore stashed calibration if you cleared it for testing.",
                "Exit",
                lambda: self._exit_first_launch_preview(confirm=True),
                True,
            ),
        )
        for title, description, button_text, command, allow_while_running in rows:
            card = self._card(body, padx=8, pady=4 if self._modern else 5)
            block = tk.Frame(card, bg=theme.SURFACE_2)
            block.pack(fill=tk.X, padx=14, pady=12)
            if self._modern:
                run_btn = self._add_tools_row_modern(
                    block,
                    title=title,
                    description=description,
                    button_text=button_text,
                    command=command,
                )
            else:
                run_btn = ttk.Button(
                    block,
                    text=title,
                    style=self._btn_style("Secondary"),
                    command=command,
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
            run_btn._allow_while_running = allow_while_running  # type: ignore[attr-defined]
            self._tool_buttons.append(run_btn)

    def _run_fixit(self, recipe: FixItRecipe) -> None:
        """Run the action tied to a Tools → "If something's wrong" recipe card."""
        actions = {
            "connect_adb": self.connect_adb,
            "calib_missing": self.calibrate_whats_missing,
            "setup": lambda: self._show_page("setup"),
            "tools_health": lambda: self._run_debug("health_check"),
            "export_debug": self._export_debug,
        }
        action = actions.get(recipe.action)
        if action is not None:
            action()

    def _run_debug(self, action_id: str) -> None:
        # Shortcut install does not touch ADB / the bot loop.
        allow_while_running = action_id == "install_desktop_shortcut"
        if self._bot_running() and not allow_while_running:
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
                if action_id == "install_desktop_shortcut" and not result.startswith("Error"):
                    messagebox.showinfo(
                        "Desktop shortcut",
                        f"{result}\n\n"
                        "Double-click the icon (choose Allow Launching if Ubuntu asks).",
                    )

            self.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    def _set_debug_busy(self, busy: bool) -> None:
        self._debug_busy = busy
        self._update_tool_buttons_state()

    def _update_tool_buttons_state(self) -> None:
        bot_running = self._bot_running()
        for btn in self._tool_buttons:
            try:
                if not btn.winfo_exists():
                    continue
                allow_while_running = bool(getattr(btn, "_allow_while_running", False))
                disabled = self._debug_busy or (bot_running and not allow_while_running)
                btn.configure(state=tk.DISABLED if disabled else tk.NORMAL)
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
            # Incomplete setup prompt — not a full first-launch preview session.
            self._save_gui_state()
            self._refresh_home_status()
            self._show_page("setup")
            self._refresh_calib_status()
            return

        self._start_btn.configure(state=tk.DISABLED)
        self._stop_btn.configure(state=tk.NORMAL)
        self._status.set("Bot running")
        self._append_log("==> Starting bot")
        if self._practice_mode:
            self._append_log("Activity: Practice mode ON — donation taps will be skipped")
        self._sync_run_chip()
        self._update_tool_buttons_state()

        def worker() -> None:
            try:
                from coc_bot.bot import DonationBot

                self._bot = DonationBot(
                    dry_run=self._dry_run or self._practice_mode,
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

    def _on_practice_toggle(self) -> None:
        """User flipped the Home Practice toggle — persist it and update state."""
        if self._practice_sync_guard:
            return
        payload = load_user_settings()
        payload.setdefault("gui", {})["practice_mode"] = bool(self._practice_var.get())
        save_user_settings(payload)
        self._practice_mode = bool(self._practice_var.get())
        if self._practice_mode:
            self._append_log("Activity: Practice mode enabled — donation taps will be skipped")
        else:
            self._append_log("Activity: Practice mode disabled")
        var = self._setting_vars.get("gui_practice_mode")
        if var is not None:
            var.set(self._practice_mode)
            # Already persisted above — keep the dirty guard from false-flagging it.
            if self._settings_baseline is not None:
                self._settings_baseline["gui_practice_mode"] = "1" if self._practice_mode else "0"
            self._mark_settings_dirty()
        self._sync_run_chip()

    def _set_practice_var_silent(self, value: bool) -> None:
        """Update the practice toggle/state without re-triggering a settings write."""
        self._practice_sync_guard = True
        try:
            self._practice_var.set(bool(value))
        finally:
            self._practice_sync_guard = False
        self._practice_mode = bool(value)
        self._sync_run_chip()

    def _restart_bot(self) -> None:
        """Stop the bot (if running) and start it again once the thread has exited."""
        if not self._bot_running():
            self.start_bot()
            return
        self._append_log("==> Restarting bot to apply settings…")
        self.stop_bot()
        self._await_restart(0)

    def _await_restart(self, attempts: int) -> None:
        if self._bot_running():
            if attempts >= 50:  # ~10s at 200ms per attempt
                self._append_log("==> Bot did not stop in time — restart cancelled")
                return
            self.after(200, lambda: self._await_restart(attempts + 1))
            return
        self.start_bot()

    def request_farm_attack(self) -> None:
        """Queue a farm attack on the running bot, or run a one-shot if stopped."""
        readiness = farm_readiness()
        if not readiness.ready_for_manual:
            messagebox.showerror(
                "Farm not ready",
                "Farm attack now needs:\n\n"
                + "\n".join(readiness.summary_lines())
                + "\n\nOpen Setup → Farm to finish these.",
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
            from coc_bot.runtime.tracker import RuntimeTracker

            tracker = RuntimeTracker(config)
            # Ensure the persisted farm clock is frozen while stopped (idempotent).
            tracker.pause_farm_clock()

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
        else:
            self._farm_timer_frozen_text = None
        return text

    def _break_status(self) -> tuple[bool, float]:
        """Return ``(on_break, remaining_seconds)``.

        When on a session break, ``remaining_seconds`` counts down to the break
        ending; otherwise it counts down to the next break starting.
        """
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
                    return True, left
            except ValueError:
                pass

        return False, tracker.remaining_seconds()

    def _break_timer_text(self) -> str:
        on_break, remaining = self._break_status()
        if not on_break and remaining <= 0:
            return "due"
        return format_countdown(remaining)

    def _maybe_warn_break_soon(self, *, on_break: bool, remaining: float) -> None:
        """Fire a one-time desktop notification a few minutes before a session break."""
        if remaining > 600:
            self._break_warn_sent_for = None
            return
        if not self._bot_running() or on_break:
            return
        if 1 <= remaining <= 300:
            bucket = max(1, int(remaining // 60))
            marker = f"soon:{bucket}"
            if self._break_warn_sent_for == marker:
                return
            self._break_warn_sent_for = marker
            notify(
                "Break soon",
                f"Clash will close for a session break in about {bucket} minute(s).",
            )

    def _refresh_farm_status(self) -> None:
        try:
            self._push_home_timers()
            self._sync_run_chip()
        finally:
            # Always reschedule — a dead StringVar must not stop the timer loop.
            try:
                self.after(2000, self._refresh_farm_status)
            except tk.TclError:
                pass

    def _sync_run_chip(self) -> None:
        if not hasattr(self, "_run_chip"):
            return
        oneshot = self._farm_oneshot_running()
        bot = self._bot
        running = self._bot_running() and bot is not None
        game_state = None
        on_break = False
        try:
            on_break, _remaining = self._break_status()
            if running:
                game_state = bot.game_state.state
        except Exception:  # noqa: BLE001
            pass

        label, role = live_status_label(
            running=running,
            practice=self._practice_mode,
            oneshot_farm=oneshot,
            game_state=game_state,
            on_break=on_break,
        )
        self._set_run_chip(label, role)

    def _set_run_chip(self, text: str, role: str) -> None:
        self._run_chip_var.set(text)
        color = {
            "secondary": theme.TEXT_SECONDARY,
            "success": theme.SUCCESS,
            "accent": theme.ACCENT,
            "danger": theme.DANGER,
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
                values=("Done" if ok else "Missing",),
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
                    values=(part_status,),
                )
        total = len(STEP_IDS)
        self._calib_progress.set(f"Setup progress: {done} / {total} steps ready")
        self._refresh_home_status()
        self._refresh_farm_readiness()
        base_detail = (
            f"{done}/{total} steps configured. Expand a step and select a part to "
            "recalibrate only that item (answer n at prompts to keep existing values)."
        )
        missing: MissingCalibration | None = next_missing_calibration(config)
        if missing is not None:
            base_detail = (
                f"Next required: {missing.label}\n\n{missing.hint}\n\n{base_detail}"
            )
        self._calib_detail.set(base_detail)

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
            opt = " (optional)" if part.optional else ""
            if part_key == "deploy_sequence":
                how = (
                    "Recalibrate Selected opens the farm deploy click editor."
                )
            else:
                how = (
                    f"Recalibrate Selected runs only “{part.label}” "
                    f"(not the whole “{step.title}” step)."
                )
            instr = format_part_instruction(step_id, part_key)
            self._calib_detail.set(
                f"{step.title} → {part.label}{opt}\n"
                f"Status: {status}\n\n"
                f"{instr}\n\n"
                f"{how}"
            )
            return
        status = self._calib_tree.set(iid, "status")
        parts_line = ", ".join(p.label for p in step.parts) if step.parts else step.summary
        self._calib_detail.set(
            f"{format_step_instruction(step_id)}\n"
            f"Status: {status}\n"
            f"Parts: {parts_line}\n\n"
            "Recalibrate Selected walks through each item in this step "
            "(you can skip optional ones)."
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
                self._maybe_program_deploy_sequence()
                return
            part = next((p for p in step.parts if p.key == part_key), None)
            if part is not None and part_supports_in_app(part):
                self._run_in_app_calibration(step_id, part_key)
                return
            self._launch_calibrate(["--step", step_id, "--part", part_key])
            return

        # Whole step — prefer full in-app sequence (including color/grid/frame size).
        self._run_in_app_step(step_id)

    def _maybe_program_deploy_sequence(self) -> bool:
        instr = part_instruction("farm", "deploy_sequence")
        if not messagebox.askyesno(
            "Program farm deploy",
            f"{instr.as_text()}\n\nProceed?",
        ):
            return False
        self._run_debug("farm_program_deploy")
        return True

    def _run_in_app_calibration(self, step_id: str, part_key: str) -> None:
        try:
            result = calibrate_part_in_app(self, step_id, part_key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("In-app calibration failed for {}::{}: {}", step_id, part_key, exc)
            self._append_log(f"Calibration cancelled/failed ({part_key}): {exc}")
            return
        self._append_log(f"==> {result}")
        self._refresh_calib_status()

    def calibrate_whats_missing(self) -> None:
        """Jump straight to the next required-but-missing calibration part."""
        missing: MissingCalibration | None = next_missing_calibration()
        if missing is None:
            messagebox.showinfo(
                "All set",
                "All required calibration is done. Optional items can still be "
                "tuned any time from Setup.",
            )
            return
        self._show_page("setup")
        try:
            iid = f"{missing.step_id}::{missing.part.key}"
            if self._calib_tree.exists(iid):
                self._calib_tree.selection_set(iid)
                self._calib_tree.see(iid)
            elif self._calib_tree.exists(missing.step_id):
                self._calib_tree.selection_set(missing.step_id)
        except tk.TclError:
            pass
        self._append_log(f"==> Next required: {missing.label}")
        self._run_in_app_calibration(missing.step_id, missing.part.key)

    def _run_in_app_step(self, step_id: str, *, ask_optional: bool = True) -> None:
        """Calibrate every in-app part of a step; optionally open farm deploy editor."""
        step = STEPS[step_id]
        config = load_config()
        for part in step.parts:
            if part.key == "deploy_sequence":
                continue
            if not part_supports_in_app(part):
                self._append_log(f"Skipping unsupported part {part.key}")
                continue
            if ask_optional and not should_calibrate_part(self, part, config):
                self._append_log(f"Skipped optional {part.key}")
                continue
            try:
                result = calibrate_part_in_app(self, step_id, part.key)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "In-app calibration failed for {}::{}: {}", step_id, part.key, exc
                )
                self._append_log(f"Calibration cancelled/failed ({part.key}): {exc}")
                if not messagebox.askyesno(
                    "Continue?",
                    f"“{part.label}” was cancelled or failed.\n\n"
                    "Continue with the remaining parts?",
                    parent=self,
                ):
                    break
                continue
            self._append_log(f"==> {result}")
            config = load_config()

        if any(p.key == "deploy_sequence" for p in step.parts):
            instr = part_instruction("farm", "deploy_sequence")
            if messagebox.askyesno(
                "Deploy sequence",
                f"Program the farm deploy tap sequence now?\n\n{instr.as_text()}",
                parent=self,
            ):
                self._run_debug("farm_program_deploy")
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
            "Run the full Setup calibration in the app?\n\n"
            "You will walk through each step with on-screen pickers. "
            "Optional items can be skipped. Classic terminal remains available "
            "from the Classic button if you prefer.",
        ):
            return
        self._append_log("==> Starting full in-app calibration")
        for step_id in STEP_IDS:
            step = STEPS[step_id]
            if not messagebox.askyesno(
                "Next step",
                f"Calibrate “{step.title}”?\n\n{format_step_instruction(step_id)}",
                parent=self,
            ):
                self._append_log(f"Skipped step {step_id}")
                continue
            self._run_in_app_step(step_id, ask_optional=True)
        self._append_log("==> Full in-app calibration finished")
        self._refresh_calib_status()
        messagebox.showinfo(
            "Setup finished",
            "Full calibration walkthrough complete.\n"
            "Check the Setup list for any remaining Missing items.",
        )

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
        chosen = self._choose_calibration_backup(
            title="Restore calibration",
            prompt="Select a backup to restore (newest first):",
            confirm_label="Restore",
        )
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

    def _rename_calibration_backup(self) -> None:
        from tkinter import simpledialog

        chosen = self._choose_calibration_backup(
            title="Rename backup",
            prompt="Select a backup to rename:",
            confirm_label="Rename…",
        )
        if chosen is None:
            return
        new_name = simpledialog.askstring(
            "Rename backup",
            "New name (letters, numbers, . _ -):",
            initialvalue=chosen.stamp,
            parent=self,
        )
        if new_name is None:
            return
        try:
            renamed = rename_backup(chosen, new_name)
        except (ValueError, OSError) as exc:
            messagebox.showerror("Rename failed", str(exc))
            return
        self._append_log(f"==> Renamed backup {chosen.stamp} → {renamed.stamp}")
        messagebox.showinfo("Backup renamed", f"Now named:\n{renamed.stamp}")

    def _delete_calibration_backup(self) -> None:
        chosen = self._choose_calibration_backup(
            title="Delete backup",
            prompt="Select a backup to delete permanently:",
            confirm_label="Delete…",
        )
        if chosen is None:
            return
        if not messagebox.askyesno(
            "Delete backup?",
            f"Permanently delete this calibration backup?\n\n{chosen.stamp}\n\n"
            "This cannot be undone. Your live calibration is not affected.",
            parent=self,
        ):
            return
        try:
            delete_backup(chosen)
        except (OSError, FileNotFoundError, ValueError) as exc:
            messagebox.showerror("Delete failed", str(exc))
            return
        self._append_log(f"==> Deleted calibration backup {chosen.stamp}")
        messagebox.showinfo("Backup deleted", f"Removed:\n{chosen.stamp}")

    def _choose_calibration_backup(
        self,
        *,
        title: str,
        prompt: str,
        confirm_label: str = "Select",
    ) -> CalibrationBackup | None:
        """Pick one stored backup, or None if none exist / cancelled."""
        backups = list_backups()
        if not backups:
            messagebox.showinfo(
                "No backups",
                "No calibration backups found yet.\n"
                "Use Backup calibration first.",
            )
            return None
        return self._pick_calibration_backup(
            backups, title=title, prompt=prompt, confirm_label=confirm_label
        )

    def _pick_calibration_backup(
        self,
        backups: list[CalibrationBackup],
        *,
        title: str = "Restore calibration",
        prompt: str = "Select a backup (newest first):",
        confirm_label: str = "Restore",
    ) -> CalibrationBackup | None:
        """Modal list picker; returns a CalibrationBackup or None if cancelled."""
        win = tk.Toplevel(self)
        win.title(title)
        win.transient(self)
        win.grab_set()
        win.configure(bg=theme.BG)
        result: dict[str, CalibrationBackup | None] = {"value": None}

        tk.Label(
            win,
            text=prompt,
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
            btns, text=confirm_label, style=self._btn_style("Accent"), command=accept
        ).pack(side=tk.RIGHT, padx=(0, 8))
        listbox.bind("<Double-Button-1>", lambda _e: accept())
        win.protocol("WM_DELETE_WINDOW", cancel)
        win.wait_window()
        return result["value"]

    def _pick_from_list(self, *, title: str, prompt: str, items: list[str]) -> int | None:
        """Generic modal listbox picker; returns the selected index or None if cancelled."""
        win = tk.Toplevel(self)
        win.title(title)
        win.transient(self)
        win.grab_set()
        win.configure(bg=theme.BG)
        result: dict[str, int | None] = {"value": None}

        tk.Label(
            win,
            text=prompt,
            bg=theme.BG,
            fg=theme.TEXT,
            font=ui_font(11),
            anchor="w",
        ).pack(fill=tk.X, padx=16, pady=(16, 8))

        frame = tk.Frame(win, bg=theme.BG)
        frame.pack(fill=tk.BOTH, expand=True, padx=16)
        listbox = tk.Listbox(
            frame,
            height=min(12, max(4, len(items))),
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
        for item in items:
            listbox.insert(tk.END, item)
        listbox.selection_set(0)

        btns = tk.Frame(win, bg=theme.BG)
        btns.pack(fill=tk.X, padx=16, pady=16)

        def accept() -> None:
            sel = listbox.curselection()
            if not sel:
                return
            result["value"] = int(sel[0])
            win.destroy()

        def cancel() -> None:
            result["value"] = None
            win.destroy()

        ttk.Button(
            btns, text="Cancel", style=self._btn_style("Secondary"), command=cancel
        ).pack(side=tk.RIGHT)
        ttk.Button(
            btns, text="Select", style=self._btn_style("Accent"), command=accept
        ).pack(side=tk.RIGHT, padx=(0, 8))
        listbox.bind("<Double-Button-1>", lambda _e: accept())
        win.protocol("WM_DELETE_WINDOW", cancel)
        win.wait_window()
        return result["value"]

    def _pick_adb_device(self) -> None:
        """List ``adb devices`` and let the user pick one to save + connect to."""
        from coc_bot.adb.client import AdbClient

        devices = AdbClient.list_devices()
        if not devices:
            messagebox.showinfo(
                "No devices found",
                "adb devices returned nothing. Make sure Waydroid/emulator is running "
                "and adb is on your PATH, then try again.",
            )
            return
        idx = self._pick_from_list(
            title="Pick ADB device",
            prompt="Select the device ADB should use:",
            items=[f"{serial}  ({state})" for serial, state in devices],
        )
        if idx is None:
            return
        serial = devices[idx][0]
        payload = load_user_settings()
        payload.setdefault("adb", {})["device"] = serial
        save_user_settings(payload)
        self._append_log(f"==> ADB device set to {serial}")
        var = self._setting_vars.get("adb_device")
        if var is not None:
            var.set(serial)
        self.connect_adb()

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
        if self._page == "settings" and self._settings_dirty:
            outcome = self._confirm_settings_dirty_leave()
            if outcome == "cancel":
                return
            if outcome == "save":
                self._save_settings()
                if self._settings_dirty:
                    return
            elif outcome == "discard":
                self._settings_dirty = False
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
    """Launch the control window (with startup splash)."""
    from coc_bot.gui.bootstrap import run_gui as _run_gui_with_splash

    _run_gui_with_splash(
        dry_run=dry_run,
        debug_save_frames=debug_save_frames,
        debug=debug,
    )
