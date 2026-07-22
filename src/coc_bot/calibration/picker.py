"""Interactive screenshot picker for calibration points and ROIs."""

from __future__ import annotations

from typing import Literal

import cv2
import numpy as np
from PIL import Image, ImageTk

Mode = Literal["point", "roi"]


class InteractivePicker:
    """
    Tk window over a screenshot.

    point mode: one click, then Confirm
    roi mode: two clicks (corners), then Confirm
    """

    def __init__(self, root, frame_bgr: np.ndarray, *, mode: Mode, title: str) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.root = root
        self.mode: Mode = mode
        self.points: list[tuple[int, int]] = []
        self.result: tuple[int, ...] | None = None
        self.frame_bgr = frame_bgr
        self.scale = 1.0
        self.tk_image = None
        self.rect_id = None
        self.overlays: list[int] = []
        self._refresh_cb = None

        self.root.title(title)
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        self.pil_image = Image.fromarray(rgb)
        self.img_w, self.img_h = self.pil_image.size

        toolbar = ttk.Frame(self.root, padding=6)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        ttk.Button(toolbar, text="New screenshot (r)", command=self.refresh).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="Clear (c)", command=self.clear_points).pack(side=tk.LEFT, padx=4)
        self.confirm_btn = ttk.Button(toolbar, text="Confirm (Enter)", command=self.confirm)
        self.confirm_btn.pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="Cancel (Esc)", command=self.cancel).pack(side=tk.LEFT, padx=4)

        self.status = ttk.Label(toolbar, text=self._hint())
        self.status.pack(side=tk.LEFT, padx=12)

        max_w, max_h = 1600, 900
        self.scale = min(1.0, max_w / self.img_w, max_h / self.img_h)
        canvas_w = int(self.img_w * self.scale)
        canvas_h = int(self.img_h * self.scale)

        self.canvas = tk.Canvas(self.root, width=canvas_w, height=canvas_h, cursor="crosshair")
        self.canvas.pack()

        ttk.Label(
            self.root,
            text=f"Image: {self.img_w}x{self.img_h}  |  {self._hint()}",
            padding=6,
        ).pack()

        self._set_image(self.pil_image)
        self._bind_events()
        self._update_confirm_state()

    def set_refresh_callback(self, cb) -> None:
        """Optional callback that returns a new BGR frame."""
        self._refresh_cb = cb

    def _hint(self) -> str:
        if self.mode == "point":
            return "Click once on the target, then Confirm."
        return "Click top-left, then bottom-right of the region, then Confirm."

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
        self.overlays.clear()
        self.rect_id = None

    def _to_image_coords(self, cx: int, cy: int) -> tuple[int, int]:
        x = int(round(cx / self.scale))
        y = int(round(cy / self.scale))
        x = max(0, min(x, self.img_w - 1))
        y = max(0, min(y, self.img_h - 1))
        return x, y

    def _bind_events(self) -> None:
        self.canvas.bind("<Motion>", self.on_motion)
        self.canvas.bind("<Button-1>", self.on_click)
        self.root.bind("r", lambda _e: self.refresh())
        self.root.bind("R", lambda _e: self.refresh())
        self.root.bind("c", lambda _e: self.clear_points())
        self.root.bind("C", lambda _e: self.clear_points())
        self.root.bind("<Return>", lambda _e: self.confirm())
        self.root.bind("<KP_Enter>", lambda _e: self.confirm())
        self.root.bind("<Escape>", lambda _e: self.cancel())
        self.root.bind("q", lambda _e: self.cancel())
        self.root.bind("Q", lambda _e: self.cancel())
        self.root.protocol("WM_DELETE_WINDOW", self.cancel)

    def on_motion(self, event) -> None:
        x, y = self._to_image_coords(event.x, event.y)
        needed = 1 if self.mode == "point" else 2
        self.status.config(text=f"Cursor: ({x}, {y})   |   Clicks: {len(self.points)}/{needed}")

    def on_click(self, event) -> None:
        x, y = self._to_image_coords(event.x, event.y)
        needed = 1 if self.mode == "point" else 2
        if len(self.points) >= needed:
            self.clear_points()
        self.points.append((x, y))
        sx, sy = int(x * self.scale), int(y * self.scale)
        pid = self.canvas.create_oval(sx - 5, sy - 5, sx + 5, sy + 5, outline="red", width=2)
        lid = self.canvas.create_text(
            sx + 8, sy - 8, text=f"({x},{y})", fill="red", anchor=self.tk.NW
        )
        self.overlays.extend([pid, lid])

        if self.mode == "roi" and len(self.points) == 2:
            x1, y1 = self.points[0]
            x2, y2 = self.points[1]
            rx, ry = min(x1, x2), min(y1, y2)
            rw, rh = abs(x2 - x1), abs(y2 - y1)
            sx1, sy1 = int(rx * self.scale), int(ry * self.scale)
            sx2, sy2 = int((rx + rw) * self.scale), int((ry + rh) * self.scale)
            self.rect_id = self.canvas.create_rectangle(sx1, sy1, sx2, sy2, outline="lime", width=2)
            self.status.config(text=f"ROI: {rx} {ry} {rw} {rh} — click Confirm")

        self._update_confirm_state()

    def clear_points(self) -> None:
        self.points.clear()
        for item in self.overlays:
            self.canvas.delete(item)
        self.overlays.clear()
        if self.rect_id is not None:
            self.canvas.delete(self.rect_id)
            self.rect_id = None
        self.status.config(text=self._hint())
        self._update_confirm_state()

    def _update_confirm_state(self) -> None:
        needed = 1 if self.mode == "point" else 2
        state = self.tk.NORMAL if len(self.points) >= needed else self.tk.DISABLED
        self.confirm_btn.configure(state=state)

    def confirm(self) -> None:
        if self.mode == "point":
            if len(self.points) < 1:
                return
            self.result = self.points[0]
        else:
            if len(self.points) < 2:
                return
            x1, y1 = self.points[0]
            x2, y2 = self.points[1]
            self.result = (min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))
        self.root.destroy()

    def cancel(self) -> None:
        self.result = None
        self.root.destroy()

    def refresh(self) -> None:
        if self._refresh_cb is None:
            self.status.config(text="Screenshot refresh not available in this context.")
            return
        frame = self._refresh_cb()
        self.set_frame(frame)
        self.status.config(text="Screenshot updated. " + self._hint())

    def set_frame(self, frame_bgr: np.ndarray) -> None:
        self.frame_bgr = frame_bgr
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        self.clear_points()
        self._set_image(Image.fromarray(rgb))


def _screenshot_from_adb() -> np.ndarray:
    from coc_bot.adb.capture import ScreenCapture
    from coc_bot.adb.client import AdbClient
    from coc_bot.config import load_config

    config = load_config()
    client = AdbClient(device=config.adb_device)
    client.ensure_connected()
    return ScreenCapture(client).screenshot()


def pick_interactive(
    frame: np.ndarray | None,
    label: str,
    *,
    mode: Mode,
    refresh_cb=None,
) -> tuple[tuple[int, ...] | None, np.ndarray | None]:
    """
    Open picker over a screenshot.

    Returns ``(selection, frame_used)`` where selection is a point ``(x, y)``
    or ROI ``(x, y, w, h)``. Selection is ``None`` if cancelled / unavailable.
    """
    try:
        import tkinter as tk
    except ImportError:
        print("tkinter not available (sudo apt install python3-tk). Falling back to typed input.")
        return None, frame

    if frame is None:
        print("Capturing screenshot from ADB…")
        frame = _screenshot_from_adb()

    if refresh_cb is None:
        refresh_cb = _screenshot_from_adb

    title = f"Calibrate: {label}"
    print(f"\nOpening picker for: {label}")
    if mode == "point":
        print("  Click the target once, then Confirm (Enter).")
    else:
        print("  Click two corners of the region, then Confirm (Enter).")

    root = tk.Tk()
    picker = InteractivePicker(root, frame, mode=mode, title=title)
    picker.set_refresh_callback(refresh_cb)
    root.mainloop()
    return picker.result, picker.frame_bgr


# Back-compat alias used by pick_coordinates.py / pick_grid.py
CoordinatePicker = InteractivePicker
