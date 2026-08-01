"""Reusable interactive controls (modern settings toggles, etc.)."""

from __future__ import annotations

import tkinter as tk

from coc_bot.gui.theme import ACCENT, SURFACE, SURFACE_2, TEXT_SECONDARY


class ToggleSwitch(tk.Canvas):
    """Compact on/off switch bound to a BooleanVar (Cursor-style control)."""

    WIDTH = 44
    HEIGHT = 24
    PAD = 3
    KNOB = 18

    def __init__(
        self,
        master: tk.Misc,
        variable: tk.BooleanVar,
        *,
        bg: str = SURFACE_2,
        **kwargs,
    ) -> None:
        super().__init__(
            master,
            width=self.WIDTH,
            height=self.HEIGHT,
            bg=bg,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
            **kwargs,
        )
        self._var = variable
        self._bg = bg
        self.bind("<Button-1>", self._on_click)
        self._var.trace_add("write", lambda *_: self._draw())
        self._draw()

    def _on_click(self, _event: tk.Event | None = None) -> None:
        self._var.set(not bool(self._var.get()))

    def _draw(self) -> None:
        self.delete("all")
        on = bool(self._var.get())
        track = ACCENT if on else SURFACE
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
        knob_fill = "#e8f4fc" if on else TEXT_SECONDARY
        self.create_oval(
            knob_x,
            self.PAD,
            knob_x + self.KNOB,
            self.PAD + self.KNOB,
            fill=knob_fill,
            outline=knob_fill,
        )
