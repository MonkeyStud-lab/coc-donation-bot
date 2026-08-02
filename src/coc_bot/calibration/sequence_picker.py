"""Ordered tap-sequence editor for farm deploy (army bar + map)."""

from __future__ import annotations

from typing import Callable

import cv2
import numpy as np
from loguru import logger
from PIL import Image, ImageTk


def draw_numbered_jitter_circles(
    canvas,
    points: list[tuple[int, int]],
    *,
    jitter_px: int,
    scale: float = 1.0,
    tag: str = "jitter_tap",
) -> None:
    """
    Draw numbered circles on a Tk canvas.

    Circle radius = jitter_px (image pixels) × scale — radius equals the max
    axis offset used by tap jitter (±N px square sampling).
    """
    canvas.delete(tag)
    j = max(0, int(jitter_px))
    r = max(4.0, j * scale) if j > 0 else 6.0
    for i, (x, y) in enumerate(points, start=1):
        sx, sy = x * scale, y * scale
        canvas.create_oval(
            sx - r,
            sy - r,
            sx + r,
            sy + r,
            outline="#66c0f4",
            width=2,
            fill="#66c0f4",
            stipple="gray50",
            tags=tag,
        )
        canvas.create_oval(
            sx - 3,
            sy - 3,
            sx + 3,
            sy + 3,
            outline="#ffffff",
            fill="#1b2838",
            width=1,
            tags=tag,
        )
        canvas.create_text(
            sx,
            sy - r - 8,
            text=str(i),
            fill="#ffffff",
            font=("Segoe UI", 11, "bold"),
            tags=tag,
        )


def draw_jitter_demo(
    canvas,
    *,
    jitter_px: int,
    width: int = 420,
    height: int = 160,
) -> None:
    """Abstract Settings demo: muted strip + three numbered jitter circles."""
    canvas.delete("all")
    canvas.configure(width=width, height=height)
    canvas.create_rectangle(0, 0, width, height, fill="#1b2838", outline="")
    # Fake “map” band
    canvas.create_rectangle(8, 20, width - 8, height - 36, fill="#2a475e", outline="#3d6a8a")
    # Fake army bar
    canvas.create_rectangle(8, height - 32, width - 8, height - 8, fill="#171a21", outline="#3d4450")
    demo_pts = [
        (int(width * 0.22), int(height * 0.42)),
        (int(width * 0.50), int(height * 0.55)),
        (int(width * 0.78), int(height * 0.38)),
    ]
    draw_numbered_jitter_circles(
        canvas, demo_pts, jitter_px=jitter_px, scale=1.0, tag="demo"
    )
    canvas.create_text(
        width // 2,
        10,
        text=(
            f"Farm deploy jitter demo — radius = ±{max(0, int(jitter_px))} px "
            "(max axis offset; sequence taps only)"
        ),
        fill="#c7d5e0",
        font=("Segoe UI", 9),
    )


class SequencePicker:
    """
    Multi-click editor over a battle screenshot.

    Circles show tap order; radius tracks tap jitter (max axis offset).
    """

    def __init__(
        self,
        root,
        frame_bgr: np.ndarray,
        *,
        title: str,
        jitter_px: int = 6,
        initial_points: list[tuple[int, int]] | None = None,
        on_jitter_change: Callable[[int], None] | None = None,
    ) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.root = root
        self.points: list[tuple[int, int]] = list(initial_points or [])
        self.result: list[tuple[int, int]] | None = None
        self.saved = False
        self.frame_bgr = frame_bgr
        self.jitter_px = max(0, min(40, int(jitter_px)))
        self._on_jitter_change = on_jitter_change
        self._refresh_cb = None
        self.scale = 1.0
        self.tk_image = None

        self.root.title(title)
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        self.pil_image = Image.fromarray(rgb)
        self.img_w, self.img_h = self.pil_image.size

        toolbar = ttk.Frame(self.root, padding=6)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        ttk.Button(toolbar, text="New screenshot (r)", command=self.refresh).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(toolbar, text="Undo (u)", command=self.undo_point).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="Clear (c)", command=self.clear_points).pack(
            side=tk.LEFT, padx=4
        )
        self.save_btn = ttk.Button(toolbar, text="Save (Enter)", command=self.save)
        self.save_btn.pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="Cancel (Esc)", command=self.cancel).pack(side=tk.LEFT, padx=4)

        jitter_row = ttk.Frame(self.root, padding=(6, 0, 6, 4))
        jitter_row.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(jitter_row, text="Farm deploy jitter (px):").pack(side=tk.LEFT)
        self._jitter_var = tk.IntVar(master=self.root, value=self.jitter_px)
        self._jitter_label = ttk.Label(jitter_row, text=str(self.jitter_px), width=4)
        self._jitter_label.pack(side=tk.LEFT, padx=(4, 8))
        self._jitter_scale = ttk.Scale(
            jitter_row,
            from_=0,
            to=40,
            orient=tk.HORIZONTAL,
            command=self._on_jitter_slider,
            length=220,
        )
        self._jitter_scale.set(self.jitter_px)
        self._jitter_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        self.status = ttk.Label(self.root, text=self._hint(), padding=6)
        self.status.pack(side=tk.TOP, fill=tk.X)

        self.warning = ttk.Label(self.root, text="", foreground="#e0a060", padding=(6, 0))
        self.warning.pack(side=tk.TOP, fill=tk.X)

        max_w, max_h = 1600, 820
        self.scale = min(1.0, max_w / self.img_w, max_h / self.img_h)
        canvas_w = int(self.img_w * self.scale)
        canvas_h = int(self.img_h * self.scale)
        self.canvas = tk.Canvas(self.root, width=canvas_w, height=canvas_h, cursor="crosshair")
        self.canvas.pack()

        ttk.Label(
            self.root,
            text=(
                f"Image: {self.img_w}x{self.img_h}  |  "
                "Click army-bar icons then map drops in order. "
                "Circle radius = max axis offset (±N px)."
            ),
            padding=6,
        ).pack()

        self._set_image(self.pil_image)
        self._redraw_markers()
        self._bind_events()
        self._update_save_state()
        self._update_jitter_warning()

    def set_refresh_callback(self, cb: Callable[[], np.ndarray]) -> None:
        self._refresh_cb = cb

    def _hint(self) -> str:
        return (
            f"Taps: {len(self.points)}  |  jitter ±{self.jitter_px} px  |  "
            "Click to add · Undo / Clear · Save when done"
        )

    def _on_jitter_slider(self, _value: str) -> None:
        self.jitter_px = max(0, min(40, int(round(float(self._jitter_scale.get())))))
        self._jitter_var.set(self.jitter_px)
        self._jitter_label.config(text=str(self.jitter_px))
        self._redraw_markers()
        self.status.config(text=self._hint())
        self._update_jitter_warning()
        if self._on_jitter_change is not None:
            self._on_jitter_change(self.jitter_px)

    def _update_jitter_warning(self) -> None:
        if self.jitter_px > 12:
            self.warning.config(
                text=(
                    "Warning: farm deploy jitter above 12 px can miss small army-bar icons. "
                    "This does not affect donation taps. Lower the slider if selects feel unreliable."
                )
            )
        else:
            self.warning.config(text="")

    def _set_image(self, pil_image: Image.Image) -> None:
        self.pil_image = pil_image
        self.img_w, self.img_h = pil_image.size
        if self.scale < 1.0:
            display = pil_image.resize(
                (int(self.img_w * self.scale), int(self.img_h * self.scale)),
                Image.Resampling.LANCZOS,
            )
        else:
            display = pil_image
        self.tk_image = ImageTk.PhotoImage(display)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=self.tk.NW, image=self.tk_image)

    def _to_image_coords(self, cx: int, cy: int) -> tuple[int, int]:
        x = int(round(cx / self.scale))
        y = int(round(cy / self.scale))
        x = max(0, min(x, self.img_w - 1))
        y = max(0, min(y, self.img_h - 1))
        return x, y

    def _redraw_markers(self) -> None:
        draw_numbered_jitter_circles(
            self.canvas,
            self.points,
            jitter_px=self.jitter_px,
            scale=self.scale,
            tag="jitter_tap",
        )

    def _bind_events(self) -> None:
        self.canvas.bind("<Motion>", self.on_motion)
        self.canvas.bind("<Button-1>", self.on_click)
        self.root.bind("r", lambda _e: self.refresh())
        self.root.bind("R", lambda _e: self.refresh())
        self.root.bind("u", lambda _e: self.undo_point())
        self.root.bind("U", lambda _e: self.undo_point())
        self.root.bind("c", lambda _e: self.clear_points())
        self.root.bind("C", lambda _e: self.clear_points())
        self.root.bind("<Return>", lambda _e: self.save())
        self.root.bind("<KP_Enter>", lambda _e: self.save())
        self.root.bind("<Escape>", lambda _e: self.cancel())
        self.root.bind("q", lambda _e: self.cancel())
        self.root.bind("Q", lambda _e: self.cancel())
        self.root.protocol("WM_DELETE_WINDOW", self.cancel)

    def on_motion(self, event) -> None:
        x, y = self._to_image_coords(event.x, event.y)
        self.status.config(
            text=f"Cursor: ({x}, {y})  |  Taps: {len(self.points)}  |  jitter ±{self.jitter_px} px"
        )

    def on_click(self, event) -> None:
        x, y = self._to_image_coords(event.x, event.y)
        self.points.append((x, y))
        self._redraw_markers()
        self._update_save_state()
        self.status.config(text=self._hint())

    def undo_point(self) -> None:
        if self.points:
            self.points.pop()
        self._redraw_markers()
        self._update_save_state()
        self.status.config(text=self._hint())

    def clear_points(self) -> None:
        self.points.clear()
        self._redraw_markers()
        self._update_save_state()
        self.status.config(text=self._hint())

    def _update_save_state(self) -> None:
        state = self.tk.NORMAL if self.points else self.tk.DISABLED
        self.save_btn.configure(state=state)

    def save(self) -> None:
        if not self.points:
            return
        self.result = list(self.points)
        self.saved = True
        self.root.destroy()

    def cancel(self) -> None:
        self.result = None
        self.saved = False
        self.root.destroy()

    def refresh(self) -> None:
        if self._refresh_cb is None:
            self.status.config(text="Screenshot refresh not available.")
            return
        frame = self._refresh_cb()
        self.set_frame(frame, keep_points=True)
        self.status.config(text="Screenshot updated. " + self._hint())

    def set_frame(self, frame_bgr: np.ndarray, *, keep_points: bool = False) -> None:
        self.frame_bgr = frame_bgr
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        if not keep_points:
            self.points.clear()
        self._set_image(Image.fromarray(rgb))
        self._redraw_markers()
        self._update_save_state()


def persist_farm_deploy_jitter(jitter_px: int) -> None:
    """Merge farm.deploy_jitter_px into user_settings.yaml (farm sequence only)."""
    from coc_bot.config import load_user_settings, save_user_settings

    j = max(0, min(40, int(jitter_px)))
    existing = load_user_settings()
    farm = dict(existing.get("farm") or {})
    farm["deploy_jitter_px"] = j
    existing["farm"] = farm
    save_user_settings(existing)
    logger.info("Saved farm.deploy_jitter_px={} to user_settings", j)


def pick_deploy_sequence(
    frame: np.ndarray,
    *,
    jitter_px: int = 6,
    initial_points: list[tuple[int, int]] | None = None,
    refresh_cb: Callable[[], np.ndarray] | None = None,
    title: str = "Program farm deploy taps",
    master=None,
) -> tuple[list[tuple[int, int]] | None, int, np.ndarray]:
    """
    Open the sequence editor on the Tk main thread.

    Pass ``master`` (the BotControlApp window) when launching from the GUI so we
    use a ``Toplevel`` instead of a second ``Tk()`` — required because Tools run
    ADB work off-thread and the editor must open on the UI thread.

    Returns ``(points_or_None_if_cancelled, jitter_px, frame_used)``.
    """
    try:
        import tkinter as tk
    except ImportError:
        logger.error("tkinter not available — cannot open sequence picker")
        return None, jitter_px, frame

    if master is not None:
        root = tk.Toplevel(master)
        root.transient(master)
        root.grab_set()
    else:
        root = tk.Tk()

    try:
        picker = SequencePicker(
            root,
            frame,
            title=title,
            jitter_px=jitter_px,
            initial_points=initial_points,
            on_jitter_change=persist_farm_deploy_jitter,
        )
    except Exception:
        logger.exception("Failed to build sequence picker window")
        try:
            root.destroy()
        except Exception:  # noqa: BLE001
            pass
        return None, jitter_px, frame

    if refresh_cb is not None:
        picker.set_refresh_callback(refresh_cb)

    if master is not None:
        master.wait_window(root)
    else:
        root.mainloop()

    if not picker.saved or picker.result is None:
        return None, picker.jitter_px, picker.frame_bgr
    return picker.result, picker.jitter_px, picker.frame_bgr
