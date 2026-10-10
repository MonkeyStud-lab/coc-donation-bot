"""Screenshot collection and interface-profile controls for the Tools page."""
from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from coc_bot.config import load_config
from coc_bot.gui import theme
from coc_bot.gui.theme import ui_font


class DataToolsMixin:
    def _build_data_tools(self, inner):
        body = self._section_header(inner, "tools:collection", "Screenshots & interface profiles")
        status = tk.Label(body, bg=theme.SURFACE_2, fg=theme.TEXT_SECONDARY,
                          font=ui_font(10), anchor="w", justify=tk.LEFT, wraplength=400)
        status.pack(fill=tk.X, padx=12, pady=10)
        self._track_wrap_label(status, reserve=56, page_id="tools")
        for label, callback, safe in (
            ("Review collected screenshots", lambda: self._run_debug("open_collection_review"), True),
            ("Save interface profile…", self._save_interface_profile, False),
            ("Switch interface profile…", self._restore_calibration, False),
            ("Check calibration files", self._check_calibration_files, True),
        ):
            button = ttk.Button(body, text=label, style=self._btn_style("Secondary"), command=callback)
            button.pack(anchor=tk.W, padx=12, pady=4)
            button._allow_while_running = safe
            self._tool_buttons.append(button)

        def refresh():
            if not status.winfo_exists():
                return
            config = load_config()
            try:
                report = json.loads((config.data_dir / "collection/status.json").read_text(encoding="utf-8"))
                stats = report.get("stats", {})
                used = report.get("approximate_storage_bytes", 0) / 1024**3
                pause = report.get("paused") or "No limit reached"
                text = (f"Collection setting: {'enabled' if config.collection_enabled else 'disabled'} (applies at Start). "
                        f"Saved: {stats.get('saved', 0)} this session; storage: {used:.2f} GB. {pause}. "
                        "Images and predicted labels still need human review.")
            except (OSError, ValueError, TypeError):
                text = "No collection status yet. Enable useful screenshot collection in Settings, then Start."
            status.configure(text=text)
            self.after(5000, refresh)
        refresh()

    def _save_interface_profile(self):
        if self._bot_running() or self._farm_oneshot_running():
            messagebox.showwarning("Stop first", "Stop the bot before saving an interface profile.")
            return
        name = simpledialog.askstring("Interface profile", "Name this game interface / screen layout (for example, autumn_update):", parent=self)
        if not name:
            return
        try:
            from coc_bot.calibration.profiles import save_interface_profile
            backup = save_interface_profile(name, load_config())
            self._append_log(f"Saved interface profile: {backup.stamp}")
            messagebox.showinfo("Profile saved", "Calibration and reference images are saved together. Switch profiles here, or rename/delete them from Setup.")
        except (OSError, ValueError) as exc:
            messagebox.showerror("Profile failed", str(exc))

    def _check_calibration_files(self):
        from coc_bot.calibration.profiles import check_calibration
        from coc_bot.adb.capture_coordinator import latest_frame
        config = load_config()
        latest = latest_frame(config.adb_device)
        size = (latest[0].shape[1], latest[0].shape[0]) if latest else None
        issues = check_calibration(config, size)
        text = "\n".join(issues) if issues else "Calibration files and coordinates passed the checks. This does not verify that each image still matches the current game interface. Use Practice mode to verify navigation."
        messagebox.showinfo("Calibration check", text)
