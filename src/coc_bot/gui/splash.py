"""Lightweight startup splash (tkinter only — no OpenCV / bot imports)."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class StartupSplash:
    """
    Progress window shown while the GUI loads.

    - ``master is None``: owns a temporary ``tk.Tk`` (import phase only).
    - ``master`` set: ``Toplevel`` on the real app root (safe for StringVars).
    """

    def __init__(self, master: tk.Misc | None = None) -> None:
        self._owns_root = master is None
        if master is None:
            self.root = tk.Tk()
        else:
            self.root = tk.Toplevel(master)
            try:
                self.root.transient(master)
            except tk.TclError:
                pass

        self.root.title("CoC Donation Bot")
        self.root.resizable(False, False)
        self.root.configure(bg="#1b2838")
        try:
            self.root.attributes("-topmost", True)
        except tk.TclError:
            pass

        frame = tk.Frame(self.root, bg="#1b2838", padx=28, pady=22)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            frame,
            text="CoC Donation Bot",
            bg="#1b2838",
            fg="#c7d5e0",
            font=("Segoe UI", 14, "bold"),
        ).pack(anchor=tk.W)

        self._status = tk.StringVar(master=self.root, value="Starting…")
        tk.Label(
            frame,
            textvariable=self._status,
            bg="#1b2838",
            fg="#8f98a0",
            font=("Segoe UI", 10),
        ).pack(anchor=tk.W, pady=(8, 12))

        self._value = tk.DoubleVar(master=self.root, value=0.0)
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Splash.Horizontal.TProgressbar",
            troughcolor="#171a21",
            background="#66c0f4",
            bordercolor="#171a21",
            lightcolor="#66c0f4",
            darkcolor="#66c0f4",
        )
        bar = ttk.Progressbar(
            frame,
            style="Splash.Horizontal.TProgressbar",
            orient=tk.HORIZONTAL,
            length=320,
            mode="determinate",
            maximum=100,
            variable=self._value,
        )
        bar.pack(fill=tk.X)

        self.root.update_idletasks()
        w = self.root.winfo_reqwidth()
        h = self.root.winfo_reqheight()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"+{(sw - w) // 2}+{(sh - h) // 3}")
        self.root.update()

    def set(self, fraction: float, message: str) -> None:
        """Update progress ``fraction`` in [0, 1] and status text."""
        try:
            if not self.root.winfo_exists():
                return
        except tk.TclError:
            return
        self._value.set(max(0.0, min(100.0, float(fraction) * 100.0)))
        self._status.set(message)
        self.root.update_idletasks()
        self.root.update()

    def close(self) -> None:
        try:
            if self.root.winfo_exists():
                self.root.destroy()
        except tk.TclError:
            pass
