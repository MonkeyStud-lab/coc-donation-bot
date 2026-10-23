"""On-demand scrcpy video, passed through to WebRTC as H.264.

The Android server is pinned because scrcpy's internal protocol is versioned.
Input is optional and uses a separate exclusive, cancellable ADB lease.
No decoded screenshots, external STUN, or recording is used.
"""
import asyncio
from contextlib import suppress
from fractions import Fraction
import hashlib
from pathlib import Path
import secrets
import shutil
import struct

VERSION = "3.3.3"
SERVER_SHA256 = "7e70323ba7f259649dd4acce97ac4fefbae8102b2c6d91e2e7be613fd5354be0"
SERVER_URL = f"https://github.com/Genymobile/scrcpy/releases/download/v{VERSION}/scrcpy-server-v{VERSION}"


def server_path():
    from coc_bot.config import project_root
    return project_root() / "data/live" / f"scrcpy-server-v{VERSION}"


def check_dependencies():
    try:
        import aiortc  # noqa: F401
        import av  # noqa: F401
    except ImportError as exc:
        raise ValueError("Install live view first: python -m pip install -e '.[web,web-live]' and python scripts/setup_live_view.py") from exc
    path = server_path()
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != SERVER_SHA256:
        raise ValueError("Live view server missing or invalid. Run python scripts/setup_live_view.py")
    return path


class ScrcpySource:
    def __init__(self, device, path):
        self.device, self.path = device, Path(path)
        self.scid = secrets.token_hex(4)
        # scrcpy accepts a signed 31-bit identifier.
        self.scid = f"{int(self.scid, 16) & 0x7fffffff:08x}"
        self.port = None
        self.process = None
        self.reader = self.writer = None
        self.logs = []
        self.log_task = None
        self.wake_task = None
        self.waydroid_device = False
        self.width = self.height = 0
        self.config = b""
        self.first_pts = None
        self.packets = 0
        self.capture_failed = False

    async def adb(self, *args):
        process = await asyncio.create_subprocess_exec("adb", "-s", self.device, *args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, err = await asyncio.wait_for(process.communicate(), 15)
            if process.returncode:
                raise ValueError("Live view ADB failed: " + err.decode(errors="replace")[-500:])
            return out.decode().strip()
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()

    async def start(self):
        await self.wake_waydroid()
        if self.waydroid_device:
            async def keep_awake():
                try:
                    while True:
                        await asyncio.sleep(3)
                        await self.wake_waydroid()
                except Exception as exc:
                    self.logs.append("Waydroid resume failed: " + str(exc)[:500])
            self.wake_task = asyncio.create_task(keep_awake())
        remote = f"/data/local/tmp/coc-live-{VERSION}.jar"
        await self.adb("push", str(self.path), remote)
        self.port = await self.adb("forward", "tcp:0", "localabstract:scrcpy_" + self.scid)
        self.process = await asyncio.create_subprocess_exec("adb", "-s", self.device, "shell",
            f"CLASSPATH={remote}", "app_process", "/", "com.genymobile.scrcpy.Server", VERSION,
            f"scid={self.scid}", "tunnel_forward=true", "audio=false", "control=false",
            "max_size=1280", "max_fps=20", "video_bit_rate=2000000", "video_codec=h264",
            "video_codec_options=i-frame-interval=1", "send_device_meta=false",
            "send_dummy_byte=true", "send_codec_meta=true", "send_frame_meta=true", "power_on=false",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        async def collect_logs():
            while line := await self.process.stdout.readline():
                self.logs.append(line.decode(errors="replace")[:500].strip())
                self.logs = self.logs[-12:]
        self.log_task = asyncio.create_task(collect_logs())
        for _ in range(40):
            if self.process.returncode is not None:
                raise ValueError("Android video encoder failed: " + " ".join(self.logs)[-1000:])
            try:
                reader, writer = await asyncio.open_connection("127.0.0.1", int(self.port))
                self.reader, self.writer = reader, writer
                await asyncio.wait_for(reader.readexactly(1), .5)
                metadata = await asyncio.wait_for(reader.readexactly(12), 10)
                codec, self.width, self.height = struct.unpack(">4sII", metadata)
                if codec != b"h264" or not 0 < self.width <= 4096 or not 0 < self.height <= 4096:
                    raise ValueError("Unsupported live video metadata")
                return
            except (ConnectionError, asyncio.IncompleteReadError, asyncio.TimeoutError):
                if self.writer:
                    self.writer.close()
                    await self.writer.wait_closed()
                    self.reader = self.writer = None
                await asyncio.sleep(.1)
        raise ValueError("Could not start Android video: " + " ".join(self.logs)[-1000:])

    async def wake_waydroid(self):
        """Resume an already-running matching Waydroid container, without a window.

        A frozen container accepts ADB connections but cannot render video. Do
        not start a stopped session or change any of its persistent settings.
        """
        if not shutil.which("waydroid") or not shutil.which("gdbus"):
            return
        async def command(*args):
            process = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE,
                                                          stderr=asyncio.subprocess.PIPE)
            try:
                out, err = await asyncio.wait_for(process.communicate(), 10)
                if process.returncode:
                    raise ValueError("Cannot resume Waydroid: " + err.decode(errors="replace")[-500:])
                return out.decode(errors="replace")
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
        status = await command("waydroid", "status")
        values = dict(line.split(":", 1) for line in status.splitlines() if ":" in line)
        self.waydroid_device = values.get("IP address", "").strip() == self.device.split(":")[0]
        if values.get("Container", "").strip() == "FROZEN" and self.waydroid_device:
            await command("gdbus", "call", "--system", "--dest", "id.waydro.Container",
                          "--object-path", "/ContainerManager", "--method", "id.waydro.ContainerManager.Unfreeze")

    async def packet(self):
        while True:
            header = await asyncio.wait_for(self.reader.readexactly(12), 10)
            stamp, size = struct.unpack(">QI", header)
            if not 0 < size <= 4 * 1024 * 1024:
                raise ValueError("Invalid live video packet size")
            payload = await asyncio.wait_for(self.reader.readexactly(size), 10)
            if stamp & (1 << 63):
                self.config = payload
                continue
            pts = stamp & ((1 << 62) - 1)
            if self.first_pts is None:
                self.first_pts = pts
            import av
            packet = av.Packet((self.config if stamp & (1 << 62) else b"") + payload)
            packet.pts = packet.dts = pts - self.first_pts
            packet.time_base = Fraction(1, 1_000_000)
            self.packets += 1
            from coc_bot.adb.capture_coordinator import capture_succeeded
            capture_succeeded(self.device)
            return packet

    async def close(self):
        if self.wake_task:
            self.wake_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.wake_task
            self.wake_task = None
        if self.writer:
            self.writer.close()
            with suppress(Exception):
                await self.writer.wait_closed()
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 3)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
        if self.log_task:
            await self.log_task
        if self.port:
            with suppress(Exception):
                await self.adb("forward", "--remove", "tcp:" + self.port)
        self.port = None


async def run_live(ws, auth, origins, owner_lock, service):
    """A single stream per server, with explicit manual control while idle."""
    if ws.headers.get("origin") not in origins or not auth.session(ws.cookies.get("coc_session")):
        await ws.close(code=1008)
        return
    await ws.accept()
    if owner_lock.locked():
        await ws.send_json({"type": "error", "message": "Live view is already open in another tab."})
        await ws.close()
        return
    async with owner_lock:
        source = peer = control = None
        try:
            path = check_dependencies()
            from aiortc import RTCPeerConnection, RTCConfiguration, RTCSessionDescription, VideoStreamTrack, RTCRtpSender
            from coc_bot.config import load_config
            source = ScrcpySource(load_config().adb_device, path)
            from coc_bot.web.live_control import LiveControl
            control = LiveControl(service, source.device)
            # Negotiate first: otherwise Android queues old frames while the
            # browser gathers ICE candidates and the user initially sees a still.
            pending = []
            source_ready = asyncio.Event()
            failed = asyncio.Event()
            class EncodedTrack(VideoStreamTrack):
                async def recv(self):
                    try:
                        await source_ready.wait()
                        if pending:
                            return pending.pop()
                        return await source.packet()
                    except Exception:
                        source.capture_failed = True
                        failed.set()
                        raise
            peer = RTCPeerConnection(RTCConfiguration(iceServers=[]))
            peer.addTrack(EncodedTrack())
            codecs = [c for c in RTCRtpSender.getCapabilities("video").codecs
                      if c.mimeType == "video/H264" and c.parameters.get("profile-level-id") == "42e01f"]
            peer.getTransceivers()[0].setCodecPreferences(codecs)
            await ws.send_json({"type": "ready"})
            message = await asyncio.wait_for(ws.receive_json(), 15)
            if message.get("type") != "offer" or not isinstance(message.get("sdp"), str) or len(message["sdp"]) > 20000:
                raise ValueError("Invalid live view offer")
            await peer.setRemoteDescription(RTCSessionDescription(message["sdp"], "offer"))
            await peer.setLocalDescription(await peer.createAnswer())
            try:
                await source.start()
                # Metadata alone is not proof that Android can produce video.
                pending.append(await source.packet())
            except Exception:
                source.capture_failed = True
                raise
            source_ready.set()
            await ws.send_json({"type": "answer", "sdp": peer.localDescription.sdp})
            import time
            last_message = time.monotonic()
            while auth.session(ws.cookies.get("coc_session")):
                if control.token and control.cancel.is_set():
                    control.release()
                    await ws.send_json({"type": "control", "token": None})
                try:
                    message = await asyncio.wait_for(ws.receive_json(), .5)
                except asyncio.TimeoutError:
                    if time.monotonic() - last_message > 20:
                        raise ValueError("Live view disconnected")
                    continue
                last_message = time.monotonic()
                if failed.is_set() or peer.connectionState in ("failed", "closed") or source.process.returncode is not None:
                    raise ValueError("Live stream disconnected. Close and reopen Live view.")
                try:
                    if message.get("type") == "ping":
                        await ws.send_json({"type": "pong"})
                    elif message.get("type") == "take_control":
                        token = await control.acquire()
                        await ws.send_json({"type": "control", "token": token})
                    elif message.get("type") == "release_control":
                        control.release()
                        await ws.send_json({"type": "control", "token": None})
                    elif message.get("type") in ("tap", "swipe", "key"):
                        await control.input(message)
                    else:
                        raise ValueError("Unsupported live view command")
                except Exception as exc:
                    control.release()
                    await ws.send_json({"type": "control", "token": None, "message": str(exc)})
        except asyncio.TimeoutError:
            with suppress(Exception):
                await ws.send_json({"type": "error", "message": "Android produced no video or the connection timed out. This Waydroid build may not support scrcpy capture. Use Diagnostics → Open game instead."})
        except Exception as exc:
            with suppress(Exception):
                await ws.send_json({"type": "error", "message": str(exc) or "Live view disconnected"})
        finally:
            if control:
                control.release()
            if peer:
                await peer.close()
            if source:
                await source.close()
                if getattr(source, 'capture_failed', False):
                    from coc_bot.adb.capture_coordinator import capture_failed
                    capture_failed(source.device)
                    recovery = getattr(service, 'capture_recovery', None)
                    if recovery is not None:
                        recovery.request(source.device)
            with suppress(Exception):
                await ws.close()
