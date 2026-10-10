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
from coc_bot.gui.theme import bind_yview_mousewheel, finish_scrollable, make_scrollable, theme_label, ui_font
from coc_bot.gui.ux_helpers import FIXIT_RECIPES, settings_snapshot
from coc_bot.gui.widgets import ToggleSwitch



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

        self._build_data_tools(inner)

        for group_title, actions in DEBUG_GROUPS:
            body = self._section_header(inner, f"tools:{group_title}", group_title)

            for action_id, label, description in actions:
                card = self._card(body, padx=8, pady=4 if self._modern else 5)
                block = tk.Frame(card, bg=theme.SURFACE_2)
                block.pack(fill=tk.X, padx=14, pady=12)
                allow_while_running = action_id in {"install_desktop_shortcut", "open_collection_review"}
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
