from __future__ import annotations

import os
import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import Sequence

from loguru import logger


class AdbError(RuntimeError):
    pass


def _find_ldplayer_adb() -> str | None:
    """Auto-detect LDPlayer's bundled adb.exe on Windows."""
    if platform.system() != "Windows":
        return None

    env_path = os.environ.get("ADB_PATH", "").strip()
    if env_path and Path(env_path).is_file():
        return env_path

    common_roots = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "LDPlayer" / "LDPlayer9",
        Path(os.environ.get("PROGRAMFILES", "")) / "LDPlayer" / "LDPlayer9",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "LDPlayer" / "LDPlayer9",
        Path("C:/LDPlayer/LDPlayer9"),
        Path("D:/LDPlayer/LDPlayer9"),
        Path("C:/LDPlayer/LDPlayer4.0"),
        Path("D:/LDPlayer/LDPlayer4.0"),
    ]
    for root in common_roots:
        adb = root / "adb.exe"
        if adb.is_file():
            return str(adb)

    # Fallback: find adb on PATH
    which = shutil.which("adb")
    if which:
        return which

    return None


def _ensure_adb_on_path() -> None:
    """Add LDPlayer's ADB directory to PATH so subprocess calls work."""
    adb = _find_ldplayer_adb()
    if adb:
        adb_dir = str(Path(adb).parent)
        if adb_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = adb_dir + os.pathsep + os.environ.get("PATH", "")
            logger.info("Added LDPlayer ADB to PATH: {}", adb_dir)


_ensure_adb_on_path()


def default_adb_device() -> str:
    """Resolve ADB device from ADB_DEVICE env var or auto-detect LDPlayer device."""
    env_device = os.environ.get("ADB_DEVICE", "").strip()
    if env_device:
        return env_device

    # Try to auto-detect the first LDPlayer device
    try:
        result = subprocess.run(
            ["adb", "devices"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        for line in result.stdout.splitlines()[1:]:
            line = line.strip()
            if line and "\tdevice" in line:
                device_id = line.split("\t")[0]
                logger.info("Auto-detected ADB device: {}", device_id)
                return device_id
    except (OSError, subprocess.TimeoutExpired):
        pass

    return "127.0.0.1:5555"


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
        if result.returncode != 0:
            stderr = (result.stderr or b"").decode("utf-8", errors="replace").strip()
            raise AdbError(f"ADB exec-out failed: {stderr}")
        return result.stdout

    def connect(self) -> bool:
        if ":" in self.device:
            host_port = self.device
            # Start LDPlayer server first if available
            ld_adb = _find_ldplayer_adb()
            if ld_adb:
                try:
                    subprocess.run(
                        [ld_adb, "start-server"],
                        capture_output=True,
                        text=True,
                        timeout=15,
                        check=False,
                    )
                except (OSError, subprocess.TimeoutExpired):
                    pass
            result = subprocess.run(
                ["adb", "connect", host_port],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            logger.info("adb connect {}: {}", host_port, (result.stdout or result.stderr or "").strip())
        return self.get_state() == "device"

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
            time.sleep(self.backoff_seconds * attempt)
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
