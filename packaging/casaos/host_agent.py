#!/usr/bin/env python3
"""Standard-library-only host helper; fixed runtime commands over a Unix socket.

Installed configuration is root-owned. The web app cannot pass shell commands,
package names, file paths, or service names. Lease connections share the existing
host flock protocol so a desktop bot cannot compete with the container.
"""
import argparse
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
import subprocess
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlparse


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

    def status(self):
        text = self.command(["waydroid", "status"], user=True, check=False)
        values = {key.strip(): value.strip() for key, value in
                  (line.split(":", 1) for line in text.splitlines() if ":" in line)}
        ip = values.get("IP address")
        if ip:
            ip = str(ipaddress.IPv4Address(ip))
            # Some LXC/Waydroid combinations report STOPPED for a healthy payload.
            # Confirm Android itself rather than restarting a reachable session.
            if values.get("Container") == "STOPPED":
                try:
                    boot = self.command(["adb", "-s", ip + ":5555", "shell", "getprop", "sys.boot_completed"],
                                        user=True, check=False, timeout=3)
                except subprocess.TimeoutExpired:
                    boot = ""
                if boot.strip() == "1":
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
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                status = self.resume()
                marker = Path("/var/lib/coc-casaos/android-adb-prepared")
                if self.config.get("prepare_adb") and not marker.exists() and status["session"] == "RUNNING":
                    boot = self.command(["waydroid", "shell", "getprop", "sys.boot_completed"], check=False)
                    if boot.strip() == "1":
                        # Only a newly initialized package Android image reaches this branch.
                        for args in (["settings", "put", "global", "adb_enabled", "1"],
                                     ["setprop", "persist.adb.tcp.port", "5555"],
                                     ["setprop", "service.adb.tcp.port", "5555"],
                                     ["stop", "adbd"], ["start", "adbd"]):
                            self.command(["waydroid", "shell", *args])
                        marker.parent.mkdir(parents=True, exist_ok=True)
                        marker.write_text("configured\n")
                        status = self.status()
                if status["ip"] and status["session"] == "RUNNING" and status["container"] == "RUNNING":
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
        server.serve_forever(poll_interval=.2)


if __name__ == "__main__":
    main()
