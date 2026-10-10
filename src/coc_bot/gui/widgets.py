"""Reusable interactive controls (modern settings toggles, etc.)."""

from __future__ import annotations

import tkinter as tk

import coc_bot.gui.theme as theme


class HelpTip:
    """Contextual help without permanent description text in compact rows."""

    def __init__(self, widget: tk.Misc, text: str) -> None:
        self.widget, self.text = widget, text
        self.window = None
        self.pending = None
        widget.bind("<Enter>", self.schedule, add="+")
        widget.bind("<FocusIn>", self.schedule, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<FocusOut>", self.hide, add="+")
        widget.bind("<Escape>", self.hide, add="+")
        widget.bind("<Destroy>", self.hide, add="+")

    def schedule(self, _event=None) -> None:
        self.hide()
        self.pending = self.widget.after(550, self.show)

    def show(self) -> None:
        self.pending = None
        if not self.widget.winfo_exists() or not self.widget.winfo_ismapped():
            return
        self.window = tk.Toplevel(self.widget)
        self.window.overrideredirect(True)
        label = tk.Label(self.window, text=self.text, wraplength=320,
                         justify=tk.LEFT, bg=theme.SURFACE, fg=theme.TEXT,
                         padx=12, pady=10, relief=tk.SOLID, borderwidth=1)
        label.pack()
        self.window.update_idletasks()
        x = min(self.widget.winfo_rootx(), self.widget.winfo_screenwidth() - self.window.winfo_reqwidth() - 8)
        y = min(self.widget.winfo_rooty() + self.widget.winfo_height() + 6,
                self.widget.winfo_screenheight() - self.window.winfo_reqheight() - 8)
        self.window.geometry(f"+{max(0, x)}+{max(0, y)}")

    def hide(self, _event=None) -> None:
        if self.pending is not None:
            self.widget.after_cancel(self.pending)
            self.pending = None
        if self.window is not None:
            self.window.destroy()
            self.window = None


class ToggleSwitch(tk.Canvas):
    """Compact on/off switch bound to a BooleanVar (row-layout themes)."""

    WIDTH = 44
    HEIGHT = 24
    PAD = 3
    KNOB = 18

    def __init__(
        self,
        master: tk.Misc,
        variable: tk.BooleanVar,
        *,
        bg: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(
            master,
            width=self.WIDTH,
            height=self.HEIGHT,
            bg=bg if bg is not None else theme.SURFACE_2,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
            takefocus=True,
            **kwargs,
        )
        self._var = variable
        self.bind("<Button-1>", self._on_click)
        self.bind("<space>", self._on_click)
        self.bind("<Return>", self._on_click)
        self._var.trace_add("write", lambda *_: self._draw())
        self._draw()

    def _on_click(self, _event: tk.Event | None = None) -> None:
        self._var.set(not bool(self._var.get()))

    def _draw(self) -> None:
        self.delete("all")
        on = bool(self._var.get())
        track = theme.ACCENT if on else theme.SURFACE
        self.create_oval(0, 0, self.HEIGHT, self.HEIGHT, fill=track, outline=track)
        self.create_oval(
            self.WIDTH - self.HEIGHT,
            0,
            self.WIDTH,
            self.HEIGHT,
            fill=track,
            outline=track,
        )
        self.create_rectangle(
            self.HEIGHT // 2,
            0,
            self.WIDTH - self.HEIGHT // 2,
            self.HEIGHT,
            fill=track,
            outline=track,
        )
        knob_x = self.WIDTH - self.PAD - self.KNOB if on else self.PAD
        knob_fill = theme.ACCENT_FG if on else theme.TEXT_SECONDARY
        # Prefer a light knob on saturated accents.
        if on and knob_fill.lower() in {"#001a26", "#381e72", "#1b2838", "#2e3440", "#1a1410"}:
            knob_fill = "#f5f5f7"
        self.create_oval(
            knob_x,
            self.PAD,
            knob_x + self.KNOB,
            self.PAD + self.KNOB,
            fill=knob_fill,
            outline=knob_fill,
        )
