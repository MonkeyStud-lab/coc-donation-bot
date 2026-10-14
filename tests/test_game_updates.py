from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from coc_bot.control import game_updates as updates


class UpdateTests(unittest.TestCase):
    def test_redirects_only_allow_source_and_download_cdn_over_https(self):
        for url in (updates.SOURCE, "https://data.winudf.com/APK/file"):
            updates.allowed_url(url)
        for url in ("http://data.winudf.com/file", "https://data.winudf.com.evil.test/file",
                    "https://127.0.0.1/file", "https://user@data.winudf.com/file",
                    "https://data.winudf.com:444/file"):
            with self.assertRaises(ValueError):
                updates.allowed_url(url)

    def test_apk_metadata_rejects_other_apps_and_split_apks(self):
        for package, suffix in (("evil.package", ""), (updates.PACKAGE, " split='config.arm64'")):
            result = SimpleNamespace(returncode=0, stdout=f"package: name='{package}' versionCode='2' versionName='2.0'{suffix}\n")
            with patch.object(updates.subprocess, "run", return_value=result):
                with self.assertRaises(ValueError):
                    updates.inspect_apk(Path("candidate.apk"))

    def test_invalid_signatures_rejected_even_with_certificate_output(self):
        result = SimpleNamespace(returncode=1, stdout="Signer #1 certificate SHA-256 digest: " + "a"*64)
        with patch.object(updates.subprocess, "run", return_value=result):
            with self.assertRaises(ValueError):
                updates.signer(Path("bad.apk"))

    def test_incomplete_download_rejected(self):
        opener = MagicMock()
        response = opener.open.return_value.__enter__.return_value
        response.headers = {"Content-Length": "4"}
        response.geturl.return_value = "https://data.winudf.com/file"
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/"file.apk"
            def run(*args, **kwargs):
                target.write_bytes(b"abc")
                return SimpleNamespace(returncode=0, stdout="200")
            with patch.object(updates, "run_process", side_effect=run), self.assertRaises(ValueError):
                updates.download(opener, target, lambda _: None, lambda: None)

    def test_redirect_is_checked_before_a_second_network_request(self):
        response = SimpleNamespace(returncode=0, stdout="HTTP/2 302\r\nLocation: http://127.0.0.1/private\r\n\r\n")
        with patch.object(updates, "run_process", return_value=response) as run:
            with self.assertRaises(ValueError), updates.CurlSource().open(updates.Request(updates.SOURCE)):
                pass
        self.assertEqual(run.call_count, 1)

    def client(self):
        client = MagicMock()
        client.run_shell.side_effect = [SimpleNamespace(stdout="package:/data/app/trusted/base.apk\n"),
                                       SimpleNamespace(stdout="versionCode=1 versionName=1.0\n")]
        return client

    def opener(self):
        opener = MagicMock()
        response = opener.open.return_value.__enter__.return_value
        response.headers = {}
        response.geturl.return_value = "https://data.winudf.com/file"
        return opener

    def test_certificate_mismatch_never_installs(self):
        client = self.client()
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(updates, "build_opener", return_value=self.opener()), \
                patch.object(updates, "download"), \
                patch.object(updates, "inspect_apk", return_value=(2, "2.0")), \
                patch.object(updates, "signer", side_effect=[{"a"}, {"b"}]), \
                patch.object(updates.shutil, "disk_usage", return_value=SimpleNamespace(free=10**10)):
            with self.assertRaisesRegex(ValueError, "signer"):
                updates.update_game(client, Path(folder), lambda _: None, lambda: None)
        self.assertTrue(all(call.args[0][0] != "install" for call in client.run.call_args_list))

    def test_older_versions_never_install(self):
        client = self.client()
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(updates, "build_opener", return_value=self.opener()), \
                patch.object(updates, "download"), \
                patch.object(updates, "inspect_apk", return_value=(1, "1.0")), \
                patch.object(updates.shutil, "disk_usage", return_value=SimpleNamespace(free=10**10)):
            result = updates.update_game(client, Path(folder), lambda _: None, lambda: None)
        self.assertIn("no downgrade", result)
        client.run.assert_not_called()

    def test_matching_latest_version_skips_large_download(self):
        client = self.client()
        opener = self.opener()
        opener.open.return_value.__enter__.return_value.headers = {
            "Content-Disposition": 'attachment; filename="Clash+of+Clans_1.0_APKPure.apk"'}
        with patch.object(updates, "build_opener", return_value=opener), patch.object(updates, "download") as download:
            self.assertIn("up to date", updates.update_game(client, Path("unused"), lambda _: None, lambda: None))
        download.assert_not_called()
        client.run.assert_not_called()

    def test_verified_update_backs_up_then_installs_without_uninstalling(self):
        self.verified_update()

    def test_committed_update_is_confirmed_when_installer_response_times_out(self):
        self.verified_update(timeout=True)

    def test_failed_install_keeps_backup_and_is_not_reported_as_updated(self):
        self.verified_update(timeout=True, committed=False)

    def verified_update(self, timeout=False, committed=True):
        client = self.client()
        client.run_shell.side_effect = [SimpleNamespace(stdout="package:/data/app/trusted/base.apk\n"),
            SimpleNamespace(stdout="versionCode=1 versionName=1.0\n"),
            SimpleNamespace(stdout="versionCode=2 versionName=2.0\n" if committed else
                            "versionCode=1 versionName=1.0\n")]
        calls = []
        def run(args, **kwargs):
            calls.append(args[0])
            if args[0] == "pull":
                Path(args[2]).write_bytes(b"old-apk")
            if args[0] == "install":
                self.assertEqual(args[1:3], ["--no-streaming", "-r"])
                self.assertTrue((root / "game-update-backup/part-00.apk").exists())
                self.assertTrue(backup.called)
                if timeout:
                    raise TimeoutError("installer response timed out")
            return SimpleNamespace(stdout="Success", returncode=0)
        client.run.side_effect = run
        backup = MagicMock()
        def download(opener, destination, *args):
            destination.write_bytes(b"new-apk")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "calibrated.yaml").write_text("unchanged")
            with patch.object(updates, "build_opener", return_value=self.opener()), \
                    patch.object(updates, "download", side_effect=download), \
                    patch.object(updates, "inspect_apk", return_value=(2, "2.0")), \
                    patch.object(updates, "signer", return_value={"a"}), \
                    patch.object(updates.shutil, "disk_usage", return_value=SimpleNamespace(free=10**10)), \
                    patch.dict("sys.modules", {"coc_bot.control.backups": SimpleNamespace(create_backup=backup)}):
                if committed:
                    self.assertIn("Updated Clash to 2.0", updates.update_game(client, root, lambda _: None, lambda: None))
                else:
                    with self.assertRaises(TimeoutError):
                        updates.update_game(client, root, lambda _: None, lambda: None)
            self.assertEqual((root / "calibrated.yaml").read_text(), "unchanged")
        self.assertEqual(calls, ["pull", "pull", "install"])
