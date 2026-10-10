"""On-demand low-frame-rate viewer with an exclusive input lease.

Complete tap/swipe commands avoid leaving held touches on disconnect.
No stream exists until the user explicitly opens it.
"""
from contextlib import suppress
import asyncio
import json
import secrets
import threading
import time
import cv2
from coc_bot.runtime.device_lease import DeviceLease


async def run_viewer(ws, service, auth, origins):
    if ws.headers.get("origin") not in origins or not auth.session(ws.cookies.get("coc_session")):
        await ws.close(code=1008)
        return
    owner, cancel = secrets.token_hex(16), threading.Event()
    lease = None
    async def device_call(function, *args):
        task = asyncio.create_task(asyncio.to_thread(function, *args))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            cancel.set()
            # Retain ownership until a command that is already running exits.
            with suppress(Exception):
                await task
            raise
    try:
        with service.lock:
            service.idle()
            service.manual_owner = owner
            service.manual_cancel = cancel
        session = await device_call(service.session, cancel)
        lease = DeviceLease(session.config.adb_device)
        lease.__enter__()
        await ws.accept()
        await ws.send_json({"type": "ready"})
        last_input, last_frame, dimensions = 0.0, 0.0, None
        idle_since = time.monotonic()
        while not cancel.is_set() and auth.session(ws.cookies.get("coc_session")):
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=1)
            except asyncio.TimeoutError:
                if time.monotonic()-idle_since > 60:
                    break
                continue
            idle_since = time.monotonic()
            if len(raw) > 2000:
                raise ValueError("Viewer command too large")
            message = json.loads(raw)
            command, now = message.get("type"), time.monotonic()
            if command == "frame":
                await asyncio.sleep(max(0, 1.0 - (now-last_frame)))
                frame = await device_call(session.capture.screenshot)
                dimensions = (frame.shape[1], frame.shape[0])
                ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                if not ok:
                    raise ValueError("Viewer cannot encode frame")
                await ws.send_bytes(encoded.tobytes())
                last_frame = time.monotonic()
            elif command in ("tap", "swipe"):
                if dimensions is None or now-last_input < .15:
                    continue
                def point(key):
                    p = message.get(key)
                    if not isinstance(p, list) or len(p) != 2 or any(type(n) is not int for n in p):
                        raise ValueError("Invalid viewer coordinates")
                    if not (0 <= p[0] < dimensions[0] and 0 <= p[1] < dimensions[1]):
                        raise ValueError("Viewer coordinates out of range")
                    return p
                a = point("from")
                if command == "tap":
                    await device_call(session.client.run, ["shell", "input", "tap", *map(str, a)])
                else:
                    b = point("to")
                    await device_call(session.client.run,
                        ["shell", "input", "swipe", *map(str, a), *map(str, b), "300"])
                last_input = now
            elif command == "key":
                if now-last_input < .15:
                    continue
                keys = {"back": "KEYCODE_BACK", "home": "KEYCODE_HOME"}
                if message.get("key") not in keys:
                    raise ValueError("Unsupported viewer key")
                await device_call(session.client.run,
                    ["shell", "input", "keyevent", keys[message["key"]]])
                last_input = now
            else:
                raise ValueError("Unknown viewer command")
        await ws.close()
    except Exception:
        with suppress(Exception):
            await ws.close(code=1011, reason="Viewer closed or device busy")
    finally:
        cancel.set()
        if lease:
            lease.__exit__()
        with service.lock:
            if service.manual_owner == owner:
                service.manual_owner = None
                service.manual_cancel = None
        # Manual control never resumes the bot.
