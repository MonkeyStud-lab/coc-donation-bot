"""Tkinter control panel for the donation bot."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
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
from coc_bot.gui.debug_actions import DEBUG_ACTIONS, run_debug_action
from coc_bot.gui.settings_fields import SETTINGS, current_setting_values, save_settings_from_gui
from coc_bot.gui.theme import (
    ACCENT,
    BG,
    BORDER,
    LOG_BG,
    LOG_FG,
    SURFACE,
    TEXT,
    TEXT_SECONDARY,
    apply_theme,
    finish_scrollable,
    make_scrollable,
    ui_font,
)


def _calibrate_script() -> Path:
    return project_root() / "scripts" / "calibrate.py"


def _open_in_terminal(command: str) -> bool:
    """Run an interactive command in a new terminal window (Linux)."""
    wrapped = f"{command}; echo; read -r -p 'Press Enter to close…'"
    candidates = [
        ["gnome-terminal", "--", "bash", "-lc", wrapped],
        ["kgx", "-e", "bash", "-lc", wrapped],
        ["xfce4-terminal", "-e", f"bash -lc {shlex.quote(wrapped)}"],
        ["konsole", "-e", "bash", "-lc", wrapped],
        ["x-terminal-emulator", "-e", "bash", "-lc", wrapped],
        ["xterm", "-e", "bash", "-lc", wrapped],
    ]
    for argv in candidates:
        if shutil.which(argv[0]) is None:
            continue
        try:
            subprocess.Popen(argv, cwd=str(project_root()))  # noqa: S603
            return True
        except OSError:
            continue
    return False


class BotControlApp(tk.Tk):
    def __init__(
        self,
        *,
        dry_run: bool = False,
        debug_save_frames: bool = False,
        debug: bool = False,
    ) -> None:
        super().__init__()
        self.title("Donation Bot")
        self.geometry("780x620")
        self.minsize(640, 500)
        apply_theme(self)

        self._dry_run = dry_run
        self._debug_save_frames = debug_save_frames
        self._debug = debug
        self._bot = None
        self._bot_thread: threading.Thread | None = None
        self._log_sink_id: int | None = None
        self._setting_vars: dict[str, tk.Variable] = {}
        self._debug_busy = False

        self._status = tk.StringVar(value="Ready — open Waydroid and Clash of Clans, then press Start")

        header = ttk.Frame(self, padding=(20, 16, 20, 8))
        header.pack(fill=tk.X)
        ttk.Label(header, text="Donation Bot", style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(
            header,
            text="Clan donations for Waydroid · Clash of Clans",
            style="Subtitle.TLabel",
        ).pack(anchor=tk.W, pady=(2, 0))
        ttk.Label(header, textvariable=self._status, style="Status.TLabel").pack(
            anchor=tk.W, pady=(10, 0)
        )

        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True, padx=16, pady=(4, 16))

        self._control_tab = ttk.Frame(notebook, padding=12)
        self._settings_tab = ttk.Frame(notebook, padding=4)
        self._calib_tab = ttk.Frame(notebook, padding=12)
        self._debug_tab = ttk.Frame(notebook, padding=4)
        notebook.add(self._control_tab, text="  Bot  ")
        notebook.add(self._settings_tab, text="  Settings  ")
        notebook.add(self._calib_tab, text="  Calibration  ")
        notebook.add(self._debug_tab, text="  Debugging  ")

        self._build_control_tab()
        self._build_settings_tab()
        self._build_calib_tab()
        self._build_debug_tab()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(400, self._refresh_calib_status)
        self.after(1000, self._refresh_farm_status)
        self._install_log_sink()

    def _card(self, parent: ttk.Frame, **pack_opts) -> ttk.Frame:
        outer = tk.Frame(parent, bg=BORDER, bd=0, highlightthickness=0)
        outer.pack(fill=tk.X, **pack_opts)
        inner = tk.Frame(outer, bg=SURFACE, bd=0, highlightthickness=0)
        inner.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        return inner

    def _build_control_tab(self) -> None:
        actions = self._card(self._control_tab, pady=(0, 12))
        pad = tk.Frame(actions, bg=SURFACE)
        pad.pack(fill=tk.X, padx=16, pady=14)

        tk.Label(
            pad,
            text="Controls",
            bg=SURFACE,
            fg=TEXT,
            font=ui_font(13, "bold"),
            anchor="w",
        ).pack(fill=tk.X)

        btns = tk.Frame(pad, bg=SURFACE)
        btns.pack(fill=tk.X, pady=(12, 0))
        self._start_btn = ttk.Button(btns, text="Start", style="Accent.TButton", command=self.start_bot)
        self._start_btn.pack(side=tk.LEFT)
        self._stop_btn = ttk.Button(
            btns, text="Stop", style="Secondary.TButton", command=self.stop_bot, state=tk.DISABLED
        )
        self._stop_btn.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            btns,
            text="View screenshot",
            style="Secondary.TButton",
            command=self.view_bot_screenshot,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            btns,
            text="Farm attack now",
            style="Secondary.TButton",
            command=self.request_farm_attack,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            btns,
            text="Close Waydroid + Clash",
            style="Danger.TButton",
            command=self.close_waydroid_and_coc,
        ).pack(side=tk.RIGHT)

        self._farm_status = tk.StringVar(value="Farm: —")
        tk.Label(
            pad,
            textvariable=self._farm_status,
            bg=SURFACE,
            fg=TEXT_SECONDARY,
            font=ui_font(10),
            anchor="w",
        ).pack(fill=tk.X, pady=(10, 0))

        log_card = self._card(self._control_tab)
        log_pad = tk.Frame(log_card, bg=SURFACE)
        log_pad.pack(fill=tk.BOTH, expand=True, padx=16, pady=14)
        tk.Label(
            log_pad,
            text="Activity",
            bg=SURFACE,
            fg=TEXT,
            font=ui_font(13, "bold"),
            anchor="w",
        ).pack(fill=tk.X)
        self._log = scrolledtext.ScrolledText(
            log_pad,
            height=16,
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

    def _build_settings_tab(self) -> None:
        canvas, inner = make_scrollable(self._settings_tab)

        intro = tk.Frame(inner, bg=BG)
        intro.pack(fill=tk.X, padx=8, pady=(8, 4))
        tk.Label(
            intro,
            text="Settings",
            bg=BG,
            fg=TEXT,
            font=ui_font(13, "bold"),
            anchor="w",
        ).pack(fill=tk.X)
        tk.Label(
            intro,
            text="Saved to data/user_settings.yaml. Stop and Start the bot after saving "
            "so a running loop picks up changes.",
            bg=BG,
            fg=TEXT_SECONDARY,
            font=ui_font(10),
            wraplength=700,
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X, pady=(4, 8))

        values = current_setting_values()
        current_section = None
        for field in SETTINGS:
            if field.section != current_section:
                current_section = field.section
                tk.Label(
                    inner,
                    text=current_section,
                    bg=BG,
                    fg=TEXT,
                    font=ui_font(12, "bold"),
                    anchor="w",
                ).pack(fill=tk.X, padx=8, pady=(16, 6))

            card = self._card(inner, padx=8, pady=4)
            block = tk.Frame(card, bg=SURFACE)
            block.pack(fill=tk.X, padx=14, pady=12)

            tk.Label(
                block,
                text=field.label,
                bg=SURFACE,
                fg=TEXT,
                font=ui_font(11, "bold"),
                anchor="w",
            ).pack(fill=tk.X)
            tk.Label(
                block,
                text=field.description,
                bg=SURFACE,
                fg=TEXT_SECONDARY,
                font=ui_font(10),
                wraplength=680,
                justify=tk.LEFT,
                anchor="w",
            ).pack(fill=tk.X, pady=(4, 8))

            if field.kind == "bool":
                var: tk.Variable = tk.BooleanVar(value=bool(values[field.key]))
                ttk.Checkbutton(block, text="Enabled", variable=var).pack(anchor=tk.W)
            else:
                var = tk.StringVar(value=str(values[field.key]))
                entry = ttk.Entry(block, textvariable=var, width=42)
                entry.pack(anchor=tk.W, ipady=2)
            self._setting_vars[field.key] = var

        btns = tk.Frame(inner, bg=BG)
        btns.pack(fill=tk.X, padx=8, pady=(16, 24))
        ttk.Button(
            btns, text="Reload", style="Secondary.TButton", command=self._reload_settings_fields
        ).pack(side=tk.LEFT)
        ttk.Button(
            btns, text="Save Settings", style="Accent.TButton", command=self._save_settings
        ).pack(side=tk.LEFT, padx=(8, 0))

        finish_scrollable(inner, canvas)

    def _reload_settings_fields(self) -> None:
        values = current_setting_values()
        for field in SETTINGS:
            var = self._setting_vars[field.key]
            if field.kind == "bool":
                var.set(bool(values[field.key]))
            else:
                var.set(str(values[field.key]))
        self._append_log("==> Settings reloaded from disk")

    def _save_settings(self) -> None:
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
        self._append_log(f"==> Settings saved to {path}")
        messagebox.showinfo(
            "Saved",
            f"Settings saved to:\n{path}\n\nStop and Start the bot to apply them to a running loop.",
        )

    def _build_calib_tab(self) -> None:
        tk.Label(
            self._calib_tab,
            text="Calibration runs in a separate terminal (OpenCV pickers). "
            "Open Waydroid and Clash first.",
            bg=BG,
            fg=TEXT_SECONDARY,
            font=ui_font(10),
            wraplength=700,
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X, pady=(0, 10))

        card = self._card(self._calib_tab, pady=(0, 10))
        tree_wrap = tk.Frame(card, bg=SURFACE)
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

        row = tk.Frame(self._calib_tab, bg=BG)
        row.pack(fill=tk.X, pady=(4, 0))
        ttk.Button(
            row, text="Refresh", style="Secondary.TButton", command=self._refresh_calib_status
        ).pack(side=tk.LEFT)
        ttk.Button(
            row,
            text="Recalibrate Selected",
            style="Secondary.TButton",
            command=self._recalibrate_selected,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            row, text="Recalibrate All", style="Accent.TButton", command=self._recalibrate_all
        ).pack(side=tk.LEFT, padx=(8, 0))

        self._calib_detail = tk.StringVar(value="")
        tk.Label(
            self._calib_tab,
            textvariable=self._calib_detail,
            bg=BG,
            fg=TEXT_SECONDARY,
            font=ui_font(10),
            wraplength=700,
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X, pady=(12, 0))
        self._calib_tree.bind("<<TreeviewSelect>>", self._on_calib_select)

    def _build_debug_tab(self) -> None:
        canvas, inner = make_scrollable(self._debug_tab)

        intro = tk.Frame(inner, bg=BG)
        intro.pack(fill=tk.X, padx=8, pady=(8, 4))
        tk.Label(
            intro,
            text="Debugging",
            bg=BG,
            fg=TEXT,
            font=ui_font(13, "bold"),
            anchor="w",
        ).pack(fill=tk.X)
        tk.Label(
            intro,
            text="Run one step at a time. Stop the bot first so tests do not conflict. "
            "Results also appear in the Bot tab log.",
            bg=BG,
            fg=TEXT_SECONDARY,
            font=ui_font(10),
            wraplength=700,
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X, pady=(4, 8))

        for action_id, label, description in DEBUG_ACTIONS:
            card = self._card(inner, padx=8, pady=4)
            block = tk.Frame(card, bg=SURFACE)
            block.pack(fill=tk.X, padx=14, pady=12)
            ttk.Button(
                block,
                text=label,
                style="Secondary.TButton",
                command=lambda aid=action_id: self._run_debug(aid),
            ).pack(anchor=tk.W)
            tk.Label(
                block,
                text=description,
                bg=SURFACE,
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
                "Stop the bot before running debug actions so they do not conflict.",
            )
            return
        if self._debug_busy:
            return
        self._debug_busy = True
        self._debug_result.set(f"Running {action_id}…")
        self._append_log(f"==> Debug: {action_id}")

        def worker() -> None:
            result = run_debug_action(action_id)
            logger.info("Debug {}: {}", action_id, result)

            def done() -> None:
                self._debug_busy = False
                self._debug_result.set(result)
                self._append_log(result)

            self.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    def _install_log_sink(self) -> None:
        def sink(message: str) -> None:
            self.after(0, lambda m=message: self._append_log(m.rstrip()))

        self._log_sink_id = logger.add(sink, format="{time:HH:mm:ss} | {level:<7} | {message}")

    def _append_log(self, line: str) -> None:
        self._log.configure(state=tk.NORMAL)
        self._log.insert(tk.END, line + "\n")
        self._log.see(tk.END)
        self._log.configure(state=tk.DISABLED)

    def _bot_running(self) -> bool:
        return self._bot_thread is not None and self._bot_thread.is_alive()

    def start_bot(self) -> None:
        if self._bot_running():
            return
        config = load_config()
        if not config.calibrated:
            messagebox.showerror(
                "Not calibrated",
                "Calibration is incomplete. Open the Calibration tab and run the missing steps.",
            )
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
        if not self._bot_running():
            self._on_bot_stopped()
            return
        self._status.set("Stopping…")
        self._append_log("==> Stop requested (Clash stays open)")
        bot = self._bot
        if bot is not None:
            bot.request_stop()

    def request_farm_attack(self) -> None:
        """Queue a farm attack on the running bot, or run a one-shot if stopped."""
        config = load_config()
        if not config.farm_calibrated:
            messagebox.showerror(
                "Farm not calibrated",
                "Open Calibration → Farm and set attack_button, unranked Battle, and Return Home.\n"
                "Leave electro dragons as the active army preset.",
            )
            return

        bot = self._bot
        if self._bot_running() and bot is not None:
            bot.request_farm_attack()
            self._append_log("==> Farm attack queued (runs when not mid-donation)")
            self._farm_status.set(bot.farm_status_line())
            return

        if not messagebox.askyesno(
            "Farm attack now",
            "Bot is not running. Run one unranked farm attack now?\n\n"
            "This will leave chat, Attack → Battle, deploy along the edge, "
            "and wait for the timer to end.",
        ):
            return

        self._append_log("==> Running one-shot farm attack…")
        self._farm_status.set("Farm: running one-shot…")

        def worker() -> None:
            try:
                from coc_bot.attack.farmer import AttackFarmer
                from coc_bot.adb.capture import ScreenCapture
                from coc_bot.adb.client import AdbClient
                from coc_bot.adb.input import InputController
                from coc_bot.donation.navigator import Navigator
                from coc_bot.vision.matcher import TemplateMatcher

                cfg = load_config()
                client = AdbClient(device=cfg.adb_device)
                client.health_check()
                capture = ScreenCapture(client)
                inp = InputController(
                    client,
                    jitter_px=cfg.tap_jitter_px,
                    delay_ms=cfg.action_delay_ms,
                    dry_run=False,
                )
                capture.bind_input(inp)
                matcher = TemplateMatcher(
                    threshold=cfg.template_threshold,
                    scale_range=cfg.scale_range,
                )
                nav = Navigator(cfg, capture, inp, matcher)
                result = AttackFarmer(cfg, capture, inp, matcher, nav).run_one_attack()
                if result.success:
                    from coc_bot.runtime.tracker import RuntimeTracker

                    RuntimeTracker(cfg).mark_farm_success()
                msg = f"Farm one-shot: success={result.success} ({result.reason})"
                logger.info(msg)

                def done() -> None:
                    self._append_log(msg)
                    self._refresh_farm_status()
                    if result.success:
                        messagebox.showinfo("Farm", "Farm attack finished.")
                    else:
                        messagebox.showwarning("Farm", f"Farm failed: {result.reason}")

                self.after(0, done)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Farm one-shot failed")
                self.after(0, lambda: messagebox.showerror("Farm error", str(exc)))
                self.after(0, self._refresh_farm_status)

        threading.Thread(target=worker, daemon=True).start()

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
                    self._farm_status.set("Farm: needs calibration")
                else:
                    from coc_bot.runtime.tracker import RuntimeTracker

                    tracker = RuntimeTracker(config)
                    since = tracker.seconds_since_last_farm()
                    interval = max(60, int(config.farm_interval_seconds))
                    if since is None:
                        self._farm_status.set("Farm: ready (bot stopped)")
                    else:
                        remaining = max(0, int(interval - since))
                        if remaining <= 0:
                            self._farm_status.set("Farm: due when bot starts")
                        else:
                            self._farm_status.set(
                                f"Farm: next auto in {remaining // 60}m {remaining % 60}s "
                                "(bot stopped)"
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
                from coc_bot.adb.client import AdbClient, AdbError

                config = load_config()
                client = AdbClient(device=config.adb_device)
                client.ensure_connected()
                frame = ScreenCapture(client).screenshot()
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image = Image.fromarray(rgb)
                # Fit in a readable preview without huge windows.
                image.thumbnail((960, 540), Image.Resampling.LANCZOS)
                h, w = frame.shape[:2]

                def show() -> None:
                    win = tk.Toplevel(self)
                    win.title(f"Bot view — {w}×{h}")
                    win.configure(bg=BG)
                    photo = ImageTk.PhotoImage(image)
                    # Keep a reference so Tk does not garbage-collect the image.
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
            f"{done}/{total} steps configured. Expand a step to see each part; "
            "Recalibrate Selected runs that whole step."
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
            self._calib_detail.set(
                f"{step.title} → {part.label}{opt}\n"
                f"Status: {status} · key: {part.key} · type: {part.kind}{extra}\n\n"
                f"Recalibrate Selected runs the full “{step.title}” wizard step."
            )
            return
        status = self._calib_tree.set(iid, "status")
        parts_line = ", ".join(p.label for p in step.parts) if step.parts else step.summary
        self._calib_detail.set(
            f"{step.title} — {status}\n{step.summary}\nParts: {parts_line}"
        )

    def _recalibrate_selected(self) -> None:
        sel = self._calib_tree.selection()
        if not sel:
            messagebox.showinfo("Select a step", "Select a calibration step or part in the list first.")
            return
        step_id = parent_step_id(sel[0])
        self._launch_calibrate(["--step", step_id])

    def _recalibrate_all(self) -> None:
        if not messagebox.askyesno(
            "Recalibrate all",
            "Run the full calibration wizard in a new terminal? Existing values can be kept per prompt.",
        ):
            return
        self._launch_calibrate(["--all"])

    def _launch_calibrate(self, extra_args: list[str]) -> None:
        script = _calibrate_script()
        if not script.exists():
            messagebox.showerror("Missing script", f"Not found: {script}")
            return
        py = sys.executable
        cmd = (
            f"cd {shlex.quote(str(project_root()))} && {shlex.quote(py)} "
            f"{shlex.quote(str(script))} "
            + " ".join(shlex.quote(a) for a in extra_args)
        )
        self._append_log(f"==> Opening calibration terminal: {' '.join(extra_args)}")
        if not _open_in_terminal(cmd):
            messagebox.showerror(
                "No terminal",
                "Could not open a terminal emulator.\n"
                f"Run manually:\n{py} {script} {' '.join(extra_args)}",
            )
            return
        messagebox.showinfo(
            "Calibration started",
            "A terminal opened for calibration.\n"
            "When finished, click Refresh on the Calibration tab.",
        )

    def _on_close(self) -> None:
        if self._bot_running():
            if not messagebox.askyesno("Quit", "Bot is running. Stop it and quit?"):
                return
            self.stop_bot()
            if self._bot_thread is not None:
                self._bot_thread.join(timeout=3.0)
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
