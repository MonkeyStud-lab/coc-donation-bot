"""
Multi-touch pinch injection for zoom.

ADB ``input swipe`` is single-touch only, so parallel swipes do not zoom.
This module finds the touchscreen and injects a real two-finger pinch via
``sendevent`` (needs write access to ``/dev/input/event*`` — usually works
after ``adb root`` on Waydroid).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from loguru import logger

from coc_bot.adb.client import AdbClient, AdbError

# Linux input event codes
EV_SYN = 0
EV_KEY = 1
EV_ABS = 3
SYN_REPORT = 0
BTN_TOUCH = 330
ABS_MT_SLOT = 47
ABS_MT_POSITION_X = 53
ABS_MT_POSITION_Y = 54
ABS_MT_TRACKING_ID = 57


@dataclass(frozen=True)
class TouchDevice:
    path: str
    name: str
    max_x: int
    max_y: int


@dataclass(frozen=True)
class ZoomResult:
    ok: bool
    method: str
    detail: str


def _parse_getevent_devices(text: str) -> list[TouchDevice]:
    devices: list[TouchDevice] = []
    current_path: str | None = None
    current_name = ""
    max_x = 0
    max_y = 0
    has_mt = False

    def flush() -> None:
        nonlocal current_path, current_name, max_x, max_y, has_mt
        if current_path and has_mt and max_x > 0 and max_y > 0:
            devices.append(
                TouchDevice(path=current_path, name=current_name or current_path, max_x=max_x, max_y=max_y)
            )
        current_path = None
        current_name = ""
        max_x = 0
        max_y = 0
        has_mt = False

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("add device") and "/dev/input/" in line:
            flush()
            m = re.search(r"(/dev/input/event\d+)", line)
            current_path = m.group(1) if m else None
            continue
        if current_path is None:
            continue
        if line.startswith("name:"):
            current_name = line.split(":", 1)[1].strip().strip('"')
            continue
        if "ABS_MT_POSITION_X" in line:
            has_mt = True
            m = re.search(r"max\s+(\d+)", line)
            if m:
                max_x = int(m.group(1))
        elif "ABS_MT_POSITION_Y" in line:
            has_mt = True
            m = re.search(r"max\s+(\d+)", line)
            if m:
                max_y = int(m.group(1))
    flush()
    return devices


def discover_touch_device(client: AdbClient) -> TouchDevice | None:
    result = client.run_shell("getevent -pl 2>/dev/null", check=False)
    text = result.stdout or ""
    devices = _parse_getevent_devices(text)
    if not devices:
        logger.warning("No multitouch devices found via getevent -pl")
        return None

    def score(d: TouchDevice) -> int:
        name = d.name.lower()
        s = 0
        if "waydroid" in name:
            s += 50
        if "touch" in name or "touchscreen" in name:
            s += 30
        if "virtual" in name:
            s += 10
        if "keyboard" in name or "headset" in name or "button" in name:
            s -= 100
        return s

    devices.sort(key=score, reverse=True)
    best = devices[0]
    logger.info(
        "Using touch device {} ({}) abs max {}x{}",
        best.path,
        best.name,
        best.max_x,
        best.max_y,
    )
    return best


def _scale(v: int, screen_max: int, abs_max: int) -> int:
    if screen_max <= 1:
        return 0
    return max(0, min(abs_max, int(round(v * abs_max / (screen_max - 1)))))


def _build_pinch_script(
    device: TouchDevice,
    width: int,
    height: int,
    *,
    steps: int = 12,
) -> str:
    """Pinch-in (zoom out): two fingers start apart and move toward center."""
    cx, cy = width // 2, int(height * 0.45)
    span = int(min(width, height) * 0.30)
    start = [
        (cx - span, cy - span),
        (cx + span, cy + span),
    ]
    end = [
        (cx - span // 5, cy - span // 5),
        (cx + span // 5, cy + span // 5),
    ]

    lines = [
        "#!/system/bin/sh",
        f"DEV='{device.path}'",
        "se() { sendevent \"$DEV\" \"$1\" \"$2\" \"$3\"; }",
    ]

    def emit(etype: int, code: int, value: int) -> None:
        lines.append(f"se {etype} {code} {value}")

    def syn() -> None:
        emit(EV_SYN, SYN_REPORT, 0)

    def put_finger(slot: int, tracking: int, x: int, y: int) -> None:
        ax = _scale(x, width, device.max_x)
        ay = _scale(y, height, device.max_y)
        emit(EV_ABS, ABS_MT_SLOT, slot)
        emit(EV_ABS, ABS_MT_TRACKING_ID, tracking)
        emit(EV_ABS, ABS_MT_POSITION_X, ax)
        emit(EV_ABS, ABS_MT_POSITION_Y, ay)

    def move_finger(slot: int, x: int, y: int) -> None:
        ax = _scale(x, width, device.max_x)
        ay = _scale(y, height, device.max_y)
        emit(EV_ABS, ABS_MT_SLOT, slot)
        emit(EV_ABS, ABS_MT_POSITION_X, ax)
        emit(EV_ABS, ABS_MT_POSITION_Y, ay)

    # Touch down both fingers
    emit(EV_KEY, BTN_TOUCH, 1)
    put_finger(0, 1, start[0][0], start[0][1])
    syn()
    put_finger(1, 2, start[1][0], start[1][1])
    syn()

    for i in range(1, steps + 1):
        t = i / steps
        x0 = int(start[0][0] + (end[0][0] - start[0][0]) * t)
        y0 = int(start[0][1] + (end[0][1] - start[0][1]) * t)
        x1 = int(start[1][0] + (end[1][0] - start[1][0]) * t)
        y1 = int(start[1][1] + (end[1][1] - start[1][1]) * t)
        move_finger(0, x0, y0)
        move_finger(1, x1, y1)
        syn()

    # Lift
    emit(EV_ABS, ABS_MT_SLOT, 0)
    emit(EV_ABS, ABS_MT_TRACKING_ID, -1)
    syn()
    emit(EV_ABS, ABS_MT_SLOT, 1)
    emit(EV_ABS, ABS_MT_TRACKING_ID, -1)
    syn()
    emit(EV_KEY, BTN_TOUCH, 0)
    syn()
    return "\n".join(lines) + "\n"


def _write_remote_script(client: AdbClient, remote_path: str, content: str) -> None:
    """Write a script onto the device via adb shell cat."""
    import subprocess

    cmd = [*client._base_cmd(), "shell", f"cat > {remote_path}"]
    result = subprocess.run(
        cmd,
        input=content,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise AdbError(f"Failed to write {remote_path}: {stderr}")


def _run_via_waydroid_shell(remote_path: str) -> tuple[bool, str]:
    """
    Waydroid blocks ``adb root``. Privileged actions need host ``waydroid shell``.

    Tries passwordless sudo first, then plain ``waydroid shell``.
    """
    import shutil
    import subprocess

    if shutil.which("waydroid") is None:
        return False, "waydroid command not found on PATH"

    # Ensure executable bit inside the container (adb shell is enough for chmod).
    runners = [
        ["sudo", "-n", "waydroid", "shell", "sh", remote_path],
        ["waydroid", "shell", "sh", remote_path],
    ]
    last = "waydroid shell failed"
    for cmd in runners:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        out = ((result.stdout or "") + (result.stderr or "")).strip()
        last = out or f"exit {result.returncode}"
        if result.returncode == 0 and "Permission denied" not in out:
            return True, " ".join(cmd[:3]) if cmd[0] == "sudo" else "waydroid shell"
        logger.debug("Pinch via {} failed: {}", " ".join(cmd), last)
    return False, last


def _run_remote_script(client: AdbClient, remote_path: str) -> tuple[bool, str]:
    """Execute pinch script — ADB shell first, then Waydroid root shell."""
    client.run_shell(f"chmod 755 {remote_path}", check=False)

    for label, cmd in (
        ("adb sh", f"sh {remote_path}"),
        ("adb su 0", f"su 0 sh {remote_path}"),
    ):
        result = client.run_shell(cmd, check=False)
        out = ((result.stdout or "") + (result.stderr or "")).strip()
        if result.returncode == 0 and "Permission denied" not in out:
            return True, label
        logger.debug("Pinch script via {} failed (code={}): {}", label, result.returncode, out)

    ok, detail = _run_via_waydroid_shell(remote_path)
    if ok:
        return True, detail

    return (
        False,
        detail
        or "need privileged waydroid shell to write /dev/input "
        "(Waydroid does not support adb root). Try once: sudo waydroid shell",
    )


def pinch_zoom_out_sendevent(
    client: AdbClient,
    width: int,
    height: int,
    *,
    repeats: int = 3,
) -> ZoomResult:
    # Note: ``adb root`` is intentionally disabled on Waydroid.
    device = discover_touch_device(client)
    if device is None:
        return ZoomResult(False, "sendevent", "no multitouch device found")

    remote = "/data/local/tmp/coc_pinch_zoom.sh"
    script = _build_pinch_script(device, width, height)
    try:
        _write_remote_script(client, remote, script)
    except AdbError as exc:
        return ZoomResult(False, "sendevent", str(exc))

    last_detail = ""
    for i in range(max(1, repeats)):
        ok, detail = _run_remote_script(client, remote)
        last_detail = detail
        if not ok:
            return ZoomResult(False, "sendevent", detail)
        logger.info("Sendevent pinch zoom-out {}/{} ({})", i + 1, repeats, detail)
        time.sleep(0.35)

    return ZoomResult(True, "sendevent", f"{device.path} ({device.name}); {last_detail}")


def pinch_zoom_out_keyevent(client: AdbClient, *, repeats: int = 8) -> ZoomResult:
    """Try KEYCODE_ZOOM_OUT (169) — ignored by many games including CoC."""
    for _ in range(repeats):
        result = client.run_shell("input keyevent 169", check=False)
        if result.returncode != 0:
            return ZoomResult(False, "keyevent", (result.stderr or "keyevent failed").strip())
        time.sleep(0.08)
    return ZoomResult(True, "keyevent", f"sent KEYCODE_ZOOM_OUT x{repeats}")


def zoom_out(
    client: AdbClient,
    width: int,
    height: int,
    *,
    repeats: int = 3,
) -> ZoomResult:
    """
    Best-effort zoom out. Prefers real multitouch sendevent pinch.
    """
    result = pinch_zoom_out_sendevent(client, width, height, repeats=repeats)
    if result.ok:
        return result
    logger.warning("Sendevent pinch failed: {}", result.detail)
    return ZoomResult(
        False,
        "failed",
        f"{result.detail}\n\n"
        "Waydroid blocks adb root. Zoom needs a privileged Waydroid shell.\n"
        "One-time setup (allows passwordless zoom):\n"
        "  sudo visudo\n"
        "  # add:  YOUR_USER ALL=(root) NOPASSWD: /usr/bin/waydroid shell\n"
        "Or run once manually to test:\n"
        "  sudo waydroid shell sh /data/local/tmp/coc_pinch_zoom.sh",
    )
