"""Screenshot collection and interface-profile controls for the Library page."""
from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from coc_bot.config import load_config
from coc_bot.gui import theme
from coc_bot.gui.theme import ui_font


class DataToolsMixin:
    def _build_library_page(self):
        page = self._pages["library"]
        for child in page.winfo_children():
            child.destroy()
        self._clear_wrap_labels("library")
        self._library_buttons = []
        notebook = ttk.Notebook(page)
        notebook.pack(fill=tk.BOTH, expand=True, padx=8)
        from coc_bot.gui.theme import make_scrollable, finish_scrollable
        for name in ("Screenshots", "Saved calibrations"):
            tab = ttk.Frame(notebook)
            notebook.add(tab, text=name)
            canvas, body = make_scrollable(tab)
            if name == "Screenshots":
                self._library_canvas = canvas
                self._build_data_tools(body)
            else:
                for label, callback in (
                    ("Save calibration backup", self._backup_calibration),
                    ("Save interface profile", self._save_interface_profile),
                    ("Restore saved calibration", self._restore_calibration),
                    ("Rename saved calibration", self._rename_calibration_backup),
                    ("Delete saved calibration", self._delete_calibration_backup),
                    ("Check calibration files", self._check_calibration_files),
                ):
                    card = self._card(body, padx=8, pady=4)
                    row = tk.Frame(card, bg=theme.SURFACE_2)
                    row.pack(fill=tk.X, padx=16, pady=14)
                    button = self._add_tools_row_modern(row, title=label,
                        description="Saved calibrations include both coordinates and reference images.",
                        button_text="Open", command=callback)
                    button._allow_while_running = label == "Check calibration files"
                    self._library_buttons.append(button)
            finish_scrollable(body, canvas)
        self._update_tool_buttons_state()

    def _build_data_tools(self, inner):
        card = self._card(inner, padx=8, pady=4)
        body = tk.Frame(card, bg=theme.SURFACE_2)
        body.pack(fill=tk.X, padx=16, pady=16)
        status = tk.Label(body, bg=theme.SURFACE_2, fg=theme.TEXT_SECONDARY,
                          font=ui_font(10), anchor="w", justify=tk.LEFT, wraplength=400)
        status.pack(fill=tk.X, pady=(0, 12))
        self._track_wrap_label(status, reserve=56, page_id="library")
        button = ttk.Button(body, text="Review screenshots", style=self._btn_style("Secondary"),
                            command=lambda: self._run_debug("open_collection_review"))
        button.pack(anchor=tk.W)
        button._allow_while_running = True
        self._library_buttons.append(button)
        ttk.Button(body, text="Collection settings", style=self._btn_style("Secondary"),
                   command=self._open_collection_settings).pack(anchor=tk.W, pady=(8, 0))

        def refresh():
            if not status.winfo_exists():
                return
            config = load_config()
            try:
                report = json.loads((config.data_dir / "collection/status.json").read_text(encoding="utf-8"))
                stats = report.get("stats", {})
                used = report.get("approximate_storage_bytes", 0) / 1024**3
                text = f"{stats.get('saved', 0)} saved this session · {used:.2f} GB"
                if report.get("paused"):
                    text += f" · Paused: {report['paused']}"
            except (OSError, ValueError, TypeError):
                text = "No screenshots collected yet"
            status.configure(text=text)
            self.after(5000, refresh)
        refresh()

    def _open_collection_settings(self):
        self._show_page("settings")
        self._settings_notebook.select(3)

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
            messagebox.showinfo("Profile saved", "Calibration and reference images are saved together. Restore, rename, or delete them from Library.")
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
