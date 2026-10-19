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

    def test_fresh_profile_seeds_icons_but_preserves_custom_artwork_and_calibration(self):
        entry = module("entrypoint")
        app, profile = self.root / "app", self.root / "profile"
        for name in ("config", "data/game", "data/live"):
            (app / name).mkdir(parents=True)
        (app / "data/icons/troops").mkdir(parents=True)
        (app / "data/icons/troops/electro_dragon.webp").write_bytes(b"public-artwork")
        (app / "data/calibrated.yaml").write_text("private source must not seed")
        entry.seed_profile(app, profile)
        target = profile / "data/icons/troops/electro_dragon.webp"
        self.assertEqual(target.read_bytes(), b"public-artwork")
        self.assertFalse((profile / "data/calibrated.yaml").exists())
        target.write_bytes(b"user-artwork")
        (profile / "data/calibrated.yaml").write_text("user calibration")
        entry.seed_profile(app, profile)
        self.assertEqual(target.read_bytes(), b"user-artwork")
        self.assertEqual((profile / "data/calibrated.yaml").read_text(), "user calibration")

    def test_host_backup_and_empty_import_preserve_planner_and_upgrade_intents(self):
        installer = module("install_host")
        source = self.root / "source"
        evidence = {"data/attack-planner/routine.json": b'{"plan":{}}',
                    "data/attack-planner/units/hero.png": b"reviewed portrait",
                    "data/attack-planner/attack-pending.json": b'{"phase":"deploying"}',
                    "data/upgrades/state.json": b'{"pending":true}'}
        for relative, content in evidence.items():
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        backup = installer.protect_profile(source, self.root / "backups")
        with zipfile.ZipFile(backup) as archive:
            for relative, content in evidence.items():
                self.assertEqual(archive.read(relative), content)
        destination = self.root / "destination"
        installer.copy_profile(source, destination)
        for relative, content in evidence.items():
            self.assertEqual((destination / relative).read_bytes(), content)

    def test_failed_staged_import_does_not_publish_partial_profile(self):
        installer = module("install_host")
        source, destination = self.root / "source", self.root / "destination"
        (source / "data").mkdir(parents=True)
        (source / "data/calibrated.yaml").write_text("calibration")
        (source / "data/user_settings.yaml").write_text("settings")
        original = installer.shutil.copy2
        def copy(src, dst):
            if Path(src).name == "user_settings.yaml":
                raise OSError("disk full")
            return original(src, dst)
        with patch.object(installer.shutil, "copy2", side_effect=copy):
            with self.assertRaises(OSError):
                installer.copy_profile(source, destination)
        self.assertFalse(destination.exists())
        self.assertFalse(list(self.root.glob(".coc-import-*")))

    def test_nonempty_import_destination_is_preserved_before_copying(self):
        installer = module("install_host")
        source, destination = self.root / "source", self.root / "destination"
        (source / "config").mkdir(parents=True)
        (source / "config/default.yaml").write_text("defaults")
        destination.mkdir()
        (destination / "unrelated.txt").write_text("preserve")
        with self.assertRaisesRegex(RuntimeError, "not empty"):
            installer.copy_profile(source, destination)
        self.assertEqual((destination / "unrelated.txt").read_text(), "preserve")
        self.assertFalse((destination / "config").exists())

    def test_missing_or_overlapping_import_sources_are_rejected(self):
        installer = module("install_host")
        with self.assertRaises(RuntimeError):
            installer.copy_profile(self.root / "missing", self.root / "destination")
        source = self.root / "source"
        source.mkdir()
        with self.assertRaisesRegex(RuntimeError, "overlap"):
            installer.copy_profile(source, source / "nested")

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

    def test_platform_reconnects_only_the_owned_transport_before_testing_connection(self):
        events, commands = [], []
        @contextmanager
        def lease(device):
            events.append("lease")
            try:
                yield
            finally:
                events.append("release")
        def disconnect(args, **kwargs):
            commands.append(args)
            events.append("disconnect")
        def connect():
            events.append("connect")
            raise RuntimeError("connection boundary reached")
        client = SimpleNamespace(ensure_connected=connect)
        runtime = Platform()
        with patch("coc_bot.host_bridge.request"), \
                patch("coc_bot.config.load_config", return_value=SimpleNamespace(adb_device="192.0.2.81:5555")), \
                patch("coc_bot.adb.client.AdbClient", return_value=client), \
                patch("coc_bot.runtime.device_lease.DeviceLease", side_effect=lease), \
                patch("coc_bot.runtime.processes.run_process", side_effect=disconnect):
            runtime.prepare()
        self.assertEqual(events, ["lease", "disconnect", "connect", "release"])
        self.assertEqual(commands, [["adb", "disconnect", "192.0.2.81:5555"]])
        self.assertEqual(runtime.snapshot()["error"], "connection boundary reached")

    def test_busy_device_blocks_startup_transport_refresh(self):
        client = SimpleNamespace(ensure_connected=lambda: self.fail("Cannot connect before ownership"))
        runtime = Platform()
        with patch("coc_bot.host_bridge.request"), \
                patch("coc_bot.config.load_config", return_value=SimpleNamespace(adb_device="192.0.2.81:5555")), \
                patch("coc_bot.adb.client.AdbClient", return_value=client), \
                patch("coc_bot.runtime.device_lease.DeviceLease", side_effect=RuntimeError("Another controller owns Android")), \
                patch("coc_bot.runtime.processes.run_process") as command:
            runtime.prepare()
            command.assert_not_called()
        self.assertEqual(runtime.snapshot()["error"], "Another controller owns Android")

    def test_connected_adb_waits_for_the_android_package_service(self):
        results = iter([SimpleNamespace(returncode=1, stdout=""),
                        SimpleNamespace(returncode=0, stdout="package:/system/framework/framework-res.apk\n")])
        commands = []
        def shell(command, **kwargs):
            commands.append(command)
            return next(results)
        runtime = Platform()
        with patch.object(runtime.cancel, "wait", return_value=False):
            runtime.wait_for_android(SimpleNamespace(run_shell=shell))
        self.assertEqual(commands, ["pm path android", "pm path android"])

    def test_android_service_timeout_and_cancel_do_not_proceed_as_a_missing_game(self):
        from coc_bot.control import platform as managed
        runtime = Platform()
        client = SimpleNamespace(run_shell=lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout=""))
        with patch.object(managed, "time", SimpleNamespace(monotonic=iter([0, 121]).__next__)):
            with self.assertRaisesRegex(RuntimeError, "package service unavailable"):
                runtime.wait_for_android(client)
        runtime.cancel.set()
        with self.assertRaisesRegex(RuntimeError, "canceled"):
            runtime.wait_for_android(client)

    def test_package_validator_rejects_different_game(self):
        from coc_bot.control.platform import validate_apks
        file = self.root / "base.apk"
        file.write_bytes(b"apk")
        with patch("subprocess.run", return_value=SimpleNamespace(returncode=0,
                          stdout="package: name='com.other.game'")):
            with self.assertRaises(ValueError):
                validate_apks([file])

    @skipIf(os.name == "nt", "Host maintenance uses Linux device leases")
    def test_helper_refresh_without_metadata_still_excludes_an_active_controller(self):
        import fcntl
        import pwd
        installer = module("install_host")
        config = {"socket": str(self.root / "host.sock"),
                  "user": pwd.getpwuid(os.getuid()).pw_name}
        with patch.object(installer, "runtime_status", return_value={"ip": "192.0.2.78"}), \
                patch.object(installer.tempfile, "gettempdir", return_value=str(self.root)):
            with installer.helper_maintenance_lease(config):
                path = next(self.root.glob("coc-bot-device-*.lock"))
                with path.open("r+b") as other:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with path.open("r+b") as other:
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaisesRegex(RuntimeError, "Stop automation"):
                    with installer.helper_maintenance_lease(config):
                        self.fail("A busy device must block helper replacement")

    @skipIf(os.name == "nt", "Host maintenance uses Linux device leases")
    def test_helper_refresh_without_a_valid_device_does_not_bypass_ownership(self):
        installer = module("install_host")
        with patch.object(installer, "runtime_status", return_value={"ip": None}):
            with self.assertRaisesRegex(RuntimeError, "valid IP"):
                with installer.helper_maintenance_lease({"socket": str(self.root / "host.sock")}):
                    self.fail("Unknown device must not bypass the ownership check")


@skipIf(os.name == "nt", "Managed ADB identity checks use Linux ownership")
class ManagedAdbIdentityTests(TestCase):
    def setUp(self):
        import base64
        import pwd
        import struct
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.profile = self.root / "profile"
        self.directory = self.profile / ".android"
        self.directory.mkdir(parents=True)
        self.token = base64.b64encode(struct.pack("<II", 64, 1) + b"\x01" * 512 + struct.pack("<I", 65537)).decode()
        self.key = self.directory / "adbkey.pub"
        self.key.write_text(self.token + " app-key\n")
        self.host = module("host_agent")
        self.runtime = self.host.Runtime({"user": pwd.getpwuid(os.getuid()).pw_name,
            "profile": str(self.profile), "prepare_adb": True, "app_uid": os.getuid()})

    def test_key_reader_accepts_only_bounded_app_owned_android_public_keys(self):
        self.assertEqual(self.host.adb_public_key(self.profile, os.getuid()), self.token)
        self.key.write_text(self.token + " owner-José\n")
        self.assertEqual(self.host.adb_public_key(self.profile, os.getuid()), self.token)
        with self.assertRaises(RuntimeError):
            self.host.adb_public_key(self.profile, os.getuid() + 1)
        for data in ("'; touch /tmp/forbidden", "A" * 5000, "not-base64 app-key"):
            self.key.write_text(data)
            with self.assertRaises(RuntimeError):
                self.host.adb_public_key(self.profile, os.getuid())
        self.key.unlink()
        outside = self.root / "outside.pub"
        outside.write_text(self.token)
        self.key.symlink_to(outside)
        with self.assertRaises(RuntimeError):
            self.host.adb_public_key(self.profile, os.getuid())
        self.key.unlink()
        os.mkfifo(self.key)
        with self.assertRaises(RuntimeError):
            self.host.adb_public_key(self.profile, os.getuid())

    def test_managed_authorization_adds_only_the_public_key_and_retains_authentication(self):
        self.key.write_text(self.token + " comment; touch /tmp/forbidden\n")
        commands = []
        authorized = ["another-authorized-key old-device\n"]
        def command(args, **kwargs):
            commands.append(args)
            if "cat" in args:
                return authorized[0]
            authorized[0] += self.token + " coc-bot\n"
            return ""
        self.runtime.command = command
        self.assertTrue(self.runtime.authorize_adb())
        self.assertFalse(self.runtime.authorize_adb())
        self.assertEqual(len(commands), 3)
        self.assertEqual(commands[1][:3], ["waydroid", "shell", "--"])
        script = commands[1][-1]
        self.assertIn(self.token, script)
        self.assertIn("/data/misc/adb/adb_keys", script)
        self.assertNotIn("forbidden", script)
        self.assertNotIn("ro.adb.secure", str(commands))
        self.assertFalse((self.directory / "adbkey").exists())

    def test_already_authorized_key_is_not_rewritten(self):
        commands = []
        def command(args, **kwargs):
            commands.append(args)
            return self.token + " existing-comment\n"
        self.runtime.command = command
        self.assertFalse(self.runtime.authorize_adb())
        self.assertEqual(len(commands), 1)
        self.assertNotIn("sh", commands[0])

    def test_adopted_android_does_not_enroll_or_read_managed_keys(self):
        self.runtime.config["prepare_adb"] = False
        self.key.unlink()
        with patch.object(self.runtime, "command") as command:
            self.assertFalse(self.runtime.authorize_adb())
            command.assert_not_called()

    def test_key_generation_failure_is_unpublished_and_existing_identity_is_preserved(self):
        installer = module("install_host")
        self.key.unlink()
        def generate(*args, **kwargs):
            private = Path(args[2])
            private.write_bytes(b"private-test-identity")
            private.with_suffix(".pub").write_text(self.token)
        with patch.object(installer, "run", side_effect=RuntimeError("keygen failed")):
            with self.assertRaises(RuntimeError):
                installer.create_adb_identity(self.profile, os.getuid(), os.getgid())
        self.assertFalse((self.directory / "adbkey").exists())
        link = os.link
        def fail_publication(source, destination):
            if Path(destination).suffix == ".pub":
                raise OSError("disk full")
            return link(source, destination)
        with patch.object(installer, "run", side_effect=generate), patch.object(installer.os, "link", side_effect=fail_publication):
            with self.assertRaises(OSError):
                installer.create_adb_identity(self.profile, os.getuid(), os.getgid())
        self.assertFalse((self.directory / "adbkey").exists())
        with patch.object(installer, "run", side_effect=generate):
            installer.create_adb_identity(self.profile, os.getuid(), os.getgid())
        before = {p.name: p.read_bytes() for p in self.directory.iterdir()}
        with patch.object(installer, "run") as run:
            installer.create_adb_identity(self.profile, os.getuid(), os.getgid())
            run.assert_not_called()
        self.assertEqual({p.name: p.read_bytes() for p in self.directory.iterdir()}, before)
        self.assertEqual((self.directory / "adbkey").stat().st_mode & 0o777, 0o600)

    def test_incomplete_pair_is_not_silently_replaced(self):
        installer = module("install_host")
        self.key.unlink()
        private = self.directory / "adbkey"
        private.write_bytes(b"keep-original-private-key")
        with self.assertRaisesRegex(RuntimeError, "Incomplete"):
            installer.create_adb_identity(self.profile, os.getuid(), os.getgid())
        self.assertEqual(private.read_bytes(), b"keep-original-private-key")

    def test_systemd_readiness_notification_is_sent_to_its_socket(self):
        import socket
        path = str(self.root / "notify.sock")
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as receiver:
            receiver.bind(path)
            receiver.settimeout(1)
            with patch.dict(os.environ, {"NOTIFY_SOCKET": path}):
                self.host.notify_ready()
            self.assertEqual(receiver.recv(32), b"READY=1")

    def test_helper_unit_upgrade_waits_for_readiness_and_is_idempotent(self):
        installer = module("install_host")
        old = "[Service]\nRuntimeDirectoryMode=0755\nExecStart=/usr/bin/python3 helper.py\n"
        new = installer.upgrade_helper_unit(old)
        self.assertIn("Type=notify\n", new)
        self.assertIn("TimeoutStartSec=30\n", new)
        self.assertIn("RuntimeDirectoryPreserve=restart\n", new)
        self.assertEqual(installer.upgrade_helper_unit(new), new)

    @skipIf(os.name == "nt" or getattr(os, "geteuid", lambda: 1)() != 0 or
            not shutil.which("setpriv") or not shutil.which("adb"), "Real identity generation needs the Linux root package image")
    def test_root_setup_generates_real_keys_as_the_app_user(self):
        installer = module("install_host")
        self.root.chmod(0o755)
        profile = self.root / "new-profile"
        profile.mkdir(mode=0o700)
        os.chown(profile, 1000, 1000)
        installer.create_adb_identity(profile)
        private = profile / ".android/adbkey"
        self.assertEqual(private.stat().st_uid, 1000)
        self.assertEqual(private.stat().st_mode & 0o777, 0o600)
        self.assertTrue(self.host.adb_public_key(profile, 1000))


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
            if args[0] == "lxc-attach":
                raise subprocess.TimeoutExpired(args, 3)
            return "Session: RUNNING\nContainer: STOPPED\nIP address: 192.0.2.77\n"
        self.runtime.command = command
        result = self.runtime.status()
        self.assertEqual(result["session"], "STOPPED")
        self.assertEqual(result["container"], "STOPPED")

    def test_status_recognizes_a_healthy_payload_without_starting_an_adb_server(self):
        commands = []
        def command(args, **kwargs):
            commands.append(args)
            if args[0] == "lxc-attach":
                return "1\n"
            return "Session: RUNNING\nContainer: STOPPED\nIP address: 192.0.2.77\n"
        self.runtime.command = command
        self.assertEqual(self.runtime.status()["container"], "RUNNING")
        self.assertFalse(any(args[0] == "adb" for args in commands))

    def test_first_boot_unknown_ip_is_pending_and_never_published_as_a_device(self):
        for ip in ("UNKNOWN", "", "N/A", "not-an-ip", "::1"):
            with self.subTest(ip=ip):
                self.runtime.command = lambda *args, **kwargs: (
                    "Session: RUNNING\nContainer: RUNNING\nIP address: " + ip + "\n")
                self.assertIsNone(self.runtime.status()["ip"])
                self.assertFalse(self.path.with_name("device.json").exists())

    def test_new_android_waits_for_boot_before_configuring_adb_and_returning_ready(self):
        marker = Path(self.temp.name) / "android-adb-prepared"
        boot_reads = iter(["0\n", "1\n"])
        commands = []
        self.runtime.config["prepare_adb"] = True
        def command(args, **kwargs):
            commands.append(args)
            if args[:2] == ["waydroid", "status"]:
                return "Session: RUNNING\nContainer: RUNNING\nIP address: 192.0.2.77\n"
            if args[0] == "lxc-attach":
                return next(boot_reads)
            return ""
        self.runtime.command = command
        clock = SimpleNamespace(monotonic=iter([0, 200, 400]).__next__, sleep=lambda _: None)
        with patch.object(self.host, "ADB_PREPARED", marker, create=True), \
                patch.object(self.host, "time", clock), \
                patch.object(self.runtime, "adb_port_ready", return_value=True), \
                patch.object(self.runtime, "authorize_adb", return_value=False):
            result = self.runtime.ensure()
        self.assertEqual(result["session"], "RUNNING")
        self.assertTrue(marker.exists())
        self.assertEqual(sum(args[0] == "lxc-attach" for args in commands), 2)
        self.assertNotIn(["waydroid", "shell", "setprop", "ctl.restart", "adbd"], commands)

    def test_reboot_waits_for_boot_even_when_tcp_was_prepared_previously(self):
        marker = Path(self.temp.name) / "android-adb-prepared"
        marker.write_text("configured\n")
        self.runtime.config["prepare_adb"] = True
        with patch.object(self.host, "ADB_PREPARED", marker), \
                patch.object(self.runtime, "android_booted", side_effect=[False, True]) as boot, \
                patch.object(self.runtime, "adb_port_ready", return_value=True), \
                patch.object(self.runtime, "authorize_adb", return_value=False), \
                patch.object(self.host.time, "sleep"):
            self.runtime.ensure()
        self.assertEqual(boot.call_count, 2)
        self.assertEqual(marker.read_text(), "configured\n")

    def test_new_tcp_configuration_waits_for_its_listener_and_only_configures_once(self):
        marker = Path(self.temp.name) / "android-adb-prepared"
        self.runtime.config["prepare_adb"] = True
        commands = []
        def command(args, **kwargs):
            commands.append(args)
            return "Session: RUNNING\nContainer: RUNNING\nIP address: 192.0.2.77\n" if args[0] == "waydroid" and args[1] == "status" else ""
        self.runtime.command = command
        with patch.object(self.host, "ADB_PREPARED", marker), \
                patch.object(self.runtime, "android_booted", return_value=True), \
                patch.object(self.runtime, "adb_port_ready", side_effect=[False, False, True]), \
                patch.object(self.runtime, "authorize_adb", return_value=False), \
                patch.object(self.host.time, "sleep"):
            self.runtime.ensure()
        self.assertTrue(marker.exists())
        self.assertEqual(commands.count(["waydroid", "shell", "settings", "put", "global", "adb_enabled", "1"]), 1)
        self.assertEqual(commands.count(["waydroid", "shell", "setprop", "ctl.restart", "adbd"]), 1)

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
