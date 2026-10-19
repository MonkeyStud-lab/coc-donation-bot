#!/usr/bin/env python3
"""Standard-library-only host helper; fixed runtime commands over a Unix socket.

Installed configuration is root-owned. The web app cannot pass shell commands,
package names, file paths, or service names. Lease connections share the existing
host flock protocol so a desktop bot cannot compete with the container.
"""
import argparse
import base64
import fcntl
import hashlib
from http.server import BaseHTTPRequestHandler
import ipaddress
import json
import os
from pathlib import Path
import pwd
import socket
import socketserver
import stat
import struct
import subprocess
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlparse


ADB_PREPARED = Path("/var/lib/coc-casaos/android-adb-prepared")


def adb_public_key(profile, uid):
    """Read only the app-owned, bounded Android public key; never its private key."""
    root = Path(profile).resolve()
    path = root / ".android/adbkey.pub"
    if not path.resolve().is_relative_to(root):
        raise RuntimeError("ADB public key must stay inside the app profile")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != uid or not 1 <= info.st_size <= 4096:
            raise RuntimeError("ADB public key must be a small app-owned regular file")
        try:
            token = source.read(4097).split()[0].decode("ascii")
            raw = base64.b64decode(token, validate=True)
            if len(raw) != 524 or struct.unpack_from("<I", raw)[0] != 64 or struct.unpack_from("<I", raw, 520)[0] not in (3, 65537):
                raise ValueError("Not an Android RSA public key")
        except (UnicodeError, ValueError, IndexError) as exc:
            raise RuntimeError("Invalid Android ADB public key") from exc
    return token


class Runtime:
    def __init__(self, config):
        self.config = config
        self.user = pwd.getpwnam(config["user"])
        self.operations = threading.Lock()

    def command(self, args, *, user=False, check=True, timeout=30):
        if user and os.geteuid() == 0:
            args = ["runuser", "-u", self.user.pw_name, "--", "env",
                    "XDG_RUNTIME_DIR=/run/user/" + str(self.user.pw_uid),
                    "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/" + str(self.user.pw_uid) + "/bus",
                    "WAYLAND_DISPLAY=" + self.config["display"], *args]
        result = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
        if check and result.returncode:
            raise RuntimeError((result.stderr or result.stdout).strip()[-1500:] or "Runtime command failed")
        return result.stdout

    def android_booted(self, timeout=30):
        # Read through LXC, not ADB: status checks must not create a shared ADB
        # server with the helper/session user's identity before the app starts.
        return self.command(["lxc-attach", "-P", "/var/lib/waydroid/lxc", "-n", "waydroid",
            "--", "/system/bin/getprop", "sys.boot_completed"], check=False, timeout=timeout).strip() == "1"

    @staticmethod
    def adb_port_ready(ip):
        try:
            with socket.create_connection((ip, 5555), timeout=1):
                return True
        except OSError:
            return False

    def authorize_adb(self):
        """Enroll only the managed app's key; retain Android ADB authentication."""
        if not self.config.get("prepare_adb"):
            return False
        if not self.config.get("profile"):
            raise RuntimeError("Refresh the host helper to configure the managed ADB identity")
        token = adb_public_key(self.config["profile"], self.config.get("app_uid", 1000))
        existing = self.command(["waydroid", "shell", "cat", "/data/misc/adb/adb_keys"], check=False)
        present = token in {line.split()[0] for line in existing.splitlines() if line.split()}
        if not present:
            # token contains validated base64 only. Paths and permissions are
            # fixed here; browser requests never supply keys or shell commands.
            script = ("umask 027; mkdir -p /data/misc/adb && "
                      "chown 1000:2000 /data/misc/adb && chmod 2750 /data/misc/adb && "
                      "printf '%s\\n' '" + token + " coc-bot' >> /data/misc/adb/adb_keys && "
                      "chown 1000:2000 /data/misc/adb/adb_keys && "
                      "chmod 640 /data/misc/adb/adb_keys && restorecon /data/misc/adb /data/misc/adb/adb_keys")
            try:
                self.command(["waydroid", "shell", "--", "sh", "-c", script])
            except RuntimeError as exc:
                raise RuntimeError(str(exc).replace(token, "<managed ADB public key>")) from None
        return not present

    def status(self):
        text = self.command(["waydroid", "status"], user=True, check=False)
        values = {key.strip(): value.strip() for key, value in
                  (line.split(":", 1) for line in text.splitlines() if ":" in line)}
        ip = None
        try:
            ip = str(ipaddress.IPv4Address(values.get("IP address", "")))
        except ipaddress.AddressValueError:
            # A new session reports UNKNOWN until Android's network is ready.
            # Keep waiting; never publish a placeholder as an ADB address.
            pass
        if ip:
            # Some LXC/Waydroid combinations report STOPPED for a healthy payload.
            # Confirm Android itself rather than restarting a reachable session.
            if values.get("Container") == "STOPPED":
                try:
                    boot = self.android_booted(timeout=3)
                except subprocess.TimeoutExpired:
                    boot = False
                if boot:
                    values["Container"] = "RUNNING"
                else:
                    # Waydroid may retain RUNNING session metadata after its user
                    # process exits. An unavailable stopped payload needs startup.
                    values["Session"] = "STOPPED"
                text = "\n".join(key + ":\t" + value for key, value in values.items()) + "\n"
            destination = Path(self.config["socket"]).with_name("device.json")
            # Unique temporary names: status requests may arrive concurrently.
            fd, name = tempfile.mkstemp(dir=destination.parent, prefix="device-")
            with os.fdopen(fd, "w") as file:
                json.dump({"ip": ip}, file)
            os.chmod(name, 0o644)
            os.replace(name, destination)
        return {"raw_status": text, "ip": ip,
                "session": values.get("Session", "STOPPED"),
                "container": values.get("Container", "STOPPED")}

    def resume(self):
        status = self.status()
        if status["container"] == "FROZEN":
            self.command(["gdbus", "call", "--system", "--dest", "id.waydro.Container",
                "--object-path", "/ContainerManager", "--method", "id.waydro.ContainerManager.Unfreeze"])
        return self.status()

    def adopted_unit(self, name, command):
        loaded = self.command(["systemctl", "show", name + ".service", "--property=LoadState", "--value"], check=False).strip()
        if loaded == "loaded":
            self.command(["systemctl", "start", "--no-block", name + ".service"])
            return
        uid = str(self.user.pw_uid)
        self.command(["systemd-run", "--unit=" + name, "--uid=" + self.user.pw_name,
            "--setenv=XDG_RUNTIME_DIR=/run/user/" + uid,
            "--setenv=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/" + uid + "/bus",
            "--setenv=WAYLAND_DISPLAY=" + self.config["display"],
            "/usr/bin/waydroid", *command])

    def ensure(self):
        if not self.operations.acquire(blocking=False):
            raise RuntimeError("Another runtime operation is finishing; retry shortly")
        try:
            status = self.status()
            adopted_start = False
            if self.config.get("manage_services", True):
                self.command(["systemctl", "start", "waydroid-container.service"])
                if status["session"] != "RUNNING":
                    self.command(["systemctl", "start", "coc-waydroid-session.service"], timeout=60)
            elif status["session"] != "RUNNING":
                display = Path("/run/user") / str(self.user.pw_uid) / self.config["display"]
                if not display.is_socket():
                    raise RuntimeError("The adopted desktop display is unavailable. Log into its Wayland session, then Retry.")
                self.adopted_unit("coc-waydroid-adopted-session", ["session", "start"])
                adopted_start = True
            # First Android boot also prepares app data; give slow fresh hosts
            # time without lengthening ordinary reopen/failure recovery.
            managed_adb = bool(self.config.get("prepare_adb"))
            first_boot = managed_adb and not ADB_PREPARED.exists()
            configured = not first_boot
            deadline = time.monotonic() + (600 if first_boot else 180)
            while time.monotonic() < deadline:
                status = self.resume()
                running = bool(status["ip"] and status["session"] == "RUNNING" and status["container"] == "RUNNING")
                booted = running and (not managed_adb or self.android_booted())
                if booted and not configured:
                    for args in (["settings", "put", "global", "adb_enabled", "1"],
                                 ["setprop", "persist.adb.tcp.port", "5555"],
                                 ["setprop", "service.adb.tcp.port", "5555"]):
                        self.command(["waydroid", "shell", *args])
                    self.authorize_adb()
                    if not self.adb_port_ready(status["ip"]):
                        self.command(["waydroid", "shell", "setprop", "ctl.restart", "adbd"])
                    configured = True
                if booted and configured:
                    self.authorize_adb()
                    if managed_adb:
                        if not self.adb_port_ready(status["ip"]):
                            time.sleep(1)
                            continue
                        if first_boot:
                            ADB_PREPARED.parent.mkdir(parents=True, exist_ok=True)
                            ADB_PREPARED.write_text("configured\n")
                    if self.config.get("needs_ui"):
                        self.command(["systemctl", "start", "--no-block", "coc-waydroid-ui.service"])
                    elif adopted_start:
                        self.adopted_unit("coc-waydroid-adopted-ui", ["show-full-ui"])
                    return status
                time.sleep(1)
            raise RuntimeError("Waydroid did not become ready; inspect the host service logs")
        finally:
            self.operations.release()

    def stop(self):
        if not self.operations.acquire(blocking=False):
            raise RuntimeError("Wait for startup to finish before closing Waydroid")
        try:
            # Do not stop the global container: the explicit action closes this session.
            if self.config.get("manage_services", True):
                if self.config.get("needs_ui"):
                    self.command(["systemctl", "stop", "coc-waydroid-ui.service"])
                self.command(["systemctl", "stop", "coc-waydroid-session.service"])
            else:
                for name in ("coc-waydroid-adopted-ui.service", "coc-waydroid-adopted-session.service"):
                    self.command(["systemctl", "stop", name], check=False)
            self.command(["waydroid", "session", "stop"], user=True, timeout=40)
            return self.status()
        finally:
            self.operations.release()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def respond(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.headers.get("Content-Length", "0") != "0" or self.headers.get("Transfer-Encoding"):
            self.close_connection = True
            return self.respond({"error": "Request bodies are not accepted"}, 400)
        actions = {"/v1/ensure": self.server.runtime.ensure,
                   "/v1/resume": self.server.runtime.resume,
                   "/v1/stop": self.server.runtime.stop}
        action = actions.get(self.path)
        if action is None:
            return self.respond({"error": "Unknown runtime action"}, 404)
        try:
            self.respond(action())
        except Exception as exc:
            self.respond({"error": str(exc)}, 503)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/v1/status" and not parsed.query:
            try:
                return self.respond(self.server.runtime.status())
            except Exception as exc:
                return self.respond({"error": str(exc)}, 503)
        if parsed.path != "/v1/lease":
            return self.respond({"error": "Unknown runtime action"}, 404)
        arguments = parse_qs(parsed.query)
        serials = arguments.get("device", [])
        try:
            status = self.server.runtime.status()
            if set(arguments) != {"device"} or len(serials) != 1 or serials[0] != status["ip"] + ":5555":
                return self.respond({"error": "Device does not match managed Waydroid"}, 400)
            digest = hashlib.sha256(serials[0].encode()).hexdigest()
            path = Path(tempfile.gettempdir()) / ("coc-bot-device-" + digest + ".lock")
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                pass
            else:
                if os.geteuid() == 0:
                    os.fchown(fd, self.server.runtime.user.pw_uid, self.server.runtime.user.pw_gid)
                os.close(fd)
            with path.open("r+b") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    return self.respond({"error": "Another bot or tool is controlling Waydroid"}, 409)
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()
                self.wfile.flush()
                self.connection.settimeout(None)
                # EOF releases a lost client. R requests an acknowledged release.
                released = self.connection.recv(1)
            if released == b"R":
                self.connection.sendall(b"A")
            self.close_connection = True
        except Exception as exc:
            self.respond({"error": str(exc)}, 503)


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def notify_ready():
    """Let systemd complete startup only after the request socket is listening."""
    address = os.environ.get("NOTIFY_SOCKET")
    if address:
        if address.startswith("@"):
            address = "\0" + address[1:]
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as notification:
            notification.sendto(b"READY=1", address)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="/etc/coc-casaos/host.json")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    runtime = Runtime(config)
    path = Path(config["socket"])
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            probe = socket.socket(socket.AF_UNIX)
            probe.connect(str(path))
        except (ConnectionRefusedError, FileNotFoundError):
            path.unlink(missing_ok=True)
        else:
            raise RuntimeError("Host helper is already running")
        finally:
            probe.close()
    with Server(str(path), Handler) as server:
        server.runtime = runtime
        os.chmod(path, 0o600)
        if os.geteuid() == 0:
            os.chown(path, config.get("app_uid", runtime.user.pw_uid), config.get("app_gid", runtime.user.pw_gid))
        notify_ready()
        server.serve_forever(poll_interval=.2)


if __name__ == "__main__":
    main()
