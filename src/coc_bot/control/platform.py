"""Optional CasaOS runtime preparation; the dashboard stays up on failure."""
from contextvars import copy_context
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import zipfile
import os


PACKAGE = "com.supercell.clashofclans"
APK_LIMIT = 2 * 1024 * 1024 * 1024


class Platform:
    def __init__(self):
        self.lock = threading.RLock()
        self.cancel = threading.Event()
        self.thread = None
        self.stage = "stopped"
        self.message = "Preparing Android"
        self.ready = False
        self.error = None
        self.game_update = None
        self.explicit_update = False

    def snapshot(self):
        with self.lock:
            return {"stage": self.stage, "message": self.message, "ready": self.ready,
                    "busy": self.thread is not None and self.thread.is_alive(), "error": self.error,
                    "game_update": self.game_update}

    def update(self, stage, message, *, ready=False, error=None):
        with self.lock:
            self.stage, self.message, self.ready, self.error = stage, message, ready, error

    def stop(self):
        self.cancel.set()

    def start(self, *, update_game=False):
        with self.lock:
            if self.thread is not None and self.thread.is_alive():
                raise ValueError("Runtime startup is already in progress")
            self.cancel = threading.Event()
            self.explicit_update = update_game
            self.update("starting", "Starting Waydroid")
            self.thread = threading.Thread(target=copy_context().run, args=(self.prepare,), daemon=True,
                                           name="casaos-runtime")
            self.thread.start()

    def check_cancel(self):
        if self.cancel.is_set():
            raise RuntimeError("Runtime preparation canceled. Use Retry when ready.")

    def prepare(self):
        try:
            from coc_bot.host_bridge import request
            from coc_bot.adb.client import AdbClient
            from coc_bot.config import load_config
            from coc_bot.runtime.device_lease import DeviceLease
            from coc_bot.adb.capture import ScreenCapture
            request("ensure", timeout=240)
            self.check_cancel()
            config = load_config()
            client = AdbClient(config.adb_device)
            client.stop_check = self.cancel.is_set
            self.update("connecting", "Connecting to Android")
            client.ensure_connected()
            with DeviceLease(config.adb_device):
                self.check_cancel()
                # A restarted Android payload can retain a transport marked
                # "device" whose shell never responds. Refresh only this device
                # while holding ownership; do not restart the shared ADB server.
                from coc_bot.runtime.processes import run_process
                run_process(["adb", "disconnect", config.adb_device], text=True,
                            timeout=15, stop_check=self.cancel.is_set)
                if not client.connect():
                    raise RuntimeError("Android connection could not be refreshed. Use Retry.")
                installed = client.run_shell("pm path " + PACKAGE, check=False).stdout.strip()
                if installed and (self.explicit_update or os.environ.get("COC_AUTO_UPDATE_GAME", "1") == "1"):
                    from coc_bot.control.game_updates import update_game
                    from loguru import logger
                    try:
                        self.game_update = update_game(client, config.data_dir,
                            lambda message: self.update("updating_game", message), self.check_cancel)
                        logger.info(self.game_update)
                    except Exception as exc:
                        self.check_cancel()
                        self.game_update = f"Clash update check could not finish: {exc}"
                        logger.warning(self.game_update)
                        if self.explicit_update:
                            raise
                if not installed:
                    files = sorted((config.data_dir / "game-apks").glob("*.apk"))
                    if not files:
                        self.update("needs_game", "Import the Clash APK archive to finish installation")
                        return
                    self.update("installing_game", "Installing Clash of Clans")
                    validate_apks(files)
                    client.run(["install-multiple", *map(str, files)], timeout=180)
                self.check_cancel()
                self.update("opening_game", "Opening Clash of Clans")
                # Resolve the activity through the existing validated launch code.
                # The container's Waydroid shim ensures the host session, not a new dock window.
                from coc_bot.adb.app import AppController
                capture = ScreenCapture(client)
                controller = AppController(client, config, capture)
                controller.stop_check = self.cancel.is_set
                controller.launch()
                import time
                for _ in range(30):
                    self.check_cancel()
                    if controller.is_running():
                        break
                    self.cancel.wait(1)
                else:
                    raise RuntimeError("Clash did not stay running. Check APK/device compatibility.")
                client.health_check()
                self.check_cancel()
                self.update("ready", "Ready — open Live view to sign in or prepare the game", ready=True)
        except Exception as exc:
            self.update("error", str(exc), error=str(exc))


def validate_apks(files):
    if not files or len(files) > 32 or sum(p.stat().st_size for p in files) > APK_LIMIT:
        raise ValueError("Import between 1 and 32 APK files, up to 2 GB in total")
    for file in files:
        result = subprocess.run(["aapt", "dump", "badging", str(file)], capture_output=True,
                                text=True, timeout=30)
        if result.returncode or ("package: name='" + PACKAGE + "'") not in result.stdout:
            raise ValueError("The archive must contain only Clash of Clans APK files")


def import_apks(archive, destination):
    """Stage, inspect, and replace private game files; never extract ZIP paths."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="game-import-", dir=destination.parent) as temp:
        staging = Path(temp) / "apks"
        staging.mkdir()
        try:
            source = zipfile.ZipFile(archive)
        except zipfile.BadZipFile as exc:
            raise ValueError("Choose a ZIP archive containing Clash APK files") from exc
        with source:
            entries = source.infolist()
            if not 1 <= len(entries) <= 32 or sum(e.file_size for e in entries) > APK_LIMIT:
                raise ValueError("APK archive is empty or too large")
            for index, entry in enumerate(entries):
                if entry.is_dir() or not entry.filename.lower().endswith(".apk") or entry.flag_bits & 1:
                    raise ValueError("ZIP must contain only unencrypted .apk files")
                with source.open(entry) as src, (staging / f"part-{index:02}.apk").open("wb") as dst:
                    shutil.copyfileobj(src, dst)
        validate_apks(list(staging.glob("*.apk")))
        previous = Path(temp) / "previous"
        if destination.exists():
            destination.rename(previous)
        try:
            staging.rename(destination)
        except BaseException:
            if previous.exists():
                previous.rename(destination)
            raise
