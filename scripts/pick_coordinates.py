#!/usr/bin/env python3
"""
Interactive pixel coordinate / ROI picker for calibration.

Usage:
  python scripts/pick_coordinates.py              # fresh ADB screenshot
  python scripts/pick_coordinates.py ~/coc-screenshot.png   # existing image

Controls:
  Move mouse     — live (x, y) under cursor
  Left-click     — mark a corner (2 clicks = ROI: x y width height)
  r              — capture a new screenshot from ADB
  c              — clear marked points
  q / Escape     — quit
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
from PIL import Image, ImageTk

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from coc_bot.adb.capture import ScreenCapture
from coc_bot.adb.client import AdbClient
from coc_bot.config import load_config

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError as exc:
    raise SystemExit(
        "tkinter is required. Install with: sudo apt install python3-tk"
    ) from exc


class CoordinatePicker:
    def __init__(self, root: tk.Tk, frame_bgr) -> None:
        self.root = root
        self.root.title("CoC Coordinate Picker")
        self.points: list[tuple[int, int]] = []
        self.scale = 1.0
        self.tk_image = None
        self.rect_id = None
        self.point_ids: list[int] = []
        self.label_ids: list[int] = []

        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        self.pil_image = Image.fromarray(rgb)
        self.img_w, self.img_h = self.pil_image.size

        self._build_ui()
        self._set_image(self.pil_image)
        self._bind_events()

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self.root, padding=6)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        ttk.Button(toolbar, text="New screenshot (r)", command=self.refresh).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="Clear (c)", command=self.clear_points).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="Quit (q)", command=self.root.destroy).pack(side=tk.LEFT, padx=4)

        self.status = ttk.Label(
            toolbar,
            text="Move mouse for coordinates. Click top-left, then bottom-right.",
        )
        self.status.pack(side=tk.LEFT, padx=12)

        # Fit to screen (max 1600x900) but keep exact coordinates
        max_w, max_h = 1600, 900
        self.scale = min(1.0, max_w / self.img_w, max_h / self.img_h)

        canvas_w = int(self.img_w * self.scale)
        canvas_h = int(self.img_h * self.scale)

        self.canvas = tk.Canvas(self.root, width=canvas_w, height=canvas_h, cursor="crosshair")
        self.canvas.pack()

        help_text = (
            f"Image: {self.img_w}x{self.img_h}  |  "
            "2 clicks copy ROI to terminal  |  r=new  c=clear  q=quit"
        )
        ttk.Label(self.root, text=help_text, padding=6).pack()

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
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_image)
        self.point_ids.clear()
        self.label_ids.clear()
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
        self.root.bind("q", lambda _e: self.root.destroy())
        self.root.bind("Q", lambda _e: self.root.destroy())
        self.root.bind("<Escape>", lambda _e: self.root.destroy())

    def on_motion(self, event) -> None:
        x, y = self._to_image_coords(event.x, event.y)
        self.status.config(text=f"Cursor: ({x}, {y})   |   Clicks: {len(self.points)}/2")

    def on_click(self, event) -> None:
        x, y = self._to_image_coords(event.x, event.y)
        if len(self.points) >= 2:
            self.clear_points()
        self.points.append((x, y))
        sx, sy = int(x * self.scale), int(y * self.scale)
        pid = self.canvas.create_oval(sx - 5, sy - 5, sx + 5, sy + 5, outline="red", width=2)
        lid = self.canvas.create_text(sx + 8, sy - 8, text=f"P{len(self.points)} ({x},{y})", fill="red", anchor=tk.NW)
        self.point_ids.extend([pid, lid])
        print(f"Point {len(self.points)}: {x} {y}")

        if len(self.points) == 2:
            x1, y1 = self.points[0]
            x2, y2 = self.points[1]
            rx, ry = min(x1, x2), min(y1, y2)
            rw, rh = abs(x2 - x1), abs(y2 - y1)
            sx1, sy1 = int(rx * self.scale), int(ry * self.scale)
            sx2, sy2 = int((rx + rw) * self.scale), int((ry + rh) * self.scale)
            self.rect_id = self.canvas.create_rectangle(sx1, sy1, sx2, sy2, outline="lime", width=2)
            roi = f"{rx} {ry} {rw} {rh}"
            print(f"\n>>> ROI (paste into calibration): {roi}\n")
            self.status.config(text=f"ROI: {roi}")

    def clear_points(self) -> None:
        self.points.clear()
        for item in self.point_ids:
            self.canvas.delete(item)
        self.point_ids.clear()
        if self.rect_id is not None:
            self.canvas.delete(self.rect_id)
            self.rect_id = None
        self.status.config(text="Cleared. Click top-left, then bottom-right.")
        print("Cleared points.")

    def refresh(self) -> None:
        print("\nCapturing new screenshot...")
        frame = load_frame_from_adb()
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        self.clear_points()
        self._set_image(Image.fromarray(rgb))
        print("Screenshot updated. Click two corners for ROI.\n")

    def set_frame(self, frame_bgr) -> None:
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        self.clear_points()
        self._set_image(Image.fromarray(rgb))


def load_frame_from_adb():
    config = load_config()
    client = AdbClient(device=config.adb_device)
    client.ensure_connected()
    capture = ScreenCapture(client)
    frame = capture.screenshot()
    out = Path.home() / "coc-screenshot.png"
    cv2.imwrite(str(out), frame)
    print(f"Saved screenshot: {out} ({frame.shape[1]}x{frame.shape[0]})")
    return frame


def load_frame_from_path(path: Path):
    frame = cv2.imread(str(path))
    if frame is None:
        raise SystemExit(f"Could not load image: {path}")
    print(f"Loaded: {path} ({frame.shape[1]}x{frame.shape[0]})")
    return frame


def main() -> None:
    if len(sys.argv) > 1:
        frame = load_frame_from_path(Path(sys.argv[1]).expanduser())
    else:
        print("Capturing screenshot from ADB...")
        frame = load_frame_from_adb()

    root = tk.Tk()
    CoordinatePicker(root, frame)
    print("Window opened. Move mouse for coordinates; 2 clicks = ROI.\n")
    root.mainloop()


if __name__ == "__main__":
    main()
