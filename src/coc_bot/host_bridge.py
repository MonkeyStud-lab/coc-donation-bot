"""Small Unix-socket client shared by the container, shims, and device leases."""
import http.client
import json
import os
import socket
from urllib.parse import urlencode


# Includes the host's first-boot allowance and bounded service-start overhead.
STARTUP_TIMEOUT_SECONDS = 900


class UnixConnection(http.client.HTTPConnection):
    def __init__(self, path=None, timeout=15):
        super().__init__("localhost", timeout=timeout)
        self.path = path or os.environ.get("COC_HOST_SOCKET", "")

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


def request(action, *, timeout=15):
    connection = UnixConnection(timeout=timeout)
    try:
        connection.request("POST" if action != "status" else "GET", "/v1/" + action,
                           body=b"", headers={"Content-Length": "0"})
        response = connection.getresponse()
        payload = json.loads(response.read(65536))
        if response.status != 200:
            raise RuntimeError(payload.get("error", "Host runtime request failed"))
        return payload
    finally:
        connection.close()


def acquire_lease(device):
    connection = UnixConnection(timeout=15)
    try:
        connection.request("GET", "/v1/lease?" + urlencode({"device": device}))
        response = connection.getresponse()
        if response.status != 200:
            message = json.loads(response.read(65536)).get("error", "Device busy")
            raise RuntimeError(message)
        # The host retains flock until this connection closes. No command queue.
        return connection
    except BaseException:
        connection.close()
        raise


def release_lease(connection):
    try:
        if connection.sock is not None:
            connection.sock.settimeout(5)
            connection.sock.sendall(b"R")
            if connection.sock.recv(1) != b"A":
                raise RuntimeError("Host did not acknowledge device release")
    finally:
        connection.close()


def managed_device():
    if not os.environ.get("COC_HOST_SOCKET"):
        return None
    from pathlib import Path
    import ipaddress
    try:
        data = json.loads(Path(os.environ["COC_HOST_SOCKET"]).with_name("device.json").read_text())
        address = str(ipaddress.IPv4Address(data["ip"]))
        return address + ":5555"
    except (OSError, ValueError, KeyError, TypeError):
        return None


def shim_main():
    """Only the exact Waydroid/gdbus commands used by the app are exposed."""
    import sys
    args = sys.argv[1:]
    command = os.path.basename(sys.argv[0])
    if command == "waydroid" and args == ["status"]:
        print(request("status")["raw_status"])
    elif command == "waydroid" and args in (["show-full-ui"], ["session", "start"]):
        request("ensure", timeout=STARTUP_TIMEOUT_SECONDS)
    elif command == "waydroid" and args == ["session", "stop"]:
        request("stop", timeout=45)
    elif command == "gdbus" and args == ["call", "--system", "--dest", "id.waydro.Container",
            "--object-path", "/ContainerManager", "--method", "id.waydro.ContainerManager.Unfreeze"]:
        request("resume")
    else:
        raise SystemExit("Unsupported host command")
