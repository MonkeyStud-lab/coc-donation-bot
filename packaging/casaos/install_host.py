#!/usr/bin/env python3
"""Idempotent host preparation. Never reset Android or overwrite calibration.

Run once with administrator privileges, or by the CasaOS setup container. Dry
run is read-only and does not require root. Existing desktop sessions may be
adopted explicitly; new installations use a dedicated headless Wayland session.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile


def run(*args, timeout=600):
    print("Preparing: " + " ".join(args[:3]), flush=True)
    subprocess.run(args, check=True, timeout=timeout,
                   env=os.environ | {"DEBIAN_FRONTEND": "noninteractive"})


def protect_profile(root, destination):
    # Match the bot's cross-process calibration lock while taking the snapshot.
    if os.name != "posix":
        return _protect_profile(root, destination)
    import fcntl
    identity = "calibration:" + str(Path(root).resolve())
    lock_path = Path(tempfile.gettempdir()) / ("coc-bot-device-" + hashlib.sha256(identity.encode()).hexdigest() + ".lock")
    try:
        lock = lock_path.open("r+b")  # No O_CREAT: Linux protected_regular allows this for root.
    except FileNotFoundError:
        try:
            lock = lock_path.open("x+b")
        except FileExistsError:
            lock = lock_path.open("r+b")
        else:
            if os.geteuid() == 0:
                owner = Path(root).stat() if Path(root).exists() else None
                os.fchown(lock.fileno(), owner.st_uid if owner and owner.st_uid else 1000,
                          owner.st_gid if owner and owner.st_gid else 1000)
    with lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = Path(root) / "data"
        if not data.is_dir():
            return _protect_profile(root, destination)
        shared = data / ".calibration.lock"
        try:
            persisted = shared.open("r+b")
        except FileNotFoundError:
            try:
                persisted = shared.open("x+b")
            except FileExistsError:
                persisted = shared.open("r+b")
            else:
                if os.geteuid() == 0:
                    owner = Path(root).stat()
                    os.fchown(persisted.fileno(), owner.st_uid or 1000, owner.st_gid or 1000)
        with persisted:
            fcntl.flock(persisted, fcntl.LOCK_EX)
            return _protect_profile(root, destination)


def _protect_profile(root, destination):
    """A portable, checksum-verified snapshot before any installation changes."""
    root = Path(root).resolve()
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    archive = destination / ("before-install-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".zip")
    files = [root / p for p in ("data/calibrated.yaml", "data/user_settings.yaml",
             "data/runtime_state.json", "config/default.yaml") if (root / p).is_file()]
    files += [p for p in (root / "data/templates").rglob("*") if p.is_file()]
    hashes = {}
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
        for file in files:
            if file.is_symlink() or not file.resolve().is_relative_to(root):
                raise RuntimeError("Backup source contains an external link")
            content = file.read_bytes()
            key = str(file.relative_to(root))
            hashes[key] = hashlib.sha256(content).hexdigest()
            output.writestr(key, content)
        output.writestr("manifest.json", json.dumps(hashes, indent=2))
    with zipfile.ZipFile(archive) as check:
        for name, digest in hashes.items():
            if hashlib.sha256(check.read(name)).hexdigest() != digest:
                raise RuntimeError("Calibration backup verification failed")
    archive.chmod(0o600)
    print("Verified backup: " + str(archive), flush=True)
    return archive


def inspect():
    release = dict(line.rstrip().split("=", 1) for line in Path("/etc/os-release").read_text().splitlines()
                   if "=" in line)
    distro = release.get("ID", "").strip('"')
    return {"distribution": distro, "version": release.get("VERSION_ID", "").strip('"'),
            "architecture": platform.machine(), "kernel": platform.release(),
            "render_nodes": [str(p) for p in Path("/dev/dri").glob("renderD*")],
            "binder": Path("/sys/module/binder_linux").exists(),
            "waydroid": shutil.which("waydroid"), "systemd": Path("/run/systemd/system").exists()}


def copy_profile(source, destination):
    """Import into empty private storage only. Never merge over live calibration."""
    source, destination = Path(source), Path(destination)
    for name in ("config", "data/calibrated.yaml", "data/templates", "data/user_settings.yaml",
                 "data/runtime_state.json", "data/game", "data/icons", "data/models", "data/live"):
        src, dst = source / name, destination / name
        if not src.exists():
            continue
        if dst.exists():
            raise RuntimeError("Import destination already contains " + name + "; use Library restore instead")
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            if any(p.is_symlink() for p in src.rglob("*")):
                raise RuntimeError("Import source contains links; use a verified calibration archive")
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)


def install(args):
    import pwd
    report = inspect()
    print(json.dumps(report, indent=2), flush=True)
    if report["distribution"] not in ("ubuntu", "debian") or report["architecture"] != "x86_64":
        raise RuntimeError("Initial package supports x86-64 Ubuntu/Debian hosts only")
    if not report["systemd"] or not report["render_nodes"]:
        raise RuntimeError("A systemd host with a hardware graphics render device is required")
    if args.dry_run:
        print("Dry run: host would be prepared, existing Android/calibration would be retained.")
        return
    if os.geteuid() != 0:
        raise RuntimeError("Host installation needs administrator privileges")
    profile = Path(args.profile).resolve()
    backups = Path(args.backups).resolve()
    # These run before apt, Waydroid initialization, service writes or imports.
    protect_profile(profile, backups)
    if args.import_from:
        protect_profile(args.import_from, backups)
        if not (profile / "data/calibrated.yaml").exists():
            copy_profile(args.import_from, profile)
    existing = Path("/etc/coc-casaos/host.json")
    if existing.exists() and not args.adopt_user:
        previous = json.loads(existing.read_text())
        if not previous.get("manage_services", True):
            args.adopt_user, args.display = previous["user"], previous["display"]
    run("apt-get", "update")
    run("apt-get", "install", "-y", "python3", "curl", "ca-certificates", "weston",
        "dbus-user-session", "adb", "mesa-utils", "libgl1-mesa-dri")
    if not report["binder"]:
        # Only install modules for the currently running kernel. Never replace the kernel.
        if report["distribution"] == "ubuntu":
            run("apt-get", "install", "-y", "linux-modules-extra-" + platform.release())
        run("modprobe", "binder_linux")
    if shutil.which("waydroid") is None:
        # Current Waydroid repository metadata contains this project's signing key.
        run("curl", "--fail", "--location", "--proto", "=https", "--tlsv1.2", "--output",
            "/usr/share/keyrings/waydroid.gpg", "https://repo.waydro.id/waydroid.gpg")
        release = Path("/etc/os-release").read_text()
        match = re.search(r'^VERSION_CODENAME=["\']?([a-z]+)', release, re.M)
        if not match:
            raise RuntimeError("Could not determine the distribution codename")
        Path("/etc/apt/sources.list.d/waydroid.list").write_text(
            "deb [signed-by=/usr/share/keyrings/waydroid.gpg] https://repo.waydro.id/ " + match[1] + " main\n")
        run("apt-get", "update")
        run("apt-get", "install", "-y", "waydroid")
    new_android = not Path("/var/lib/waydroid/waydroid.cfg").exists()
    if new_android:
        run("waydroid", "init", "-s", "VANILLA", timeout=3600)
    if args.adopt_user:
        user = pwd.getpwnam(args.adopt_user)
        display = args.display
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", display):
            raise RuntimeError("Invalid Wayland display name")
        if not (Path("/run/user") / str(user.pw_uid) / display).exists():
            raise RuntimeError("Existing Wayland socket is not available")
    else:
        try:
            user = pwd.getpwnam("coc-game")
        except KeyError:
            run("useradd", "--create-home", "--shell", "/usr/sbin/nologin", "coc-game")
            user = pwd.getpwnam("coc-game")
        display = "wayland-coc"
    for group in ("render", "video"):
        run("usermod", "-a", "-G", group, user.pw_name)
    run("loginctl", "enable-linger", user.pw_name)
    uid = user.pw_uid
    environment = f"Environment=XDG_RUNTIME_DIR=/run/user/{uid}\nEnvironment=WAYLAND_DISPLAY={display}\nEnvironment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus\n"
    directory = Path("/etc/coc-casaos")
    directory.mkdir(parents=True, exist_ok=True)
    installation = Path("/opt/coc-casaos-host")
    installation.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(__file__).with_name("host_agent.py"), installation / "host_agent.py")
    config = {"user": user.pw_name, "display": display, "socket": "/run/coc-waydroid/host.sock",
              "manage_services": not bool(args.adopt_user), "app_uid": 1000, "app_gid": 1000}
    config["needs_ui"] = not bool(args.adopt_user)
    config["prepare_adb"] = new_android or (
        existing.exists() and json.loads(existing.read_text()).get("prepare_adb", False))
    (directory / "host.json").write_text(json.dumps(config, indent=2))
    units = Path("/etc/systemd/system")
    if not args.adopt_user:
        help_result = subprocess.run(["weston", "--help"], text=True, capture_output=True, check=True)
        render_option = "--renderer=gl" if "--renderer" in help_result.stdout else "--use-gl"
        (units / "coc-waydroid-display.service").write_text(
            "[Unit]\nDescription=CoC headless Wayland display\nAfter=user@" + str(uid) + ".service\nRequires=user@" + str(uid) + ".service\n"
            "[Service]\nUser=" + user.pw_name + "\n" + environment +
            "ExecStart=/usr/bin/weston --backend=headless-backend.so " + render_option + " --socket=wayland-coc --idle-time=0 --width=1853 --height=1048\n"
            "Restart=on-failure\nRestartSec=5\n")
        (units / "coc-waydroid-session.service").write_text(
            "[Unit]\nDescription=CoC Waydroid user session\nAfter=coc-waydroid-display.service waydroid-container.service\n"
            "Requires=coc-waydroid-display.service waydroid-container.service\n"
            "[Service]\nUser=" + user.pw_name + "\n" + environment +
            "ExecStartPre=/usr/bin/python3 -c \"import pathlib,time; p=pathlib.Path('/run/user/" + str(uid) + "/wayland-coc'); [time.sleep(.5) for _ in range(60) if not p.exists()]; assert p.exists()\"\n"
            "ExecStart=/usr/bin/waydroid session start\nExecStop=/usr/bin/waydroid session stop\nRestart=on-failure\nRestartSec=5\n")
        (units / "coc-waydroid-ui.service").write_text(
            "[Unit]\nDescription=CoC Android surface on headless display\nAfter=coc-waydroid-session.service\nRequires=coc-waydroid-session.service\n"
            "[Service]\nType=oneshot\nUser=" + user.pw_name + "\n" + environment +
            "ExecStart=/usr/bin/waydroid show-full-ui\nRemainAfterExit=yes\nTimeoutStartSec=90\n")
    (units / "coc-waydroid-host.service").write_text(
        "[Unit]\nDescription=CoC CasaOS host runtime helper\nAfter=network.target\n"
        "[Service]\nExecStart=/usr/bin/python3 /opt/coc-casaos-host/host_agent.py\n"
        "RuntimeDirectory=coc-waydroid\nRuntimeDirectoryMode=0755\nRuntimeDirectoryPreserve=restart\nRestart=on-failure\nRestartSec=5\n"
        "UMask=0077\n[Install]\nWantedBy=multi-user.target\n")
    profile.mkdir(parents=True, exist_ok=True)
    profile.chmod(0o700)
    for path in [profile, *profile.rglob("*")]:
        if not path.is_symlink():
            os.chown(path, 1000, 1000)
    run("systemctl", "daemon-reload")
    run("systemctl", "enable", "--now", "waydroid-container.service", "coc-waydroid-host.service")
    print("Host prepared. Install/start the CasaOS app, then import the Clash APK archive.", flush=True)


def refresh_helper(args):
    """Refresh only the helper after proving the game controller is stopped."""
    import fcntl
    import ipaddress
    if os.geteuid() != 0:
        raise RuntimeError("Helper refresh needs administrator privileges")
    config = json.loads(Path("/etc/coc-casaos/host.json").read_text())
    metadata = Path(config["socket"]).with_name("device.json")
    serial = str(ipaddress.IPv4Address(json.loads(metadata.read_text())["ip"])) + ":5555"
    digest = hashlib.sha256(serial.encode()).hexdigest()
    lock = Path(tempfile.gettempdir()) / ("coc-bot-device-" + digest + ".lock")
    with lock.open("r+b") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Stop automation and release Live view control before refreshing the helper")
        protect_profile(args.profile, args.backups)
        target = Path("/opt/coc-casaos-host/host_agent.py")
        shutil.copy2(Path(__file__).with_name("host_agent.py"), target)
        unit = Path("/etc/systemd/system/coc-waydroid-host.service")
        content = unit.read_text()
        if "RuntimeDirectoryPreserve=" not in content:
            unit.write_text(content.replace("RuntimeDirectoryMode=0755", "RuntimeDirectoryMode=0755\nRuntimeDirectoryPreserve=restart"))
        run("systemctl", "daemon-reload")
        run("systemctl", "restart", "coc-waydroid-host.service")
    print("Helper refreshed; Android and calibration were not reset.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--refresh-helper", action="store_true", help="Refresh only the installed helper after stopping automation")
    parser.add_argument("--profile", default="/DATA/AppData/coc-bot/profile")
    parser.add_argument("--backups", default="/DATA/AppData/coc-bot/backups")
    parser.add_argument("--adopt-user", help="Keep an existing desktop Waydroid session instead of creating headless services")
    parser.add_argument("--display", default="wayland-0")
    parser.add_argument("--import-from", help="Copy a previous bot profile into an empty package profile")
    args = parser.parse_args()
    try:
        if args.refresh_helper:
            refresh_helper(args)
        else:
            install(args)
    except Exception as exc:
        print("Installation stopped: " + str(exc), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
