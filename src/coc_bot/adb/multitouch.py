"""Pinned scrcpy touch transport. Caller must hold the device lease.

Uses the existing main Android display; does not create a window or video stream.
"""
from contextlib import suppress
import hashlib
import math
from pathlib import Path
import secrets
import socket
import struct
import subprocess
import tempfile
import time

from coc_bot.adb.client import AdbClient, AdbStopped
from coc_bot.web.live import VERSION, SERVER_SHA256, server_path


def touch_packet(action, pointer, x, y, width, height):
    values = (action, pointer, x, y, width, height)
    if any(type(v) is not int for v in values):
        raise ValueError('Touch coordinates and IDs must be integers')
    if action not in (0, 1, 2) or pointer not in (0, 1):
        raise ValueError('Unsupported touch action or finger')
    if not (0 < width <= 65535 and 0 < height <= 65535 and 0 <= x < width and 0 <= y < height):
        raise ValueError('Touch outside display')
    return struct.pack('>BBQiiHHHII', 2, action, pointer, x, y, width, height,
                       0 if action == 1 else 65535, 0, 0)


class Multitouch:
    def __init__(self, client, dimensions, path=None):
        self.client = client
        self.width, self.height = dimensions
        touch_packet(0, 0, 0, 0, self.width, self.height)
        self.path = Path(path) if path else server_path()
        self.connection = self.process = self.logs = self.port = None
        self.active = {}

    def stopping(self):
        return bool(self.client.stop_check and self.client.stop_check())

    def check_stop(self):
        if self.stopping():
            raise AdbStopped('Zoom cancelled')

    def __enter__(self):
        self.check_stop()
        if not self.path.is_file() or hashlib.sha256(self.path.read_bytes()).hexdigest() != SERVER_SHA256:
            raise ValueError('Missing or invalid pinned scrcpy server; install Live view dependencies')
        scid = f'{secrets.randbits(31):08x}'
        remote = f'/data/local/tmp/coc-touch-{VERSION}.jar'
        try:
            self.client.run(['push', str(self.path), remote], timeout=10)
            port = self.client.run(['forward', 'tcp:0', 'localabstract:scrcpy_' + scid], timeout=5).stdout.strip()
            if not port.isdigit() or not 0 < int(port) <= 65535:
                raise ValueError('Invalid multitouch forwarding port')
            self.port = int(port)
            self.logs = tempfile.TemporaryFile()
            self.process = subprocess.Popen([
                'adb', '-s', self.client.device, 'shell', f'CLASSPATH={remote}', 'app_process', '/',
                'com.genymobile.scrcpy.Server', VERSION, f'scid={scid}', 'tunnel_forward=true',
                'video=false', 'audio=false', 'control=true', 'send_device_meta=false',
                'send_dummy_byte=true', 'power_on=false', 'clipboard_autosync=false', 'cleanup=false'],
                stdout=self.logs, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                self.check_stop()
                if self.process.poll() is not None:
                    break
                try:
                    self.connection = socket.create_connection(('127.0.0.1', self.port), timeout=.25)
                    self.connection.settimeout(.25)
                    greeting = self.connection.recv(1)
                    if not greeting:
                        # ADB can accept the forwarded connection before Android
                        # has created the abstract socket, then immediately close it.
                        raise ConnectionError('Touch server is not ready')
                    if greeting != b'\0':
                        raise ValueError('Invalid scrcpy touch handshake')
                    return self
                except (ConnectionError, TimeoutError):
                    if self.connection:
                        self.connection.close()
                        self.connection = None
                    time.sleep(.05)
            self.logs.seek(0)
            detail = self.logs.read().decode(errors='replace')[-1000:]
            raise RuntimeError('Multitouch server failed to connect: ' + detail)
        except BaseException:
            self.close()
            raise

    def _send(self, action, finger, point):
        if action != 1:
            self.check_stop()
        packet = touch_packet(action, finger, *point, self.width, self.height)
        if action == 0:
            self.active[finger] = point
        self.connection.sendall(packet)
        if action == 1:
            self.active.pop(finger, None)
        else:
            self.active[finger] = point

    def release_fingers(self):
        for finger, point in sorted(list(self.active.items()), reverse=True):
            with suppress(OSError, ValueError):
                self._send(1, finger, point)

    def pinch(self, *, start_span=.60, end_span=.16, duration=.6, steps=24):
        if (type(steps) is not int or not 4 <= steps <= 120 or
                any(type(v) not in (int, float) or not math.isfinite(v)
                    for v in (start_span, end_span, duration)) or
                not .06 <= start_span <= .70 or not .06 <= end_span <= .70 or
                not .2 <= duration <= 2):
            raise ValueError('Invalid pinch parameters')
        if not self.connection or self.active:
            raise ValueError('Touch session is unavailable or already active')
        def points(span):
            return [(round(self.width * (.5-span/2)), round(self.height*.42)),
                    (round(self.width * (.5+span/2)), round(self.height*.42))]
        try:
            for finger, point in enumerate(points(start_span)):
                self._send(0, finger, point)
            started = time.monotonic()
            for i in range(1, steps+1):
                deadline = started + duration*i/steps
                while time.monotonic() < deadline:
                    self.check_stop()
                    time.sleep(min(.01, max(0, deadline-time.monotonic())))
                for finger, point in enumerate(points(start_span+(end_span-start_span)*i/steps)):
                    self._send(2, finger, point)
        finally:
            self.release_fingers()

    def close(self):
        self.release_fingers()
        if self.connection:
            self.connection.close()
            self.connection = None
        if self.process:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(2)
            self.process = None
        if self.port:
            # Stop must not prevent removal of this session's own forwarding rule.
            with suppress(Exception):
                AdbClient(self.client.device).run(['forward', '--remove', f'tcp:{self.port}'], timeout=3)
            self.port = None
        if self.logs:
            self.logs.close()
            self.logs = None

    def __exit__(self, *args):
        self.close()
