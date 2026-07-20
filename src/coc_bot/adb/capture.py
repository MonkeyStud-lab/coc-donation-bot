from __future__ import annotations

import tempfile
from pathlib import Path

import cv2
import numpy as np
from loguru import logger

from coc_bot.adb.client import AdbClient, AdbError


def _fix_png_line_endings(png_bytes: bytes) -> bytes:
    """ADB on some Waydroid builds injects CRLF into PNG data, breaking decode."""
    if png_bytes.startswith(b"\x89PNG") and b"\r\n" in png_bytes[:16]:
        return png_bytes.replace(b"\r\n", b"\n")
    if png_bytes.startswith(b"\x89PNG\r\r\n"):
        return png_bytes.replace(b"\r\r\n", b"\n")
    return png_bytes


def _decode_png(png_bytes: bytes) -> np.ndarray | None:
    for data in (png_bytes, _fix_png_line_endings(png_bytes)):
        arr = np.frombuffer(data, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is not None:
            return frame
    return None


def _decode_raw_screencap(raw: bytes) -> np.ndarray | None:
    """Decode uncompressed screencap (adb exec-out screencap, no -p flag)."""
    if len(raw) < 12:
        return None
    width, height, _fmt = np.frombuffer(raw[:12], dtype=np.uint32)
    w, h = int(width), int(height)
    if w <= 0 or h <= 0 or w > 10000 or h > 10000:
        return None
    expected = w * h * 4
    pixels = raw[12 : 12 + expected]
    if len(pixels) < expected:
        return None
    rgba = np.frombuffer(pixels, dtype=np.uint8).reshape(h, w, 4)
    return cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGR)


class ScreenCapture:
    """Capture frames from Android via ADB screencap."""

    def __init__(self, client: AdbClient, max_retries: int = 3) -> None:
        self.client = client
        self.max_retries = max_retries
        self._last_size: tuple[int, int] | None = None

    @property
    def last_size(self) -> tuple[int, int] | None:
        return self._last_size

    def _capture_png_exec_out(self) -> np.ndarray | None:
        png_bytes = self.client.run_exec_out(["screencap", "-p"], timeout=15.0)
        return _decode_png(png_bytes)

    def _capture_raw_exec_out(self) -> np.ndarray | None:
        raw = self.client.run_exec_out(["screencap"], timeout=15.0)
        return _decode_raw_screencap(raw)

    def _capture_via_pull(self) -> np.ndarray | None:
        remote = "/sdcard/coc_bot_screen.png"
        self.client.run_shell(f"screencap -p {remote}", timeout=15.0)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            local = tmp.name
        try:
            self.client.run(["pull", remote, local], timeout=30.0)
            self.client.run_shell(f"rm -f {remote}", check=False)
            data = Path(local).read_bytes()
            frame = _decode_png(data)
            if frame is None:
                frame = cv2.imread(local, cv2.IMREAD_COLOR)
            return frame
        finally:
            Path(local).unlink(missing_ok=True)

    def screenshot(self) -> np.ndarray:
        methods = (
            ("exec-out png", self._capture_png_exec_out),
            ("exec-out raw", self._capture_raw_exec_out),
            ("pull png", self._capture_via_pull),
        )
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            for method_name, method in methods:
                try:
                    frame = method()
                    if frame is None:
                        logger.debug("Screencap {} returned no frame", method_name)
                        continue
                    h, w = frame.shape[:2]
                    self._last_size = (w, h)
                    if attempt > 1 or method_name != "exec-out png":
                        logger.info("Screencap OK via {} ({}x{})", method_name, w, h)
                    return frame
                except (AdbError, cv2.error, ValueError) as exc:
                    last_error = exc
                    logger.debug("Screencap {} failed: {}", method_name, exc)

            logger.warning("Screencap attempt {}/{} failed on all methods", attempt, self.max_retries)
            if attempt < self.max_retries:
                self.client.ensure_connected()

        raise AdbError(f"Screencap failed after {self.max_retries} attempts") from last_error

    def save_debug(self, frame: np.ndarray, path: str) -> None:
        cv2.imwrite(path, frame)
