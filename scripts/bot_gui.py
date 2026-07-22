#!/usr/bin/env python3
"""Simple control window for the CoC donation bot (start + shutoff)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import scrolledtext, ttk


ROOT = Path(__file__).resolve().parents[1]
VENV_PY = ROOT / ".venv" / "bin" / "python"
START_SCRIPT = ROOT / "scripts" / "start_bot_desktop.sh"
STOP_SCRIPT = ROOT / "scripts" / "stop_bot_desktop.sh"
LOG_DIR = ROOT / "logs"


class BotGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("CoC Donation Bot")
        self.geometry("520x360")
        self.minsize(420, 280)

        self._bot_proc: subprocess.Popen[str] | None = None
        self._prepare_proc: subprocess.Popen[str] | None = None
        self._starting = False

        self._status = tk.StringVar(value="Starting…")
        header = ttk.Frame(self, padding=10)
        header.pack(fill=tk.X)
        ttk.Label(header, textvariable=self._status, font=("Segoe UI", 11)).pack(side=tk.LEFT)

        btns = ttk.Frame(self, padding=(10, 0, 10, 8))
        btns.pack(fill=tk.X)
        self._stop_btn = ttk.Button(btns, text="Shut off bot", command=self.stop_bot)
        self._stop_btn.pack(side=tk.LEFT)
        self._start_btn = ttk.Button(btns, text="Start bot", command=self.start_bot, state=tk.DISABLED)
        self._start_btn.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(btns, text="Quit", command=self.on_quit).pack(side=tk.RIGHT)

        self._log = scrolledtext.ScrolledText(self, height=14, wrap=tk.WORD, state=tk.DISABLED)
        self._log.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        self.protocol("WM_DELETE_WINDOW", self.on_quit)
        self.after(200, self.start_bot)

    def append_log(self, line: str) -> None:
        self._log.configure(state=tk.NORMAL)
        self._log.insert(tk.END, line.rstrip() + "\n")
        self._log.see(tk.END)
        self._log.configure(state=tk.DISABLED)

    def set_status(self, text: str) -> None:
        self._status.set(text)

    def start_bot(self) -> None:
        if self._starting or self._bot_running():
            return
        self._starting = True
        self._start_btn.configure(state=tk.DISABLED)
        self._stop_btn.configure(state=tk.NORMAL)
        self.set_status("Preparing Waydroid / CoC…")
        self.append_log("==> Preparing environment…")
        threading.Thread(target=self._start_worker, daemon=True).start()

    def _bot_running(self) -> bool:
        return self._bot_proc is not None and self._bot_proc.poll() is None

    def _start_worker(self) -> None:
        try:
            if not VENV_PY.exists():
                self.after(0, lambda: self._fail("Missing .venv — run ./scripts/setup_linux.sh"))
                return
            if not START_SCRIPT.exists():
                self.after(0, lambda: self._fail(f"Missing {START_SCRIPT}"))
                return

            env = os.environ.copy()
            env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:" + env.get(
                "PATH", ""
            )
            env["PYTHONUNBUFFERED"] = "1"

            self._prepare_proc = subprocess.Popen(
                ["/bin/bash", str(START_SCRIPT), "--prepare-only"],
                cwd=str(ROOT),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            assert self._prepare_proc.stdout is not None
            for line in self._prepare_proc.stdout:
                text = line.rstrip()
                self.after(0, lambda t=text: self.append_log(t))
            code = self._prepare_proc.wait()
            self._prepare_proc = None
            if code != 0:
                self.after(0, lambda: self._fail(f"Prepare failed (exit {code})"))
                return

            LOG_DIR.mkdir(parents=True, exist_ok=True)
            self.after(0, lambda: self.set_status("Bot running"))
            self.after(0, lambda: self.append_log("==> Starting donation bot…"))

            self._bot_proc = subprocess.Popen(
                [str(VENV_PY), "-m", "coc_bot.main"],
                cwd=str(ROOT),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
            assert self._bot_proc.stdout is not None
            for line in self._bot_proc.stdout:
                text = line.rstrip()
                self.after(0, lambda t=text: self.append_log(t))
            code = self._bot_proc.wait()
            self._bot_proc = None
            self.after(0, lambda: self._on_bot_exited(code))
        except Exception as exc:  # noqa: BLE001 — show in GUI
            self.after(0, lambda: self._fail(str(exc)))
        finally:
            self._starting = False

    def _fail(self, message: str) -> None:
        self.set_status("Error")
        self.append_log(f"ERROR: {message}")
        self._start_btn.configure(state=tk.NORMAL)
        self._stop_btn.configure(state=tk.DISABLED)

    def _on_bot_exited(self, code: int) -> None:
        self.set_status("Bot stopped")
        self.append_log(f"==> Bot exited (code {code})")
        self._start_btn.configure(state=tk.NORMAL)
        self._stop_btn.configure(state=tk.DISABLED)

    def stop_bot(self) -> None:
        self.append_log("==> Shutting off bot…")
        self.set_status("Stopping…")

        if self._prepare_proc and self._prepare_proc.poll() is None:
            try:
                self._prepare_proc.terminate()
            except OSError:
                pass

        proc = self._bot_proc
        if proc and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    proc.terminate()
                except OSError:
                    pass

        if STOP_SCRIPT.exists():
            subprocess.run(["/bin/bash", str(STOP_SCRIPT)], cwd=str(ROOT), check=False)

        self.after(800, self._confirm_stopped)

    def _confirm_stopped(self) -> None:
        if self._bot_running():
            proc = self._bot_proc
            if proc is not None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    try:
                        proc.kill()
                    except OSError:
                        pass
        self.set_status("Bot stopped")
        self._start_btn.configure(state=tk.NORMAL)
        self._stop_btn.configure(state=tk.DISABLED)
        self.append_log("==> Bot shut off (game left running)")

    def on_quit(self) -> None:
        if self._bot_running() or self._starting:
            self.stop_bot()
            self.after(500, self.destroy)
        else:
            self.destroy()


def main() -> None:
    if sys.platform != "linux":
        print("This GUI is intended for the Ubuntu/Waydroid host.", file=sys.stderr)
    app = BotGui()
    app.mainloop()


if __name__ == "__main__":
    main()
