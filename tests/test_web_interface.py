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
        self.client = TestClient(create_app(self.service, origins=["http://testserver"], password_required=True))
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

    def test_attack_review_is_private_revisioned_and_does_not_enable_deployment(self):
        from coc_bot.attack.army import ArmyCard
        from coc_bot.control.attack_observation import write_report
        ident='b'*32
        folder=self.home/'data/debug/attack-observations'/ident
        folder.mkdir(parents=True)
        report={'attack_observation':True,'observation_id':ident,'cards':[
            ArmyCard('card-0',(0,0,10,10),None,'hero',1).to_dict()],
            'ready_for_execution':False,'map':{'coverage':'partial'}}
        write_report(folder,report)
        (folder/'overlay.png').write_bytes(b'test-image')
        url='/api/attack-observations/'+ident
        self.assertEqual(self.client.get(url).status_code,200)
        self.assertEqual(self.client.get(url+'/images/overlay.png').content,b'test-image')
        body={'revision':report['revision'],'corrections':[
            {'slot':'card-0','unit_id':'barbarian_king','kind':'hero','quantity':1,'confirmed':True}]}
        self.assertEqual(self.client.patch(url,json=body).status_code,403)
        updated=self.client.patch(url,json=body,headers=self.headers)
        self.assertEqual(updated.status_code,200)
        self.assertTrue(updated.json()['cards'][0]['confirmed'])
        self.assertFalse(updated.json()['ready_for_execution'])
        self.assertEqual(self.client.patch(url,json=body,headers=self.headers).status_code,400)
        self.assertEqual(self.client.get(url+'/images/report.json').status_code,400)
        self.client.post('/api/logout',headers=self.headers)
        self.assertEqual(self.client.get(url+'/images/overlay.png').status_code,401)

    def test_automatic_attack_needs_csrf_exclusive_ownership_and_honors_stop(self):
        from unittest.mock import Mock
        entered=threading.Event()
        session=Mock()
        def run(stop, *, automatic=False):
            self.assertTrue(automatic)
            entered.set()
            while not stop():
                threading.Event().wait(.01)
            return False,'Stopped'
        session.farm_one_shot.side_effect=run
        self.service.session_factory=lambda:session
        url='/api/attack-planner/automatic'
        self.assertEqual(self.client.post(url).status_code,403)
        self.assertEqual(self.client.post(url,headers=self.headers).status_code,200)
        self.assertTrue(entered.wait(1))
        self.assertEqual(self.client.post(url,headers=self.headers).status_code,409)
        self.client.post('/api/stop',headers=self.headers)
        self.assertTrue(self.service.controller.wait(1))
        self.assertEqual(self.service.result,{'automatic_attack':True,'success':False,'message':'Stopped'})
        self.assertFalse((self.home/'data/attack-planner/routine.json').exists())

    def test_automatic_attack_method_roundtrips_in_settings(self):
        saved=save_settings({'farm_engine':'automatic'},revision())
        self.assertEqual(load_config().farm_engine,'automatic')
        self.assertEqual(settings_snapshot()['values']['farm_engine'],'automatic')

    def test_attack_planner_requires_csrf_valid_geometry_and_idle_ownership(self):
        from coc_bot.attack.army import ArmyCard
        from coc_bot.attack.plans import AttackPlan,ArmyEntry,PlanStep,MapPoint
        from coc_bot.control.attack_observation import write_report
        ident='d'*32;folder=self.home/'data/debug/attack-observations'/ident;folder.mkdir(parents=True)
        report={'observation_id':ident,'page':'battle','device':load_config().adb_device,
                'survey':{'captured_at':0},'cards':[ArmyCard('card-0',(0,0,20,20),
                   'electro_dragon','troop',11,confirmed=True).to_dict()]}
        write_report(folder,report)
        plan=AttackPlan((ArmyEntry('electro_dragon','troop',11,True),),
                       (PlanStep('deploy_point','electro_dragon',11,(MapPoint(.055,.5),)),))
        body={'observation_id':ident,'revision':report['revision'],'plan':plan.to_dict(),
              'corners':[[500,50],[900,300],[500,550],[100,300]]}
        self.assertEqual(self.client.post('/api/attack-planner/preview',json=body).status_code,403)
        invalid=body|{'corners':[[0,0]]*4}
        self.assertEqual(self.client.post('/api/attack-planner/preview',json=invalid,headers=self.headers).status_code,400)
        entered=threading.Event()
        self.service.job('other tool',lambda cancel:(entered.set(),cancel.wait(1)))
        self.assertTrue(entered.wait(1))
        self.assertEqual(self.client.post('/api/attack-planner/preview',json=body,headers=self.headers).status_code,409)
        review={'revision':report['revision'],'corrections':[]}
        self.assertEqual(self.client.patch('/api/attack-observations/'+ident,json=review,headers=self.headers).status_code,409)
        self.service.stop();self.assertTrue(self.service.controller.wait(1))
        saved=self.client.post('/api/attack-planner/preview',json=body,headers=self.headers)
        self.assertEqual(saved.status_code,200,saved.text)
        self.assertFalse(saved.json()['ready_for_execution'])
        self.assertEqual(self.client.get('/api/attack-planner').json()['report']['observation_id'],ident)

    def test_saved_attack_routine_can_be_loaded_but_not_from_another_device(self):
        from coc_bot.attack.plans import AttackPlan,ArmyEntry,PlanStep,MapPoint
        from coc_bot.control.attack_planner import template_path
        plan=AttackPlan((ArmyEntry('electro_dragon','troop',11,True),),
                       (PlanStep('deploy_point','electro_dragon',11,(MapPoint(.055,.5),)),))
        config=load_config();path=template_path(config);path.parent.mkdir(parents=True)
        value={'device':config.adb_device,'plan':plan.to_dict(),'live_verified':False}
        path.write_text(json.dumps(value))
        response=self.client.get('/api/attack-planner/routine')
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['steps'][0]['quantity'],11)
        value['device']='different-device';path.write_text(json.dumps(value))
        self.assertEqual(self.client.get('/api/attack-planner/routine').status_code,400)

    def test_password_free_bootstrap_keeps_csrf_origin_and_socket_guards(self):
        service = ControlService()
        with TestClient(create_app(service, auth_path=self.home / "missing-password.json",
                                   origins=["http://testserver"])) as client:
            self.assertEqual(client.get("/api/status").status_code, 401)
            self.assertEqual(client.get("/api/session", headers={"Origin": "http://evil.invalid"}).status_code, 403)
            session = client.get("/api/session")
            self.assertEqual(session.status_code, 200)
            self.assertFalse(session.json()["password_required"])
            headers = {"X-CSRF-Token": session.json()["csrf"]}
            self.assertEqual(client.get("/api/session").json()["csrf"], session.json()["csrf"])
            self.assertEqual(client.get("/api/status").status_code, 200)
            self.assertEqual(client.post("/api/stop").status_code, 403)
            self.assertEqual(client.post("/api/stop", headers=headers).status_code, 200)
            self.assertEqual(client.post("/api/stop", headers={**headers, "Origin": "http://evil.invalid"}).status_code, 403)
            with client.websocket_connect("/api/events/ws", headers={"Origin": "http://testserver"}) as socket:
                self.assertIn("status", socket.receive_json())
            auth = client.app.state.auth
            auth.logout(client.cookies.get("coc_session"))
            self.assertEqual(client.get("/api/status").status_code, 401)
            renewed = client.get("/api/session").json()
            self.assertNotEqual(renewed["csrf"], headers["X-CSRF-Token"])
            self.assertEqual(client.get("/api/status").status_code, 200)
            self.assertFalse((self.home / "missing-password.json").exists())

    def test_password_free_launcher_rejects_public_and_wildcard_bind(self):
        from coc_bot.web.__main__ import main
        for host in ("0.0.0.0", "::", "8.8.8.8", "224.0.0.1", "169.254.1.1"):
            with self.subTest(host=host), self.assertRaises(SystemExit) as raised:
                main(["--host", host, "--origin", "http://testserver"])
            self.assertEqual(raised.exception.code, 2)

    def test_settings_revision_and_validation(self):
        settings = self.client.get("/api/settings").json()
        self.assertEqual(len(settings["fields"]), 47)
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

    def test_upgrade_api_validation_and_exclusive_ownership(self):
        self.assertEqual(self.client.post('/api/upgrades/preview', json={'kind':'research'}).status_code, 403)
        for body in ({'kind':'gems'}, {'kind':'research','token':'x'*65}):
            self.assertEqual(self.client.post('/api/upgrades/preview', headers=self.headers,
                                             json=body).status_code, 422)
        self.assertEqual(self.client.post('/api/upgrades/start', headers=self.headers,
                                         json={'kind':'research'}).status_code, 400)
        with patch.object(self.service, 'upgrade') as upgrade:
            self.assertEqual(self.client.post('/api/upgrades/preview', headers=self.headers,
                                             json={'kind':'buildings'}).status_code, 200)
            upgrade.assert_called_once_with('buildings')
            upgrade.reset_mock()
            self.assertEqual(self.client.post('/api/upgrades/start', headers=self.headers,
                                             json={'kind':'research','token':'a'*64}).status_code, 200)
            upgrade.assert_called_once_with('research',execute=True,token='a'*64)
        entered=threading.Event()
        def work(cancel):
            entered.set()
            cancel.wait(2)
        self.service.job('holding-device',work)
        self.assertTrue(entered.wait(1))
        self.assertEqual(self.client.post('/api/upgrades/preview',headers=self.headers,
                                         json={'kind':'research'}).status_code,409)
        self.service.stop()
        self.assertTrue(self.service.controller.wait(1))

    def test_upgrade_settings_validate_reserves_and_keep_automation_off(self):
        config=load_config()
        self.assertFalse(config.upgrade_buildings_enabled)
        self.assertFalse(config.upgrade_research_enabled)
        for values in ({'upgrade_gold_reserve':-1}, {'upgrade_builders_reserved':7},
                       {'upgrade_interval_seconds':0}, {'upgrade_research_enabled':'true'},
                       {'upgrade_elixir_reserve':'nan'}, {'upgrade_elixir_reserve':'inf'},
                       {'upgrade_elixir_reserve':True}, {'upgrade_elixir_reserve':1.5}):
            response=self.client.put('/api/settings',headers=self.headers,
                                     json={'revision':revision(),'values':values})
            self.assertEqual(response.status_code,400,response.text)

    def test_upgrade_reserves_above_ten_million_round_trip(self):
        keys=('upgrade_gold_reserve','upgrade_elixir_reserve','upgrade_dark_elixir_reserve')
        for amount in (0,10_000_001,20_000_000,100_000_000):
            with self.subTest(amount=amount):
                values={key:amount for key in keys}
                response=self.client.put('/api/settings',headers=self.headers,
                                         json={'revision':revision(),'values':values})
                self.assertEqual(response.status_code,200,response.text)
                for key in keys:
                    self.assertEqual(response.json()['values'][key],amount)
                    self.assertEqual(getattr(load_config(),key),amount)
        # A stored large reserve must not block saving an unrelated setting.
        response=self.client.put('/api/settings',headers=self.headers,
                                 json={'revision':revision(),'values':{'donate_open_requests':False}})
        self.assertEqual(response.status_code,200,response.text)
        self.assertFalse(load_config().upgrade_buildings_enabled)
        self.assertFalse(load_config().upgrade_research_enabled)
        self.assertFalse(self.service.controller.snapshot().active)

    def test_upgrade_limits_match_browser_and_desktop_validation(self):
        from coc_bot.control.settings_fields import build_user_settings_payload,current_setting_values
        limits={'upgrade_gold_reserve':(0,100_000_000),'upgrade_elixir_reserve':(0,100_000_000),
                'upgrade_dark_elixir_reserve':(0,100_000_000),'upgrade_builders_reserved':(0,6),
                'upgrade_interval_seconds':(60,86400)}
        for key,(lower,upper) in limits.items():
            for value in (lower,upper):
                with self.subTest(key=key,value=value):
                    build_user_settings_payload(current_setting_values()|{key:value})
                    response=self.client.put('/api/settings',headers=self.headers,
                                             json={'revision':revision(),'values':{key:value}})
                    self.assertEqual(response.status_code,200,response.text)
            for value in (lower-1,upper+1):
                with self.subTest(key=key,value=value):
                    with self.assertRaises(ValueError):
                        build_user_settings_payload(current_setting_values()|{key:value})
                    before=revision()
                    response=self.client.put('/api/settings',headers=self.headers,
                                             json={'revision':before,'values':{key:value}})
                    self.assertEqual(response.status_code,400,response.text)
                    self.assertEqual(revision(),before)

    def test_managed_runtime_import_is_optional_guarded_and_preserves_calibration(self):
        from types import SimpleNamespace
        import io
        import zipfile
        self.assertEqual(self.client.post("/api/runtime/retry", headers=self.headers).status_code, 404)
        starts = []
        self.service.platform = SimpleNamespace(
            snapshot=lambda: {"ready": False, "busy": False, "stage": "needs_game", "message": "Import", "error": None},
            start=lambda: starts.append(True), stop=lambda: None)
        self.assertEqual(self.client.post("/api/runtime/import-game", content=b"bad").status_code, 403)
        self.assertEqual(self.client.post("/api/runtime/import-game", headers=self.headers, content=b"bad").status_code, 400)
        self.assertEqual(self.client.post("/api/runtime/import-game", headers={**self.headers,
            "Content-Length": str(2*1024**3+1)}, content=b"bad").status_code, 413)
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as file:
            file.writestr("base.apk", b"private-installation-file")
        with patch("coc_bot.control.platform.validate_apks"):
            response = self.client.post("/api/runtime/import-game", headers=self.headers, content=archive.getvalue())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(starts, [True])
        self.assertEqual((self.home / "data/game-apks/part-00.apk").read_bytes(), b"private-installation-file")
        self.assertFalse((self.home / "data/calibrated.yaml").exists())

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

    def test_suggestion_preview_never_saves_and_rejects_stale_or_expired_captures(self):
        captures = self.client.app.state.captures
        meta = captures.add(np.zeros((540, 960, 3), dtype=np.uint8))
        before = calibration_revision()
        url = '/api/captures/'+meta['id']+'/suggestions'
        result = self.client.get(url)
        self.assertEqual(result.status_code, 200)
        self.assertFalse(result.json()['supported'])
        self.assertEqual(result.json()['capture'], meta['id'])
        self.assertEqual(calibration_revision(), before)
        self.assertFalse((self.home/'data/calibrated.yaml').exists())
        from test_donation_calibration import panel
        visible = captures.add(panel())
        preview = self.client.get('/api/captures/'+visible['id']+'/suggestions')
        self.assertEqual(preview.status_code, 200)
        self.assertTrue(preview.json()['supported'])
        self.assertEqual(len(preview.json()['proposals']), 6)
        self.assertEqual(calibration_revision(), before)
        self.assertFalse((self.home/'data/calibrated.yaml').exists())
        captures.save(meta['id'], 'frame_width', [], meta['revision'])
        self.assertIn(self.client.get(url).status_code, (400, 409))
        for _ in range(9):
            captures.add(np.zeros((540,960,3), dtype=np.uint8))
        self.assertEqual(self.client.get(url).status_code, 400)
        self.client.post('/api/logout', headers=self.headers)
        self.assertEqual(self.client.get(url).status_code, 401)

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

    def test_live_failure_is_clear_and_does_not_take_input_ownership(self):
        with patch("coc_bot.web.live.check_dependencies", side_effect=ValueError("Install live view first")):
            with self.client.websocket_connect("/api/live/ws", headers={"Origin": "http://testserver"}) as ws:
                self.assertEqual(ws.receive_json(), {"type": "error", "message": "Install live view first"})
        self.assertFalse(self.service.snapshot()["manual_control"])
        self.assertFalse(self.service.controller.snapshot().active)

    def test_live_rejects_wrong_origin_and_logged_out_session(self):
        from starlette.websockets import WebSocketDisconnect
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect("/api/live/ws", headers={"Origin": "http://evil.invalid"}):
                pass
        self.client.post("/api/logout", headers=self.headers)
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect("/api/live/ws", headers={"Origin": "http://testserver"}):
                pass

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
