"""Offline API integration: no device, production config, or desktop required."""
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
import json
import shutil
import tempfile
import threading
import numpy as np
from fastapi.testclient import TestClient
from coc_bot.config import project_root, load_config
from coc_bot.control.lifecycle import BotController
from coc_bot.control.service import ControlService, BusyError
from coc_bot.control.events import EventHistory
from coc_bot.control.calibration import Captures, checklist, calibration_revision
from coc_bot.control.settings import save_settings, revision, settings_snapshot, RevisionConflict
from coc_bot.web.auth import set_password
from coc_bot.web.server import create_app


class WebTests(TestCase):
    def setUp(self):
        root = project_root()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        shutil.copytree(root / "config", self.home / "config")
        self.env = patch.dict("os.environ", {"COC_BOT_HOME": str(self.home),
            "COC_BOT_CONFIG": str(self.home / "data/calibrated.yaml")})
        self.env.start()
        self.addCleanup(self.env.stop)
        (self.home / "data").mkdir()
        self.auth_path = self.home / "data/web-auth.json"
        set_password(self.auth_path, "testing-password-123")
        self.service = ControlService()
        self.client = TestClient(create_app(self.service, origins=["http://testserver"]))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        result = self.client.post("/api/login", json={"password": "testing-password-123"})
        self.assertEqual(result.status_code, 200)
        self.headers = {"X-CSRF-Token": result.json()["csrf"]}

    def test_authentication_origin_csrf_and_logout(self):
        self.assertEqual(self.client.post("/api/stop").status_code, 403)
        self.assertEqual(self.client.post("/api/stop", headers=self.headers).status_code, 200)
        self.assertEqual(self.client.get("/api/status", headers={"Origin": "http://evil.invalid"}).status_code, 403)
        self.client.post("/api/logout", headers=self.headers)
        self.assertEqual(self.client.get("/api/status").status_code, 401)

    def test_settings_revision_and_validation(self):
        settings = self.client.get("/api/settings").json()
        self.assertEqual(len(settings["fields"]), 38)
        self.assertEqual(len(settings["themes"]), 7)
        body = {"revision": settings["revision"], "values": {"farm_interval_seconds": 7200}}
        result = self.client.put("/api/settings", headers=self.headers, json=body)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(load_config().farm_interval_seconds, 7200)
        self.assertEqual(self.client.put("/api/settings", headers=self.headers, json=body).status_code, 409)
        for values in ({"donate_open_requests": "false"}, {"farm_pan_swipes": -1},
                       {"farm_pan_swipes": None}, {"farm_pan_swipes": True},
                       {"scan_interval_ms": "200, 100"}, {"gui_theme": "missing"}, {"unknown": 1}):
            body = {"revision": revision(), "values": values}
            self.assertEqual(self.client.put("/api/settings", headers=self.headers, json=body).status_code, 400)

    def test_jobs_priority_stop_and_busy_settings(self):
        entered = threading.Event()
        def job(cancel):
            entered.set()
            cancel.wait(2)
            return "Canceled"
        self.service.job("fake-farm", job)
        self.assertTrue(entered.wait(1))
        with self.assertRaises(BusyError):
            self.service.job("other", job)
        result = self.client.put("/api/settings", headers=self.headers,
                                json={"revision": revision(), "values": {}})
        self.assertEqual(result.status_code, 409)
        self.client.post("/api/stop", headers=self.headers)
        self.assertTrue(self.service.controller.wait(1))
        self.assertEqual(self.service.snapshot()["result"], "Canceled")

    def test_stopped_device_job_is_not_reported_as_failure(self):
        from coc_bot.adb.client import AdbStopped
        entered = threading.Event()
        def job(cancel):
            entered.set()
            cancel.wait(2)
            raise AdbStopped("Stopped")
        self.service.job("device-test", job)
        self.assertTrue(entered.wait(1))
        self.service.stop()
        self.assertTrue(self.service.controller.wait(1))
        self.assertEqual(self.service.snapshot()["state"], "stopped")
        self.assertIsNone(self.service.snapshot()["error"])

    def test_chunked_body_size_limit(self):
        result = self.client.post("/api/stop", headers=self.headers,
                                  content=iter([b'x'*60000, b'x'*60000]))
        self.assertEqual(result.status_code, 413)

    def test_calibration_all_parts_and_transaction(self):
        captures = self.client.app.state.captures
        frame = np.full((100, 160, 3), 123, dtype=np.uint8)
        parts = [p for s in checklist()["steps"] for p in s["parts"]]
        self.assertEqual(len(parts), 32)
        for part in parts:
            meta = captures.add(frame)
            key = part["key"]
            selection = [] if key == "frame_width" else (
                [[10, 20], [30, 40]] if key == "deploy_sequence" else [10, 10, 40, 20])
            result = self.client.post("/api/setup", headers=self.headers, json={
                "capture": meta["id"], "revision": meta["revision"], "part": key,
                "selection": selection, "cols": 2, "rows": 1, "jitter": 3})
            self.assertEqual(result.status_code, 200, (key, result.text))
        self.assertTrue(all(p["configured"] for s in checklist()["steps"] for p in s["parts"]))
        self.assertEqual(load_config().farm_deploy_jitter_px, 3)
        self.assertEqual(len(load_config().farm_deploy_sequence["taps"]), 2)
        self.assertTrue(list((self.home/"data/calibration_backups").iterdir()))

    def test_stale_invalid_and_expired_capture_preserves_data(self):
        captures = Captures()
        frame = np.zeros((100, 160, 3), dtype=np.uint8)
        meta = captures.add(frame)
        original = calibration_revision()
        for selection in ([159, 99, 40, 20], [-1, 1], [1.5, 2], [1, 2, 0, 4]):
            with self.assertRaises(ValueError):
                captures.save(meta["id"], "open_chat", selection, meta["revision"])
            self.assertEqual(calibration_revision(), original)
        captures.save(meta["id"], "frame_width", [], meta["revision"])
        with self.assertRaises(RevisionConflict):
            captures.save(meta["id"], "open_chat", [2, 3], meta["revision"])
        for _ in range(9):
            captures.add(frame)
        with self.assertRaises(ValueError):
            captures.get(meta["id"])

    def test_backup_path_guard(self):
        self.assertEqual(self.client.post("/api/backups/unknown/restore", headers=self.headers).status_code, 404)
        self.assertEqual(self.client.get("/api/library/images/unknown").status_code, 404)
        self.assertEqual(self.client.post("/api/diagnostics/exec", headers=self.headers).status_code, 400)

    def test_bounded_reconnect_history(self):
        history = EventHistory(3)
        for n in range(10):
            history.append("INFO", str(n))
        result = history.since()
        self.assertTrue(result["reset"])
        self.assertEqual([e["id"] for e in result["entries"]], [8, 9, 10])
        self.assertEqual(history.since(10)["entries"], [])

    def test_websocket_auth_and_snapshot(self):
        with self.client.websocket_connect("/api/events/ws", headers={"Origin": "http://testserver"}) as ws:
            data = ws.receive_json()
            self.assertIn("timers", data["status"])
            self.assertIn("cursor", data["events"])

    def test_archive_roundtrip_and_traversal_rejection(self):
        import io
        import zipfile
        from coc_bot.control.archive import import_calibration
        captures = self.client.app.state.captures
        meta = captures.add(np.zeros((100, 160, 3), dtype=np.uint8))
        captures.save(meta["id"], "frame_width", [], meta["revision"])
        backup = self.client.post("/api/backups", headers=self.headers).json()["id"]
        exported = self.client.get("/api/backups/"+backup+"/export")
        self.assertEqual(exported.status_code, 200)
        imported = self.client.post("/api/backups/import?name=Imported",
            headers=self.headers | {"Content-Type": "application/zip"}, content=exported.content)
        self.assertEqual(imported.status_code, 200, imported.text)
        malicious = io.BytesIO()
        with zipfile.ZipFile(malicious, "w") as archive:
            archive.writestr("../outside.txt", "bad")
        with self.assertRaises(ValueError):
            import_calibration(malicious.getvalue(), "Rejected")
        self.assertFalse((self.home / "data/calibration_backups/Rejected").exists())

    def test_viewer_ownership_coordinates_and_disconnect(self):
        from types import SimpleNamespace
        commands = []
        frame = np.zeros((100, 160, 3), dtype=np.uint8)
        def session():
            return SimpleNamespace(config=SimpleNamespace(adb_device="offline-viewer-test"),
                client=SimpleNamespace(run=lambda args: commands.append(args)),
                input=SimpleNamespace(), navigator=SimpleNamespace(), attack_nav=SimpleNamespace(),
                deployer=SimpleNamespace(), app=SimpleNamespace(),
                capture=SimpleNamespace(screenshot=lambda: frame.copy()))
        self.service.session_factory = session
        with self.client.websocket_connect("/api/viewer/ws", headers={"Origin": "http://testserver"}) as ws:
            self.assertEqual(ws.receive_json()["type"], "ready")
            self.assertTrue(self.service.snapshot()["manual_control"])
            with self.assertRaises(BusyError):
                self.service.job("competing", lambda cancel: None)
            ws.send_json({"type": "frame"})
            self.assertTrue(ws.receive_bytes().startswith(b"\xff\xd8"))
            ws.send_json({"type": "tap", "from": [10, 20]})
            ws.send_json({"type": "frame"})
            ws.receive_bytes()
            self.assertEqual(commands, [["shell", "input", "tap", "10", "20"]])
        self.assertFalse(self.service.snapshot()["manual_control"])
        self.assertFalse(self.service.controller.snapshot().active)

    def test_first_launch_isolation_reset_and_shared_ownership(self):
        original = (self.home / "data").glob("*")
        before = {p.name: p.read_bytes() for p in original if p.is_file()}
        self.assertTrue(self.client.get("/first-launch/api/mode").json()["first_launch"])
        self.assertEqual(self.client.post("/first-launch/api/stop").status_code, 403)
        test_settings = self.client.get("/first-launch/api/settings").json()
        result = self.client.put("/first-launch/api/settings", headers=self.headers,
            json={"revision": test_settings["revision"], "values": {"farm_interval_seconds": 7311}})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.client.get("/first-launch/api/settings").json()["values"]["farm_interval_seconds"], 7311)
        self.assertNotEqual(load_config().farm_interval_seconds, 7311)
        entered = threading.Event()
        self.service.job("test", lambda cancel: (entered.set(), cancel.wait(1)))
        self.assertTrue(entered.wait(1))
        self.assertEqual(self.client.put("/first-launch/api/settings", headers=self.headers,
            json={"revision": result.json()["revision"], "values": {}}).status_code, 409)
        self.service.stop()
        self.assertTrue(self.service.controller.wait(1))
        self.assertEqual(self.client.post("/api/first-launch/reset", headers=self.headers).status_code, 200)
        self.assertEqual(self.client.get("/first-launch/api/settings").json()["values"]["farm_interval_seconds"],
                         load_config().farm_interval_seconds)
        after = {p.name: p.read_bytes() for p in (self.home / "data").glob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(self.client.get("/first-launch/").status_code, 200)

    def test_worker_copies_profile_context(self):
        from coc_bot.config import profile_root
        selected = self.home / "isolated"
        token = profile_root.set(selected)
        observed = []
        try:
            self.service.job("context", lambda cancel: observed.append(project_root()))
        finally:
            profile_root.reset(token)
        self.assertTrue(self.service.controller.wait(1))
        self.assertEqual(observed, [selected])
        self.assertEqual(project_root(), self.home)

    def test_stopped_timers_remain_frozen_without_writing(self):
        from datetime import datetime, timedelta, timezone
        from coc_bot.runtime.persistence import RuntimeState, save_runtime_state
        save_settings({"farm_enabled": True, "farm_interval_seconds": 7200}, revision())
        state = RuntimeState.fresh()
        now = datetime.now(timezone.utc)
        state.last_farm_at = (now-timedelta(seconds=1000)).isoformat()
        state.farm_paused_at = (now-timedelta(seconds=900)).isoformat()
        state.next_farm_interval_seconds = 7200
        state.active_seconds = 500
        state.next_session_limit_seconds = 14400
        path = self.home / "data/runtime_state.json"
        save_runtime_state(path, state)
        original = path.read_bytes()
        for _ in range(2):
            snapshot = self.service.snapshot()
            self.assertEqual(snapshot["timers"], {"farm_seconds": 7100, "break_seconds": 13900})
            self.assertFalse(snapshot["active"])
        self.assertEqual(path.read_bytes(), original)

    def test_invalid_archive_mapping_is_rejected(self):
        import io, zipfile
        from coc_bot.control.archive import import_calibration
        for section in ('tap_points: [1, 2]', 'rois: {home: [0, 0, 10, 10]}',
                        'templates: {home: [1, 2]}', 'grid: {troop_bar: []}'):
            content = io.BytesIO()
            with zipfile.ZipFile(content, 'w') as archive:
                archive.writestr('calibrated.yaml', 'frame_width: 160\nframe_height: 100\n'+section)
            with self.assertRaises(ValueError):
                import_calibration(content.getvalue(), 'BadImport')
            self.assertFalse((self.home/'data/calibration_backups/BadImport').exists())
