"""Verified in-place updates of an already trusted Clash installation.

Caller must own DeviceLease and exclude bot/manual control for the entire call.
No source is trusted to bootstrap the signing identity of a fresh installation.
"""
from pathlib import Path
from contextlib import contextmanager
from email import message_from_string
import re
import shutil
import subprocess
import tempfile
from urllib.parse import urlsplit, urljoin
from urllib.request import Request
from coc_bot.runtime.processes import run_process

PACKAGE = "com.supercell.clashofclans"
SOURCE = "https://d.apkpure.net/b/APK/" + PACKAGE + "?version=latest"
MAX_BYTES = 2 * 1024**3
HOSTS = {"d.apkpure.net", "data.winudf.com"}


def allowed_url(url):
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.hostname not in HOSTS or
            parts.port not in (None, 443) or parts.username or parts.password):
        raise ValueError("APK source redirected to an unsupported address")


class SourceResponse:
    def __init__(self, url, headers):
        self.url, self.headers = url, headers

    def geturl(self):
        return self.url


class CurlSource:
    # The provider accepts curl's HTTPS client; Python urllib was rejected in
    # the live container. Resolve every redirect ourselves, never use curl -L.
    @contextmanager
    def open(self, request, timeout=30):
        url = request.full_url
        for _ in range(6):
            allowed_url(url)
            result = run_process(["curl", "--silent", "--show-error", "--head", "--proto", "=https",
                "--max-time", str(timeout), url], text=True, timeout=timeout+5)
            if result.returncode:
                raise RuntimeError("APK source could not be reached")
            block = re.split(r"\r?\n\r?\n", result.stdout.strip())[-1]
            first, _, rest = block.partition("\n")
            status = re.search(r"HTTP/\S+ (\d+)", first)
            headers = message_from_string(rest)
            if status and int(status[1]) in (301, 302, 303, 307, 308) and headers.get("Location"):
                url = urljoin(url, headers["Location"])
                continue
            if not status or int(status[1]) != 200:
                raise RuntimeError("APK source refused the update check")
            yield SourceResponse(url, headers)
            return
        raise RuntimeError("Too many APK source redirects")


def build_opener(*args):
    return CurlSource()


def signer(file):
    result = subprocess.run(["apksigner", "verify", "--print-certs", str(file)],
                            capture_output=True, text=True, timeout=90)
    digests = frozenset(re.findall(r"Signer #\d+ certificate SHA-256 digest: ([0-9a-fA-F]{64})",
                                  result.stdout.lower(), re.IGNORECASE))
    if result.returncode or not digests:
        raise ValueError("APK signature verification failed")
    return digests


def inspect_apk(file):
    result = subprocess.run(["aapt", "dump", "badging", str(file)],
                            capture_output=True, text=True, timeout=30)
    match = re.search(r"^package: name='([^']+)' versionCode='(\d+)' versionName='([^']+)'(.*)$",
                      result.stdout, re.MULTILINE)
    if result.returncode or not match or match[1] != PACKAGE or "split='" in match[4]:
        raise ValueError("Download is not a standalone Clash APK; use APK archive import")
    return int(match[2]), match[3]


def download(opener, destination, report, cancel):
    with opener.open(Request(SOURCE, method="HEAD"), timeout=30) as response:
        allowed_url(response.geturl())
        expected = int(response.headers.get("Content-Length", "0"))
        if expected < 0 or expected > MAX_BYTES:
            raise ValueError("APK download exceeds 2 GB")
        last_report = -1
        def progress():
            nonlocal last_report
            cancel()
            total = destination.stat().st_size if destination.exists() else 0
            if total > MAX_BYTES:
                raise ValueError("APK download exceeds 2 GB")
            percent = int(total * 100 / expected) if expected else total // 1024**2
            if percent != last_report:
                report(f"Downloading Clash update — {percent}%" if expected else
                       f"Downloading Clash update — {percent} MB")
                last_report = percent
            return False
        result = run_process(["curl", "--silent", "--show-error", "--fail", "--proto", "=https",
            "--max-time", "600", "--max-filesize", str(MAX_BYTES), "--output", str(destination),
            "--write-out", "%{http_code}", response.geturl()], text=True, timeout=610, stop_check=progress)
        if result.returncode or result.stdout.strip() != "200":
            raise RuntimeError("APK download failed; existing Clash was not changed")
        total = destination.stat().st_size
        if total == 0 or (expected and total != expected):
            raise ValueError("APK download was incomplete")


def update_game(client, data_dir, report, cancel):
    """Check latest, pin to installed certificate, back up, install without clearing data."""
    paths = client.run_shell("pm path " + PACKAGE).stdout.splitlines()
    installed_paths = [p.removeprefix("package:").strip() for p in paths if p.startswith("package:")]
    if not installed_paths or any(not re.fullmatch(r"/data/app/[A-Za-z0-9_./=+~-]+\.apk", p)
                                  for p in installed_paths):
        raise ValueError("Import a trusted Clash installation before using automatic updates")
    state = client.run_shell("dumpsys package " + PACKAGE).stdout
    version = re.search(r"\bversionCode=(\d+)", state)
    name = re.search(r"\bversionName=([^\s]+)", state)
    if not version or not name:
        raise ValueError("Cannot determine installed Clash version")
    opener = build_opener()
    report("Checking Clash updates on APKPure")
    with opener.open(Request(SOURCE, method="HEAD"), timeout=30) as response:
        allowed_url(response.geturl())
        advertised = re.search(r"Clash(?:\+| |%20)of(?:\+| |%20)Clans_([0-9.]+)_",
                               response.headers.get("Content-Disposition", ""))
        if advertised and advertised[1] == name[1]:
            return f"Clash {name[1]} is up to date"
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(data_dir).free < 3 * MAX_BYTES:
        raise ValueError("At least 6 GB of free space is needed to download and back up Clash")
    with tempfile.TemporaryDirectory(prefix="clash-update-", dir=data_dir) as temp:
        folder = Path(temp)
        candidate = folder / "latest.apk"
        download(opener, candidate, report, cancel)
        code, new_name = inspect_apk(candidate)
        if code <= int(version[1]):
            return f"Clash {name[1]} is up to date (no downgrade installed)"
        cancel()
        report("Verifying Clash update signature")
        base = next((p for p in installed_paths if p.endswith("/base.apk")), None)
        if base is None:
            raise ValueError("Installed Clash base APK was not found")
        trusted = folder / "installed.apk"
        client.run(["pull", base, str(trusted)], timeout=180)
        if signer(candidate) != signer(trusted):
            raise ValueError("Update signer does not match installed Clash; update rejected")
        cancel()
        from coc_bot.control.backups import create_backup
        if (data_dir / "calibrated.yaml").exists():
            create_backup(data_dir.parent, stamp_prefix="before-game-update")
        backup = data_dir / "game-update-backup"
        with tempfile.TemporaryDirectory(prefix="old-apks-", dir=data_dir) as saved:
            for index, path in enumerate(installed_paths):
                client.run(["pull", path, str(Path(saved) / f"part-{index:02}.apk")], timeout=180)
            # Keep one complete previous installation, never uninstall or clear app data.
            if backup.exists():
                shutil.rmtree(backup)
            shutil.copytree(saved, backup)
        cancel()
        report(f"Installing Clash {new_name}")
        install_error = None
        try:
            # Waydroid can commit a streamed installation without returning its
            # final ADB response. Use push+install and verify committed state.
            result = client.run(["install", "--no-streaming", "-r", str(candidate)], timeout=300)
            if "Success" not in result.stdout:
                install_error = RuntimeError("Android did not confirm the Clash update")
        except Exception as exc:
            cancel()
            install_error = exc
        installed = client.run_shell("dumpsys package " + PACKAGE).stdout
        actual = re.search(r"\bversionCode=(\d+)", installed)
        if actual is None or int(actual[1]) != code:
            if install_error is not None:
                raise install_error
            raise RuntimeError("Installed Clash version could not be confirmed")
        return f"Updated Clash to {new_name} — check calibration after game UI changes"
