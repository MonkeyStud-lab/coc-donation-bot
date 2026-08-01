"""Steam-inspired Tkinter control panel for the donation bot."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from loguru import logger

from coc_bot.calibration.wizard import (
    STEP_IDS,
    STEPS,
    CalibrationWizard,
    parent_step_id,
    part_is_configured,
)
from coc_bot.config import load_config, project_root, user_settings_path
from coc_bot.gui.debug_actions import DEBUG_ACTIONS, DebugSession, run_debug_action
from coc_bot.gui.settings_fields import SETTINGS, current_setting_values, save_settings_from_gui
from coc_bot.gui.theme import (
    ACCENT,
    BG,
    LOG_BG,
    LOG_FG,
    SIDEBAR,
    SURFACE,
    SURFACE_2,
    TEXT,
    TEXT_SECONDARY,
    apply_theme,
    finish_scrollable,
    make_scrollable,
    ui_font,
)
from coc_bot.gui.util import calibrate_script, open_in_terminal
from coc_bot.gui.widgets import ToggleSwitch

PAGES = (
    ("home", "Home", "Start the bot, farm, and watch activity"),
    ("settings", "Settings", "Timing, donations, farm, and breaks"),
    ("setup", "Setup", "Teach the bot where buttons are on your screen"),
    ("tools", "Tools", "One-shot tests when something looks wrong"),
)


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
        self.geometry("960x680")
        self.minsize(820, 560)
        apply_theme(self)

        self._dry_run = dry_run
        self._debug_save_frames = debug_save_frames
        self._debug = debug
        self._bot = None
        self._bot_thread: threading.Thread | None = None
        self._farm_oneshot_thread: threading.Thread | None = None
        self._farm_oneshot_stop = threading.Event()
        self._log_sink_id: int | None = None
        self._setting_vars: dict[str, tk.Variable] = {}
        self._debug_busy = False
        self._page = "home"
        self._nav_buttons: dict[str, ttk.Button] = {}
        self._pages: dict[str, ttk.Frame] = {}
        self._page_title = tk.StringVar(value="Home")
        self._page_subtitle = tk.StringVar(value=PAGES[0][2])
        self._status = tk.StringVar(
            value="Ready — open Waydroid and Clash of Clans, then press Start"
        )
        self._ui_style = load_config().gui_ui_style
        self._settings_canvas: tk.Canvas | None = None

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

        for page_id, _label, _subtitle in PAGES:
            page = ttk.Frame(self._content)
            self._pages[page_id] = page

        self._build_home_page()
        self._build_settings_page()
        self._build_setup_page()
        self._build_tools_page()

        status = ttk.Frame(right, style="StatusBar.TFrame", padding=(16, 8))
        status.pack(fill=tk.X, side=tk.BOTTOM)
        ttk.Label(status, textvariable=self._status, style="Status.TLabel").pack(anchor=tk.W)

        self._show_page("home")
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(400, self._refresh_calib_status)
        self.after(1000, self._refresh_farm_status)
        self._install_log_sink()

    def _build_sidebar(self, parent: ttk.Frame) -> None:
        side = tk.Frame(parent, bg=SIDEBAR, width=200)
        side.pack(side=tk.LEFT, fill=tk.Y)
        side.pack_propagate(False)

        brand = tk.Frame(side, bg=SIDEBAR)
        brand.pack(fill=tk.X, padx=16, pady=(20, 24))
        tk.Label(
            brand,
            text="DONATION BOT",
            bg=SIDEBAR,
            fg=TEXT,
            font=ui_font(13, "bold"),
            anchor="w",
        ).pack(fill=tk.X)
        tk.Label(
            brand,
            text="Clash of Clans · Waydroid",
            bg=SIDEBAR,
            fg=TEXT_SECONDARY,
            font=ui_font(9),
            anchor="w",
        ).pack(fill=tk.X, pady=(4, 0))

        tk.Label(
            side,
            text="LIBRARY",
            bg=SIDEBAR,
            fg=TEXT_SECONDARY,
            font=ui_font(8, "bold"),
            anchor="w",
        ).pack(fill=tk.X, padx=16, pady=(0, 6))

        for page_id, label, _subtitle in PAGES:
            btn = ttk.Button(
                side,
                text=label,
                style="Nav.TButton",
                command=lambda pid=page_id: self._show_page(pid),
            )
            btn.pack(fill=tk.X, padx=8, pady=1)
            self._nav_buttons[page_id] = btn

    def _show_page(self, page_id: str) -> None:
        self._page = page_id
        for pid, frame in self._pages.items():
            if pid == page_id:
                frame.pack(fill=tk.BOTH, expand=True)
            else:
                frame.pack_forget()
        for pid, btn in self._nav_buttons.items():
            btn.configure(style="NavSelected.TButton" if pid == page_id else "Nav.TButton")
        for pid, label, subtitle in PAGES:
            if pid == page_id:
                self._page_title.set(label)
                self._page_subtitle.set(subtitle)
                break

    @property
    def _modern(self) -> bool:
        return self._ui_style != "classic"

    def _btn_style(self, kind: str) -> str:
        """Map Accent/Secondary/Danger/Play → modern or classic ttk style name."""
        if self._modern:
            return {
                "Accent": "Modern.Accent.TButton",
                "Secondary": "Modern.Secondary.TButton",
                "Danger": "Modern.Danger.TButton",
                "Play": "Modern.Play.TButton",
            }.get(kind, "Modern.Secondary.TButton")
        return {
            "Accent": "Accent.TButton",
            "Secondary": "Secondary.TButton",
            "Danger": "Danger.TButton",
            "Play": "Play.TButton",
        }.get(kind, "Secondary.TButton")

    def _card(self, parent: tk.Misc, **pack_opts) -> tk.Frame:
        outer = tk.Frame(parent, bg=SURFACE, bd=0, highlightthickness=0)
        fill = pack_opts.pop("fill", tk.X)
        outer.pack(fill=fill, **pack_opts)
        inner = tk.Frame(outer, bg=SURFACE_2, bd=0, highlightthickness=0)
        inner.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        return inner

    def _build_home_page(self) -> None:
        page = self._pages["home"]
        actions = self._card(page, pady=(0, 12))
        pad = tk.Frame(actions, bg=SURFACE_2)
        pad_x = 18 if self._modern else 16
        pad_y = 16 if self._modern else 14
        pad.pack(fill=tk.X, padx=pad_x, pady=pad_y)

        tk.Label(
            pad,
            text="Play",
            bg=SURFACE_2,
            fg=TEXT,
            font=ui_font(13, "bold"),
            anchor="w",
        ).pack(fill=tk.X)

        primary = tk.Frame(pad, bg=SURFACE_2)
        primary.pack(fill=tk.X, pady=(12, 0))
        self._start_btn = ttk.Button(
            primary, text="▶  Start", style=self._btn_style("Play"), command=self.start_bot
        )
        self._start_btn.pack(side=tk.LEFT)
        self._stop_btn = ttk.Button(
            primary,
            text="Stop",
            style=self._btn_style("Secondary"),
            command=self.stop_bot,
            state=tk.DISABLED,
        )
        self._stop_btn.pack(side=tk.LEFT, padx=(10, 0))

        secondary = tk.Frame(pad, bg=SURFACE_2)
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

        self._farm_status = tk.StringVar(value="Farm: —")
        tk.Label(
            pad,
            textvariable=self._farm_status,
            bg=SURFACE_2,
            fg=TEXT_SECONDARY,
            font=ui_font(10),
            anchor="w",
        ).pack(fill=tk.X, pady=(12, 0))

        log_card = self._card(page, fill=tk.BOTH, expand=True)
        log_pad = tk.Frame(log_card, bg=SURFACE_2)
        log_pad.pack(fill=tk.BOTH, expand=True, padx=16, pady=14)
        tk.Label(
            log_pad,
            text="Activity",
            bg=SURFACE_2,
            fg=TEXT,
            font=ui_font(13, "bold"),
            anchor="w",
        ).pack(fill=tk.X)
        self._log = scrolledtext.ScrolledText(
            log_pad,
            height=18,
            state=tk.DISABLED,
            wrap=tk.WORD,
            font=ui_font(10),
            bg=LOG_BG,
            fg=LOG_FG,
            insertbackground=LOG_FG,
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=0,
            padx=12,
            pady=10,
        )
        self._log.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

    def _build_settings_page(self) -> None:
        page = self._pages["settings"]
        for child in page.winfo_children():
            child.destroy()
        self._setting_vars.clear()

        canvas, inner = make_scrollable(page)
        self._settings_canvas = canvas

        intro = tk.Frame(inner, bg=BG)
        intro.pack(fill=tk.X, padx=8, pady=(4, 4))
        style_note = (
            "Modern layout (Cursor-like rows). Switch to classic under Interface if you prefer."
            if self._modern
            else "Classic layout (original stacked cards)."
        )
        tk.Label(
            intro,
            text="Changes are saved to data/user_settings.yaml. Stop and Start the bot "
            f"after saving so a running loop picks them up. {style_note}",
            bg=BG,
            fg=TEXT_SECONDARY,
            font=ui_font(10),
            wraplength=700,
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X, pady=(0, 8))

        values = current_setting_values()
        current_section = None
        for field in SETTINGS:
            if field.section != current_section:
                current_section = field.section
                tk.Label(
                    inner,
                    text=current_section.upper(),
                    bg=BG,
                    fg=ACCENT,
                    font=ui_font(10, "bold"),
                    anchor="w",
                ).pack(fill=tk.X, padx=8, pady=(18, 8))

            if self._modern:
                self._add_setting_row_modern(inner, field, values[field.key])
            else:
                self._add_setting_row_classic(inner, field, values[field.key])

        btns = tk.Frame(inner, bg=BG)
        btns.pack(fill=tk.X, padx=8, pady=(16, 24))
        ttk.Button(
            btns,
            text="Reload",
            style=self._btn_style("Secondary"),
            command=self._reload_settings_fields,
        ).pack(side=tk.LEFT)
        ttk.Button(
            btns,
            text="Save Settings",
            style=self._btn_style("Accent"),
            command=self._save_settings,
        ).pack(side=tk.LEFT, padx=(8, 0))

        finish_scrollable(inner, canvas)

    def _add_setting_row_classic(self, parent: tk.Misc, field, value) -> None:
        """Original stacked card: label → description → control."""
        card = self._card(parent, padx=8, pady=5)
        block = tk.Frame(card, bg=SURFACE_2)
        block.pack(fill=tk.X, padx=14, pady=12)

        tk.Label(
            block,
            text=field.label,
            bg=SURFACE_2,
            fg=TEXT,
            font=ui_font(11, "bold"),
            anchor="w",
        ).pack(fill=tk.X)
        tk.Label(
            block,
            text=field.description,
            bg=SURFACE_2,
            fg=TEXT_SECONDARY,
            font=ui_font(10),
            wraplength=680,
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X, pady=(4, 8))

        if field.kind == "bool":
            var: tk.Variable = tk.BooleanVar(value=bool(value))
            ttk.Checkbutton(block, text="Enabled", variable=var).pack(anchor=tk.W)
            self._setting_vars[field.key] = var
        else:
            var = tk.StringVar(value=str(value))
            entry = ttk.Entry(block, textvariable=var, width=42)
            entry.pack(anchor=tk.W, ipady=2)
            self._setting_vars[field.key] = var

    def _add_setting_row_modern(self, parent: tk.Misc, field, value) -> None:
        """Cursor-like row: title/description left, control right."""
        card = self._card(parent, padx=8, pady=4)
        block = tk.Frame(card, bg=SURFACE_2)
        block.pack(fill=tk.X, padx=16, pady=14)
        block.columnconfigure(0, weight=1)

        left = tk.Frame(block, bg=SURFACE_2)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        tk.Label(
            left,
            text=field.label,
            bg=SURFACE_2,
            fg=TEXT,
            font=ui_font(12),
            anchor="w",
        ).pack(fill=tk.X)
        tk.Label(
            left,
            text=field.description,
            bg=SURFACE_2,
            fg=TEXT_SECONDARY,
            font=ui_font(10),
            wraplength=520,
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X, pady=(4, 0))

        right = tk.Frame(block, bg=SURFACE_2)
        right.grid(row=0, column=1, sticky="ne")

        if field.kind == "bool":
            var = tk.BooleanVar(value=bool(value))
            ToggleSwitch(right, var, bg=SURFACE_2).pack(anchor=tk.E, pady=(2, 0))
            self._setting_vars[field.key] = var
        else:
            var = tk.StringVar(value=str(value))
            width = 28 if field.kind in ("int", "float") else 34
            entry = ttk.Entry(
                right, textvariable=var, width=width, style="Modern.TEntry", justify=tk.RIGHT
            )
            entry.pack(anchor=tk.E)
            self._setting_vars[field.key] = var

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
        previous_style = self._ui_style
        try:
            values: dict[str, str | bool] = {}
            for field in SETTINGS:
                var = self._setting_vars[field.key]
                values[field.key] = bool(var.get()) if field.kind == "bool" else str(var.get())
            save_settings_from_gui(values)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Invalid settings", str(exc))
            return
        path = user_settings_path()
        self._install_log_sink()
        self._append_log(f"==> Settings saved to {path}")

        new_style = str(values.get("gui_ui_style", previous_style)).strip().lower()
        if new_style in ("legacy", "old"):
            new_style = "classic"
        if new_style not in ("modern", "classic"):
            new_style = previous_style
        style_changed = new_style != previous_style
        if style_changed:
            self._ui_style = new_style
            self._build_settings_page()
            self._append_log(f"==> Settings UI style → {new_style} (restart for Home/Setup)")

        extra = ""
        if style_changed:
            extra = (
                "\n\nSettings page updated to the new style. "
                "Restart the app to refresh Home/Setup button padding."
            )
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
            "Select a step or a single part below, then Recalibrate Selected "
            "(parts skip the rest of that step). Open Waydroid and Clash first. "
            "Farm deploy sequence: Farm → Deploy tap sequence (be in battle first).",
            bg=BG,
            fg=TEXT_SECONDARY,
            font=ui_font(10),
            wraplength=720,
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X, pady=(0, 12))

        card = self._card(page, pady=(0, 10))
        tree_wrap = tk.Frame(card, bg=SURFACE_2)
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

        row = tk.Frame(page, bg=BG)
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

        self._calib_detail = tk.StringVar(value="")
        tk.Label(
            page,
            textvariable=self._calib_detail,
            bg=BG,
            fg=TEXT_SECONDARY,
            font=ui_font(10),
            wraplength=720,
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X, pady=(12, 0))
        self._calib_tree.bind("<<TreeviewSelect>>", self._on_calib_select)

    def _build_tools_page(self) -> None:
        page = self._pages["tools"]
        canvas, inner = make_scrollable(page)

        intro = tk.Frame(inner, bg=BG)
        intro.pack(fill=tk.X, padx=8, pady=(4, 4))
        tk.Label(
            intro,
            text="Run one test at a time. Stop the bot first so tests do not conflict. "
            "Results also appear in the Home activity log.",
            bg=BG,
            fg=TEXT_SECONDARY,
            font=ui_font(10),
            wraplength=700,
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X, pady=(0, 8))

        for action_id, label, description in DEBUG_ACTIONS:
            card = self._card(inner, padx=8, pady=4 if self._modern else 5)
            block = tk.Frame(card, bg=SURFACE_2)
            block.pack(fill=tk.X, padx=14, pady=12)
            if self._modern:
                block.columnconfigure(0, weight=1)
                left = tk.Frame(block, bg=SURFACE_2)
                left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
                tk.Label(
                    left,
                    text=label,
                    bg=SURFACE_2,
                    fg=TEXT,
                    font=ui_font(12),
                    anchor="w",
                ).pack(fill=tk.X)
                tk.Label(
                    left,
                    text=description,
                    bg=SURFACE_2,
                    fg=TEXT_SECONDARY,
                    font=ui_font(10),
                    wraplength=520,
                    justify=tk.LEFT,
                    anchor="w",
                ).pack(fill=tk.X, pady=(4, 0))
                ttk.Button(
                    block,
                    text="Run",
                    style=self._btn_style("Secondary"),
                    command=lambda aid=action_id: self._run_debug(aid),
                ).grid(row=0, column=1, sticky="ne")
            else:
                ttk.Button(
                    block,
                    text=label,
                    style=self._btn_style("Secondary"),
                    command=lambda aid=action_id: self._run_debug(aid),
                ).pack(anchor=tk.W)
                tk.Label(
                    block,
                    text=description,
                    bg=SURFACE_2,
                    fg=TEXT_SECONDARY,
                    font=ui_font(10),
                    wraplength=680,
                    justify=tk.LEFT,
                    anchor="w",
                ).pack(fill=tk.X, pady=(8, 0))

        self._debug_result = tk.StringVar(value="")
        tk.Label(
            inner,
            textvariable=self._debug_result,
            bg=BG,
            fg=ACCENT,
            font=ui_font(11),
            wraplength=700,
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X, padx=8, pady=(12, 24))

        finish_scrollable(inner, canvas)

    def _run_debug(self, action_id: str) -> None:
        if self._bot_running():
            messagebox.showwarning(
                "Bot running",
                "Stop the bot before running tools so they do not conflict.",
            )
            return
        if self._debug_busy:
            return
        self._debug_busy = True
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
                self._debug_busy = False
                self._debug_result.set(result)
                self._append_log(result)

            self.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    def _run_farm_program_deploy_tool(self) -> None:
        """Pan via ADB off-thread, then open the sequence editor on the UI thread."""

        def worker() -> None:
            try:
                session = DebugSession()
                prep = session.prepare_farm_program_deploy()
            except Exception as exc:  # noqa: BLE001
                logger.exception("Farm program deploy prepare failed")

                def fail() -> None:
                    self._debug_busy = False
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
                    self._debug_busy = False

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

    def _append_log(self, line: str) -> None:
        self._log.configure(state=tk.NORMAL)
        self._log.insert(tk.END, line + "\n")
        self._log.see(tk.END)
        self._log.configure(state=tk.DISABLED)

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
        config = load_config()
        if not config.calibrated:
            messagebox.showerror(
                "Not calibrated",
                "Setup is incomplete. Open Setup in the sidebar and run the missing steps.",
            )
            self._show_page("setup")
            self._refresh_calib_status()
            return

        self._start_btn.configure(state=tk.DISABLED)
        self._stop_btn.configure(state=tk.NORMAL)
        self._status.set("Bot running")
        self._append_log("==> Starting bot")

        def worker() -> None:
            try:
                from coc_bot.main import DonationBot

                self._bot = DonationBot(
                    dry_run=self._dry_run,
                    debug_save_frames=self._debug_save_frames,
                    debug=self._debug,
                )
                self.after(0, lambda: self._status.set("Bot running"))
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
                "Leave electro dragons as the active army preset.",
            )
            self._show_page("setup")
            return

        bot = self._bot
        if self._bot_running() and bot is not None:
            bot.request_farm_attack()
            self._append_log("==> Farm attack queued (runs when not mid-donation)")
            self._farm_status.set(bot.farm_status_line())
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
        self._farm_status.set("Farm: running one-shot…")

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
        self._refresh_farm_status()

    def _refresh_farm_status(self) -> None:
        try:
            bot = self._bot
            if self._bot_running() and bot is not None:
                self._farm_status.set(bot.farm_status_line())
            else:
                config = load_config()
                if not config.farm_enabled:
                    self._farm_status.set("Farm: disabled (enable in Settings)")
                elif not config.farm_calibrated:
                    self._farm_status.set("Farm: needs calibration (Setup → Farm)")
                else:
                    from coc_bot.runtime.tracker import RuntimeTracker

                    tracker = RuntimeTracker(config)
                    since = tracker.seconds_since_last_farm()
                    interval = tracker.effective_farm_interval_seconds()
                    if since is None:
                        self._farm_status.set("Farm: ready (bot stopped)")
                    else:
                        remaining = max(0, int(interval - since))
                        if remaining <= 0:
                            self._farm_status.set("Farm: due when bot starts")
                        else:
                            self._farm_status.set(
                                f"Farm: next auto in {remaining // 60}m {remaining % 60}s "
                                f"(target {interval}s, bot stopped)"
                            )
        except Exception:  # noqa: BLE001
            self._farm_status.set("Farm: —")
        self.after(5000, self._refresh_farm_status)

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
                    win.configure(bg=BG)
                    photo = ImageTk.PhotoImage(image)
                    win._photo = photo  # type: ignore[attr-defined]
                    tk.Label(
                        win,
                        text="Current ADB screencap (same source the bot uses)",
                        bg=BG,
                        fg=TEXT_SECONDARY,
                        font=ui_font(10),
                    ).pack(anchor=tk.W, padx=16, pady=(12, 4))
                    tk.Label(win, image=photo, bg=BG, bd=0).pack(padx=16, pady=(0, 16))
                    self._append_log(f"==> Screenshot preview {w}×{h}")

                self.after(0, show)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Screenshot preview failed: {}", exc)
                self.after(0, lambda: messagebox.showerror("Screenshot failed", str(exc)))
                self.after(0, lambda: self._append_log(f"Screenshot failed: {exc}"))

        threading.Thread(target=worker, daemon=True).start()

    def _on_bot_stopped(self) -> None:
        self._status.set("Ready — open Waydroid and Clash of Clans, then press Start")
        self._start_btn.configure(state=tk.NORMAL)
        self._stop_btn.configure(state=tk.DISABLED)
        self._bot_thread = None

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
            self._launch_calibrate(["--step", step_id, "--part", part_key])
            return
        self._launch_calibrate(["--step", step_id])

    def _recalibrate_all(self) -> None:
        if not messagebox.askyesno(
            "Recalibrate all",
            "Run the full setup wizard in a new terminal? Existing values can be kept per prompt.",
        ):
            return
        self._launch_calibrate(["--all"])

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
