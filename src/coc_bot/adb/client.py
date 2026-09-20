from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from typing import Sequence

from loguru import logger

from coc_bot.stop import interrupted_sleep


class AdbError(RuntimeError):
    pass


class AdbStopped(AdbError):
    """Raised when a cooperative stop interrupts an ADB reconnect loop."""


_PACKAGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$")


def validate_package_name(pkg: str) -> str:
    """
    Return ``pkg`` if it is a plausible Android package name, else raise.

    Package names are interpolated into device shell commands, so anything
    with shell metacharacters must be rejected up front.
    """
    pkg = (pkg or "").strip()
    if not _PACKAGE_RE.match(pkg):
        raise AdbError(f"Invalid Android package name: {pkg!r}")
    return pkg


def default_adb_device() -> str:
    """Resolve ADB device from ADB_DEVICE env var or Waydroid default."""
    return os.environ.get("ADB_DEVICE", "127.0.0.1:5555")


class AdbClient:
    """Centralized ADB wrapper with reconnect logic."""

    def __init__(
        self,
        device: str | None = None,
        max_attempts: int = 5,
        backoff_seconds: float = 2.0,
    ) -> None:
        self.device = device or default_adb_device()
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds
        # Optional cooperative stop hook so reconnect backoff can be interrupted.
        self.stop_check: Callable[[], bool] | None = None

    def _base_cmd(self) -> list[str]:
        return ["adb", "-s", self.device]

    def run(self, args: Sequence[str], timeout: float = 30.0, check: bool = True) -> subprocess.CompletedProcess[str]:
        cmd = [*self._base_cmd(), *args]
        logger.debug("ADB: {}", " ".join(cmd))
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise AdbError(f"ADB command timed out: {' '.join(cmd)}") from exc
        except OSError as exc:
            # adb binary missing / not executable — surface as AdbError so callers
            # that already handle ADB failures don't get a raw FileNotFoundError.
            raise AdbError(f"Could not run adb ({exc}). Is adb installed and on PATH?") from exc

        if check and result.returncode != 0:
            stderr = (result.stderr or "").strip()
            raise AdbError(f"ADB failed ({result.returncode}): {' '.join(cmd)} — {stderr}")
        return result

    def run_shell(self, shell_cmd: str, timeout: float = 30.0, check: bool = True) -> subprocess.CompletedProcess[str]:
        return self.run(["shell", shell_cmd], timeout=timeout, check=check)

    def run_exec_out(self, args: Sequence[str], timeout: float = 30.0) -> bytes:
        cmd = [*self._base_cmd(), "exec-out", *args]
        logger.debug("ADB exec-out: {}", " ".join(cmd))
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise AdbError(f"ADB exec-out timed out: {' '.join(cmd)}") from exc
        except OSError as exc:
            raise AdbError(f"Could not run adb ({exc}). Is adb installed and on PATH?") from exc
        if result.returncode != 0:
            stderr = (result.stderr or b"").decode("utf-8", errors="replace").strip()
            raise AdbError(f"ADB exec-out failed: {stderr}")
        return result.stdout

    def connect(self) -> bool:
        if ":" in self.device:
            host_port = self.device
            try:
                result = subprocess.run(
                    ["adb", "connect", host_port],
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                logger.warning("adb connect {} failed: {}", host_port, exc)
                return False
            logger.info("adb connect {}: {}", host_port, (result.stdout or result.stderr or "").strip())
        return self.get_state() == "device"

    @staticmethod
    def list_devices() -> list[tuple[str, str]]:
        """
        Return ``[(serial, state), ...]`` from ``adb devices``.

        ``state`` is typically ``device``, ``offline``, or ``unauthorized``.
        """
        try:
            result = subprocess.run(
                ["adb", "devices"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        found: list[tuple[str, str]] = []
        for line in (result.stdout or "").splitlines():
            line = line.strip()
            if not line or line.lower().startswith("list of devices"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                found.append((parts[0], parts[1]))
        return found

    def get_state(self) -> str:
        try:
            result = self.run(["get-state"], check=False)
            return (result.stdout or "").strip()
        except (AdbError, FileNotFoundError):
            return "offline"

    def ensure_connected(self) -> None:
        for attempt in range(1, self.max_attempts + 1):
            state = self.get_state()
            if state == "device":
                return
            logger.warning("ADB device state '{}', reconnect attempt {}/{}", state, attempt, self.max_attempts)
            self.connect()
            if interrupted_sleep(self.backoff_seconds * attempt, self.stop_check):
                raise AdbStopped("Stop requested during ADB reconnect")
        raise AdbError(f"Unable to connect to ADB device {self.device}")

    def wm_size(self) -> tuple[int, int] | None:
        """
        Return the touch/display size Android uses for ``input tap`` (width, height).

        Prefers Override size when set, else Physical size. Screencap can differ
        from this on some Waydroid setups — taps must be scaled accordingly.
        """
        try:
            result = self.run_shell("wm size", check=False)
        except (AdbError, FileNotFoundError):
            return None
        text = (result.stdout or "") + "\n" + (result.stderr or "")
        override: tuple[int, int] | None = None
        physical: tuple[int, int] | None = None
        for line in text.splitlines():
            line = line.strip()
            if "Override size:" in line:
                part = line.split(":", 1)[-1].strip()
                if "x" in part:
                    a, b = part.lower().split("x", 1)
                    try:
                        override = (int(a.strip()), int(b.strip()))
                    except ValueError:
                        pass
            elif "Physical size:" in line or "size:" in line.lower():
                part = line.split(":", 1)[-1].strip()
                if "x" in part:
                    a, b = part.lower().split("x", 1)
                    try:
                        physical = (int(a.strip()), int(b.strip()))
                    except ValueError:
                        pass
        return override or physical

    def health_check(self) -> tuple[int, int]:
        """Verify device is reachable and screencap works. Returns (width, height)."""
        self.ensure_connected()
        from coc_bot.adb.capture import ScreenCapture

        capture = ScreenCapture(self)
        frame = capture.screenshot()
        h, w = frame.shape[:2]
        if w <= 0 or h <= 0:
            raise AdbError("Screencap returned invalid frame dimensions")
        touch = self.wm_size()
        if touch and touch != (w, h):
            logger.warning(
                "ADB health check: screencap {}x{} but wm size {}x{} — taps will be scaled",
                w,
                h,
                touch[0],
                touch[1],
            )
        else:
            logger.info("ADB health check OK: {}x{}", w, h)
        return w, h
