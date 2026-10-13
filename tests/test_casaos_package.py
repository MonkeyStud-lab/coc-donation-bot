"""No real Android or privileged host changes: package regression checks."""
from contextlib import contextmanager
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
import tempfile
import threading
from unittest import TestCase, skipIf
from unittest.mock import patch
import zipfile

from coc_bot.config import project_root
from coc_bot.control.platform import import_apks, Platform


def module(name):
    path = project_root() / "packaging/casaos" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class PackageTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_profile_backup_contains_images_settings_and_verified_manifest(self):
        installer = module("install_host")
        (self.root / "data/templates/ui").mkdir(parents=True)
        (self.root / "data/calibrated.yaml").write_text("frame_width: 1853\n")
        (self.root / "data/user_settings.yaml").write_text("farm: {}\n")
        (self.root / "data/templates/ui/chat.png").write_bytes(b"reference-image")
        archive = installer.protect_profile(self.root, self.root / "backups")
        with zipfile.ZipFile(archive) as file:
            names = file.namelist()
            self.assertIn("data/calibrated.yaml", names)
            self.assertIn("data/templates/ui/chat.png", names)
            self.assertEqual(len(json.loads(file.read("manifest.json"))), 3)
        self.assertEqual((self.root / "data/calibrated.yaml").read_text(), "frame_width: 1853\n")

    def test_entrypoint_seed_never_overwrites_calibration_or_settings(self):
        entry = module("entrypoint")
        source, target = self.root / "source", self.root / "target"
        source.mkdir(); target.mkdir()
        (source / "default.yaml").write_text("factory")
        (target / "default.yaml").write_text("user")
        (source / "seed.yaml").write_text("seed")
        entry.seed(source, target)
        entry.seed(source, target)
        self.assertEqual((target / "default.yaml").read_text(), "user")
        self.assertEqual((target / "seed.yaml").read_text(), "seed")

    @skipIf(os.name == "nt" or not hasattr(os, "geteuid") or os.geteuid() != 0,
            "Root compatibility check runs in the disposable build container")
    def test_root_backup_can_open_existing_user_owned_lock(self):
        import hashlib
        installer = module("install_host")
        os.chown(self.root, 1000, 1000)
        (self.root / "data").mkdir()
        (self.root / "data/calibrated.yaml").write_text("frame_width: 1853\n")
        identity = "calibration:" + str(self.root.resolve())
        lock = Path(tempfile.gettempdir()) / ("coc-bot-device-" + hashlib.sha256(identity.encode()).hexdigest() + ".lock")
        lock.write_bytes(b"0")
        os.chown(lock, 1000, 1000)
        self.addCleanup(lock.unlink)
        self.assertTrue(installer.protect_profile(self.root, self.root / "backups").exists())

    def archive(self, names):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as file:
            for name in names:
                file.writestr(name, b"fake-apk")
        data.seek(0)
        return data

    def test_apk_archive_is_flattened_and_validated_before_replacing_files(self):
        dest = self.root / "game-apks"
        dest.mkdir()
        (dest / "old.apk").write_bytes(b"old")
        with patch("coc_bot.control.platform.validate_apks", side_effect=ValueError("wrong package")):
            with self.assertRaises(ValueError):
                import_apks(self.archive(["base.apk"]), dest)
        self.assertEqual((dest / "old.apk").read_bytes(), b"old")
        with patch("coc_bot.control.platform.validate_apks") as validate:
            import_apks(self.archive(["../../base.apk", "nested/split.apk"]), dest)
            self.assertEqual(len(validate.call_args[0][0]), 2)
        self.assertEqual(sorted(p.name for p in dest.iterdir()), ["part-00.apk", "part-01.apk"])
        self.assertFalse((self.root / "base.apk").exists())

    def test_non_apks_and_too_many_entries_are_rejected(self):
        for names in (["password.txt"], [str(i) + ".apk" for i in range(33)]):
            with self.assertRaises(ValueError):
                import_apks(self.archive(names), self.root / "game-apks")

    def test_unmanaged_runtime_keeps_existing_settings_device(self):
        from coc_bot.host_bridge import managed_device
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(managed_device())
        path = self.root / "device.json"
        path.write_text(json.dumps({"ip": "192.168.240.112"}))
        with patch.dict(os.environ, {"COC_HOST_SOCKET": str(self.root / "host.sock")}):
            self.assertEqual(managed_device(), "192.168.240.112:5555")
            path.write_text(json.dumps({"ip": "bad; command"}))
            self.assertIsNone(managed_device())

    def test_platform_failure_does_not_start_automation(self):
        runtime = Platform()
        with patch("coc_bot.host_bridge.request", side_effect=RuntimeError("No host helper")):
            runtime.start()
            runtime.thread.join(3)
        self.assertFalse(runtime.snapshot()["ready"])
        self.assertEqual(runtime.snapshot()["error"], "No host helper")

    def test_package_validator_rejects_different_game(self):
        from coc_bot.control.platform import validate_apks
        file = self.root / "base.apk"
        file.write_bytes(b"apk")
        with patch("subprocess.run", return_value=SimpleNamespace(returncode=0,
                          stdout="package: name='com.other.game'")):
            with self.assertRaises(ValueError):
                validate_apks([file])


@skipIf(os.name == "nt", "Host helper requires Linux flock and Unix sockets")
class HostBridgeTests(TestCase):
    def setUp(self):
        import pwd
        from coc_bot.host_bridge import acquire_lease, release_lease
        self.host = module("host_agent")
        self.temp = tempfile.TemporaryDirectory(prefix="coc-host-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "host.sock"
        config = {"user": pwd.getpwuid(os.getuid()).pw_name, "display": "wayland-0", "socket": str(self.path)}
        self.runtime = self.host.Runtime(config)
        self.runtime.command = lambda *args, **kwargs: (
            "Session: RUNNING\nContainer: RUNNING\nIP address: 192.0.2.77\n")
        self.server = self.host.Server(str(self.path), self.host.Handler)
        self.server.runtime = self.runtime
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 2)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.env = patch.dict(os.environ, {"COC_HOST_SOCKET": str(self.path)})
        self.env.start(); self.addCleanup(self.env.stop)

    def test_native_and_container_leases_exclude_each_other_and_release_synchronously(self):
        from coc_bot.host_bridge import acquire_lease, release_lease
        from coc_bot.runtime.device_lease import DeviceLease, DeviceBusy
        device = "192.0.2.77:5555"
        with patch.dict(os.environ, {"COC_HOST_SOCKET": ""}):
            native = DeviceLease(device)
            native.__enter__()
        try:
            with self.assertRaises(RuntimeError):
                acquire_lease(device)
        finally:
            native.__exit__()
        connection = acquire_lease(device)
        try:
            with patch.dict(os.environ, {"COC_HOST_SOCKET": ""}):
                with self.assertRaises(DeviceBusy):
                    DeviceLease(device).__enter__()
        finally:
            release_lease(connection)
        # No sleeps: release acknowledgement must make immediate reacquisition safe.
        for _ in range(10):
            with DeviceLease(device):
                pass

    def test_only_allowlisted_actions_and_matching_device_are_accepted(self):
        from coc_bot.host_bridge import request, acquire_lease
        self.assertEqual(request("status")["ip"], "192.0.2.77")
        with self.assertRaises(RuntimeError):
            request("shell")
        with self.assertRaises(RuntimeError):
            acquire_lease("127.0.0.1:5555")

    def test_adopted_runtime_can_start_a_closed_session_without_host_commands_from_client(self):
        state = {"running": False}
        commands = []
        self.runtime.config["manage_services"] = False
        def command(args, **kwargs):
            commands.append(args)
            if args[:2] == ["waydroid", "status"]:
                value = "RUNNING" if state["running"] else "STOPPED"
                return "Session: " + value + "\nContainer: " + value + "\nIP address: 192.0.2.77\n"
            if args[0] == "systemctl":
                return "not-found\n"
            if args[0] == "systemd-run" and "--unit=coc-waydroid-adopted-session" in args:
                state["running"] = True
            return ""
        self.runtime.command = command
        with patch.object(Path, "is_socket", return_value=True):
            self.assertEqual(self.runtime.ensure()["session"], "RUNNING")
        self.assertTrue(any("--unit=coc-waydroid-adopted-session" in c for c in commands))
        self.assertTrue(any("--unit=coc-waydroid-adopted-ui" in c for c in commands))

    def test_stale_running_metadata_with_unresponsive_android_is_restartable(self):
        def command(args, **kwargs):
            if args[0] == "adb":
                raise subprocess.TimeoutExpired(args, 3)
            return "Session: RUNNING\nContainer: STOPPED\nIP address: 192.0.2.77\n"
        self.runtime.command = command
        result = self.runtime.status()
        self.assertEqual(result["session"], "STOPPED")
        self.assertEqual(result["container"], "STOPPED")

    def test_host_snapshot_waits_for_container_calibration_edit_across_path_alias(self):
        from coc_bot.runtime.device_lease import DeviceLease
        installer = module("install_host")
        root = Path(self.temp.name) / "profile"
        (root / "data").mkdir(parents=True)
        (root / "data/calibrated.yaml").write_text("frame_width: 1853\n")
        alias = Path(self.temp.name) / "container-profile"
        alias.symlink_to(root, target_is_directory=True)
        entered, finished = threading.Event(), threading.Event()
        failures = []
        def backup():
            entered.set()
            try:
                installer.protect_profile(root, Path(self.temp.name) / "backups")
            except Exception as exc:
                failures.append(exc)
            finally:
                finished.set()
        with DeviceLease("calibration:" + str(alias)):
            thread = threading.Thread(target=backup)
            thread.start()
            self.assertTrue(entered.wait(2))
            self.assertFalse(finished.wait(.1))
        thread.join(3)
        self.assertTrue(finished.is_set())
        self.assertEqual(failures, [])
