"""View builders for the control panel; behavior lives on the app controller."""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk

from loguru import logger

from coc_bot.config import load_config
from coc_bot.gui.debug_actions import DEBUG_GROUPS
import coc_bot.gui.theme as theme
from coc_bot.gui.settings_fields import SETTINGS, current_setting_values, is_raw_timing_field
from coc_bot.gui.theme import bind_yview_mousewheel, finish_scrollable, make_scrollable, ui_font
from coc_bot.gui.ux_helpers import FIXIT_RECIPES, settings_snapshot
from coc_bot.gui.widgets import HelpTip, ToggleSwitch



class PageViewsMixin:
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
            text="Diagnostics",
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
        for column in range(3):
            ob_btns.columnconfigure(column, weight=1, uniform="onboarding")
        for index, (label, callback, kind) in enumerate((
            ("Connect ADB", self.connect_adb, "Secondary"),
            ("Pick device", self._pick_adb_device, "Secondary"),
            ("Go to Setup", lambda: self._show_page("setup"), "Secondary"),
            ("Calibrate missing", self.calibrate_whats_missing, "Accent"),
            ("Dismiss", self._exit_first_launch_preview, "Secondary"),
        )):
            button = ttk.Button(ob_btns, text=label, style=self._btn_style(kind), command=callback)
            button.grid(row=index // 3, column=index % 3, sticky="ew", padx=4, pady=4)
            if label == "Dismiss":
                self._onboarding_dismiss_btn = button
        onboarding_outer.pack_forget()

        actions_outer, actions = self._card(page, pady=(0, 12), return_outer=True)
        self._home_anchor = actions_outer
        pad = tk.Frame(actions, bg=theme.SURFACE_2)
        pad_x = 18 if self._modern else 16
        pad_y = 16 if self._modern else 14
        pad.pack(fill=tk.X, padx=pad_x, pady=pad_y)

        play_header = tk.Frame(pad, bg=theme.SURFACE_2)
        play_header.pack(fill=tk.X)
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
            text="Farm attack now",
            style=self._btn_style("Secondary"),
            command=self.request_farm_attack,
        ).pack(side=tk.LEFT, padx=(8, 0))

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
            text="Next farm attack",
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
            font=ui_font(20, "bold"),
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
            font=ui_font(20, "bold"),
            anchor="w",
        )
        self._break_timer_label.pack(anchor=tk.W)

        log_card = self._card(page, fill=tk.BOTH, expand=True)
        log_pad = tk.Frame(log_card, bg=theme.SURFACE_2)
        log_pad.pack(fill=tk.BOTH, expand=True, padx=16, pady=14)
        log_header = tk.Frame(log_pad, bg=theme.SURFACE_2)
        log_header.pack(fill=tk.X)
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


    def _build_settings_page(self) -> None:
        page = self._pages["settings"]
        for child in page.winfo_children():
            child.destroy()
        self._setting_vars.clear()
        self._setting_hint_labels.clear()
        self._clear_wrap_labels("settings")
        actions = tk.Frame(page, bg=theme.BG)
        actions.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=12)
        ttk.Button(actions, text="Reload", style=self._btn_style("Secondary"),
                   command=self._reload_settings_fields).pack(side=tk.LEFT)
        ttk.Button(actions, text="Save changes", style=self._btn_style("Accent"),
                   command=self._save_settings).pack(side=tk.RIGHT)
        notebook = ttk.Notebook(page)
        notebook.pack(fill=tk.BOTH, expand=True, padx=8)
        self._settings_notebook = notebook
        self._settings_canvases = []
        bodies = {}
        for name in ("Routine", "Breaks", "Appearance", "Advanced"):
            tab = ttk.Frame(notebook)
            notebook.add(tab, text=name)
            canvas, body = make_scrollable(tab)
            self._settings_canvases.append(canvas)
            bodies[name] = (canvas, body)
        self._settings_canvas = self._settings_canvases[0]
        values = current_setting_values()
        dev = bool(values.get("gui_dev_options", False))
        routine = {"donate_open_requests", "gui_timing_preset", "farm_enabled", "farm_interval_seconds"}
        breaks = {"session_limit_seconds", "break_min_seconds", "break_max_seconds"}
        appearance = {"gui_theme", "gui_show_debug_activity", "gui_practice_mode", "gui_dev_options"}
        for field in SETTINGS:
            if is_raw_timing_field(field.key) and not dev:
                continue
            name = ("Routine" if field.key in routine else "Breaks" if field.key in breaks
                    else "Appearance" if field.key in appearance else "Advanced")
            self._add_setting_row_modern(bodies[name][1], field, values[field.key])
        sequence_card = self._card(bodies["Routine"][1], padx=8, pady=4)
        sequence_row = tk.Frame(sequence_card, bg=theme.SURFACE_2)
        sequence_row.pack(fill=tk.X, padx=16, pady=14)
        self._add_tools_row_modern(sequence_row, title="Deployment sequence",
                                   description="Choose the ordered army-bar and map taps used for farm attacks.",
                                   button_text="Edit", command=self._open_sequence_setup)
        for canvas, body in bodies.values():
            finish_scrollable(body, canvas)
        notebook.bind("<<NotebookTabChanged>>", lambda _e: self._refresh_scroll_regions(), add="+")
        self._settings_baseline = settings_snapshot({key: var.get() for key, var in self._setting_vars.items()})
        self._settings_dirty = False
        for var in self._setting_vars.values():
            var.trace_add("write", lambda *_a: self._mark_settings_dirty())

    def _open_sequence_setup(self) -> None:
        self._show_page("setup")
        if self._page != "setup":  # Unsaved-settings dialog was cancelled.
            return
        self._refresh_calib_status()
        target = "farm::deploy_sequence"
        if self._calib_tree.exists(target):
            self._calib_tree.item("farm", open=True)
            self._calib_tree.selection_set(target)
            self._calib_tree.see(target)
            self._on_calib_select()


    def _build_setup_page(self) -> None:
        page = self._pages["setup"]
        for child in page.winfo_children():
            child.destroy()
        self._clear_wrap_labels("setup")

        canvas, inner = make_scrollable(page)
        self._setup_canvas = canvas

        intro = tk.Frame(inner, bg=theme.BG)
        intro.pack(fill=tk.X, padx=8, pady=4)
        progress_label = tk.Label(
            intro,
            textvariable=self._calib_progress,
            bg=theme.BG,
            fg=theme.ACCENT,
            font=ui_font(11, "bold"),
            anchor="w",
        )
        progress_label.pack(fill=tk.X, pady=(0, 8))

        checklist_body = inner
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

        actions_card = self._card(page, side=tk.BOTTOM, padx=8, pady=8)
        actions_pad = tk.Frame(actions_card, bg=theme.SURFACE_2)
        actions_pad.pack(fill=tk.X, padx=14, pady=12)
        for column in range(3):
            actions_pad.columnconfigure(column, weight=1, uniform="setup_actions")
        for index, (label, callback, kind) in enumerate((
            ("Calibrate missing", self.calibrate_whats_missing, "Accent"),
            ("Recalibrate selected", self._recalibrate_selected, "Secondary"),
            ("Recalibrate all", self._recalibrate_all, "Secondary"),
            ("Refresh", self._refresh_calib_status, "Secondary"),
            ("Terminal calibrator", self._classic_calibrate_selected, "Secondary"),
            ("Saved calibrations", lambda: self._show_page("library"), "Secondary"),
        )):
            ttk.Button(actions_pad, text=label, command=callback, style=self._btn_style(kind)).grid(
                row=index // 3, column=index % 3, sticky="ew", padx=4, pady=4)

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
        screenshot_card = self._card(inner, padx=8, pady=(4, 12))
        block = tk.Frame(screenshot_card, bg=theme.SURFACE_2)
        block.pack(fill=tk.X, padx=16, pady=16)
        self._add_tools_row_modern(block, title="Current screenshot", description="View the latest bot image on demand.",
                                   button_text="View", command=self.view_bot_screenshot)
        close = ttk.Button(block, text="Close Waydroid + Clash", style=self._btn_style("Danger"),
                           command=self.close_waydroid_and_coc)
        close.grid(row=1, column=0, columnspan=2, sticky="e", pady=(12, 0))
        notebook = ttk.Notebook(inner)
        notebook.pack(fill=tk.X, padx=8)
        actions = ttk.Frame(notebook, padding=16)
        notebook.add(actions, text="Actions")
        options = {label: (action_id, description) for _group, entries in DEBUG_GROUPS
                   for action_id, label, description in entries}
        choice = self._str_var(next(iter(options)))
        selector = ttk.Combobox(actions, textvariable=choice, values=list(options), state="readonly", width=38)
        selector.pack(fill=tk.X, pady=(0, 12))
        tip = HelpTip(selector, options[choice.get()][1])
        run = ttk.Button(actions, text="Run selected action", style=self._btn_style("Accent"),
                         command=lambda: self._run_debug(options[choice.get()][0]))
        run.pack(anchor=tk.E)
        run._allow_while_running = False
        self._tool_buttons.append(run)
        def changed(_event=None):
            action_id, description = options[choice.get()]
            tip.text = description
            tip.hide()
            run._allow_while_running = action_id in {"install_desktop_shortcut", "open_collection_review"}
            self._update_tool_buttons_state()
        selector.bind("<<ComboboxSelected>>", changed)
        recovery = ttk.Frame(notebook, padding=16)
        notebook.add(recovery, text="Recovery")
        recipes = {recipe.title: recipe for recipe in FIXIT_RECIPES}
        recipe_var = self._str_var(next(iter(recipes)))
        recipe_box = ttk.Combobox(recovery, textvariable=recipe_var, values=list(recipes), state="readonly", width=38)
        recipe_box.pack(fill=tk.X, pady=(0, 12))
        recipe_tip = HelpTip(recipe_box, recipes[recipe_var.get()].body)
        fix = ttk.Button(recovery, text=recipes[recipe_var.get()].action_label,
                         style=self._btn_style("Secondary"), command=lambda: self._run_fixit(recipes[recipe_var.get()]))
        fix.pack(anchor=tk.E)
        fix._allow_while_running = False
        self._tool_buttons.append(fix)
        def recipe_changed(_event=None):
            recipe = recipes[recipe_var.get()]
            recipe_tip.text = recipe.body
            recipe_tip.hide()
            fix.configure(text=recipe.action_label)
        recipe_box.bind("<<ComboboxSelected>>", recipe_changed)
        if bool(load_config().gui_dev_options):
            developer = tk.Frame(notebook, bg=theme.BG)
            notebook.add(developer, text="Developer")
            self._build_tools_dev_section(developer)
        self._debug_result = self._str_var("")
        result = tk.Label(inner, textvariable=self._debug_result, bg=theme.BG, fg=theme.ACCENT,
                          font=ui_font(11), anchor="w", justify=tk.LEFT, wraplength=400)
        result.pack(fill=tk.X, padx=12, pady=16)
        self._track_wrap_label(result, reserve=40, page_id="tools")
        finish_scrollable(inner, canvas)
        self._update_tool_buttons_state()


    def _build_tools_dev_section(self, inner: tk.Frame) -> None:
        """Dev-only Tools rows (Settings → Appearance → Dev options)."""
        body = inner
        preview_on = bool(self._gui_state.first_launch_preview)
        status = "ON" if preview_on else "off"
        stash = self._gui_state.first_launch_calib_stash
        stash_note = f" Stash: {stash}." if stash else ""
        rows = (
            (
                "Simulate first launch",
                "Show Dashboard “Get started”, then optionally stash & clear calibration "
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
            run_btn = self._add_tools_row_modern(
                block, title=title, description=description,
                button_text=button_text, command=command,
            )
            run_btn._allow_while_running = allow_while_running  # type: ignore[attr-defined]
            self._tool_buttons.append(run_btn)


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
                from coc_bot.adb.capture_coordinator import latest_frame
                snapshot = latest_frame(config.adb_device)
                if self._bot_running() or self._farm_oneshot_running():
                    if snapshot is None:
                        raise RuntimeError("The bot has not captured a frame yet. Try again shortly.")
                    frame, age = snapshot
                    caption = f"Latest bot frame — captured {age:.1f} seconds ago"
                else:
                    from coc_bot.runtime.device_lease import DeviceLease
                    with DeviceLease(config.adb_device):
                        client = AdbClient(device=config.adb_device)
                        client.ensure_connected()
                        frame = ScreenCapture(client).screenshot()
                    caption = "Current ADB screenshot"
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
                        text=caption,
                        bg=theme.BG,
                        fg=theme.TEXT_SECONDARY,
                        font=ui_font(10),
                    ).pack(anchor=tk.W, padx=16, pady=(12, 4))
                    tk.Label(win, image=photo, bg=theme.BG, bd=0).pack(padx=16, pady=(0, 16))
                    self._append_log(f"==> Screenshot preview {w}×{h}")

                self.after(0, show)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Screenshot preview failed: {}", exc)
                err = str(exc)
                self.after(0, lambda e=err: messagebox.showerror("Screenshot failed", e))
                self.after(0, lambda e=err: self._append_log(f"Screenshot failed: {e}"))

        threading.Thread(target=worker, daemon=True).start()
