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

from coc_bot.calibration.wizard import STEP_IDS, STEPS, CalibrationWizard
from coc_bot.config import load_config


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _calibrate_script() -> Path:
    return _project_root() / "scripts" / "calibrate.py"


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
            subprocess.Popen(argv, cwd=str(_project_root()))  # noqa: S603
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
        self.title("CoC Donation Bot")
        self.geometry("640x480")
        self.minsize(520, 400)

        self._dry_run = dry_run
        self._debug_save_frames = debug_save_frames
        self._debug = debug
        self._bot = None
        self._bot_thread: threading.Thread | None = None
        self._log_sink_id: int | None = None

        self._status = tk.StringVar(value="Ready — open Waydroid + CoC, then press Start")
        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        self._control_tab = ttk.Frame(notebook, padding=8)
        self._calib_tab = ttk.Frame(notebook, padding=8)
        notebook.add(self._control_tab, text="Bot")
        notebook.add(self._calib_tab, text="Calibration")

        self._build_control_tab()
        self._build_calib_tab()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(400, self._refresh_calib_status)
        self._install_log_sink()

    def _build_control_tab(self) -> None:
        top = ttk.Frame(self._control_tab)
        top.pack(fill=tk.X)
        ttk.Label(top, textvariable=self._status, wraplength=560).pack(side=tk.LEFT, fill=tk.X, expand=True)

        btns = ttk.Frame(self._control_tab)
        btns.pack(fill=tk.X, pady=(10, 6))
        self._start_btn = ttk.Button(btns, text="Start bot", command=self.start_bot)
        self._start_btn.pack(side=tk.LEFT)
        self._stop_btn = ttk.Button(btns, text="Stop bot", command=self.stop_bot, state=tk.DISABLED)
        self._stop_btn.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            btns,
            text="Close Waydroid + Clash",
            command=self.close_waydroid_and_coc,
        ).pack(side=tk.RIGHT)

        ttk.Label(self._control_tab, text="Log").pack(anchor=tk.W, pady=(8, 2))
        self._log = scrolledtext.ScrolledText(self._control_tab, height=16, state=tk.DISABLED, wrap=tk.WORD)
        self._log.pack(fill=tk.BOTH, expand=True)

    def _build_calib_tab(self) -> None:
        ttk.Label(
            self._calib_tab,
            text="Calibration runs in a separate terminal (needs OpenCV pickers). "
            "Open Waydroid + CoC on the right screen first.",
            wraplength=580,
        ).pack(anchor=tk.W, pady=(0, 8))

        cols = ("step", "title", "status")
        self._calib_tree = ttk.Treeview(
            self._calib_tab, columns=cols, show="headings", height=9, selectmode="browse"
        )
        self._calib_tree.heading("step", text="Step id")
        self._calib_tree.heading("title", text="Title")
        self._calib_tree.heading("status", text="Status")
        self._calib_tree.column("step", width=120, stretch=False)
        self._calib_tree.column("title", width=220)
        self._calib_tree.column("status", width=100, stretch=False)
        self._calib_tree.pack(fill=tk.BOTH, expand=True)

        row = ttk.Frame(self._calib_tab)
        row.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(row, text="Refresh", command=self._refresh_calib_status).pack(side=tk.LEFT)
        ttk.Button(row, text="Recalibrate selected", command=self._recalibrate_selected).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Button(row, text="Recalibrate all", command=self._recalibrate_all).pack(side=tk.LEFT, padx=(8, 0))

        detail = ttk.Frame(self._calib_tab)
        detail.pack(fill=tk.X, pady=(8, 0))
        self._calib_detail = tk.StringVar(value="")
        ttk.Label(detail, textvariable=self._calib_detail, wraplength=580).pack(anchor=tk.W)
        self._calib_tree.bind("<<TreeviewSelect>>", self._on_calib_select)

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
        self._status.set("Starting bot…")
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
        self._status.set("Stopping bot…")
        self._append_log("==> Stop requested (Clash stays open)")
        bot = self._bot
        if bot is not None:
            bot.request_stop()

    def _on_bot_stopped(self) -> None:
        self._status.set("Bot stopped")
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
            wizard = CalibrationWizard(load_config())
            status = wizard.step_status()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not load calibration status: {}", exc)
            status = {sid: False for sid in STEP_IDS}

        done = 0
        for step_id in STEP_IDS:
            step = STEPS[step_id]
            ok = bool(status.get(step_id))
            if ok:
                done += 1
            self._calib_tree.insert(
                "",
                tk.END,
                iid=step_id,
                values=(step_id, step.title, "Done" if ok else "Missing"),
            )
        total = len(STEP_IDS)
        self._calib_detail.set(f"{done}/{total} steps configured. Select a step for details.")

    def _on_calib_select(self, _event=None) -> None:
        sel = self._calib_tree.selection()
        if not sel:
            return
        step_id = sel[0]
        step = STEPS[step_id]
        status = self._calib_tree.set(step_id, "status")
        self._calib_detail.set(f"{step.title} — {status}\n{step.summary}")

    def _recalibrate_selected(self) -> None:
        sel = self._calib_tree.selection()
        if not sel:
            messagebox.showinfo("Select a step", "Select a calibration step in the list first.")
            return
        self._launch_calibrate(["--step", sel[0]])

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
        cmd = f"cd {shlex.quote(str(_project_root()))} && {shlex.quote(py)} {shlex.quote(str(script))} " + " ".join(
            shlex.quote(a) for a in extra_args
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
        self.destroy()


def run_gui(*, dry_run: bool = False, debug_save_frames: bool = False, debug: bool = False) -> None:
    app = BotControlApp(
        dry_run=dry_run,
        debug_save_frames=debug_save_frames,
        debug=debug,
    )
    app.mainloop()
