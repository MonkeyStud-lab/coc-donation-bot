import os
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

from coc_bot.adb.client import AdbClient, AdbStopped
from coc_bot.adb.capture import ScreenCapture
from coc_bot.adb.capture_coordinator import latest_frame
from coc_bot.config import load_config
from coc_bot.gui.calib_backup import CalibrationBackup, restore_backup
from coc_bot.runtime.device_lease import DeviceLease, DeviceBusy
from coc_bot.runtime.processes import run_process, ProcessStopped
from coc_bot.runtime.persistence import load_runtime_state
from coc_bot.donation.executor import DonationExecutor
from coc_bot.donation.resource_mode import elixir_is_selected
from coc_bot.vision import ocr


class ReliabilityTests(unittest.TestCase):
    def test_restore_rolls_back_yaml_and_images_at_each_install_failure(self):
        for failure in ("new_templates", "new.yaml", "templates"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                data = root / "data"
                (data / "templates").mkdir(parents=True)
                (data / "calibrated.yaml").write_text("generation: old\n")
                (data / "templates/old.png").write_bytes(b"old")
                backup = root / "snapshot"
                (backup / "templates").mkdir(parents=True)
                (backup / "calibrated.yaml").write_text("generation: new\n")
                (backup / "templates/new.png").write_bytes(b"new")
                real_replace = os.replace
                def fail_once(source, destination):
                    if Path(source).name == failure:
                        raise OSError("simulated install failure")
                    return real_replace(source, destination)
                with patch("coc_bot.gui.calib_backup.os.replace", side_effect=fail_once):
                    with self.assertRaises(OSError):
                        restore_backup(CalibrationBackup(backup, "snapshot"), root, safety_snapshot=False)
                self.assertEqual((data / "calibrated.yaml").read_text(), "generation: old\n")
                self.assertEqual((data / "templates/old.png").read_bytes(), b"old")

    def test_restore_rejects_missing_template_before_touching_live(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backup = root / "snapshot"
            backup.mkdir()
            (backup / "calibrated.yaml").write_text("templates:\n  home: missing.png\n")
            with self.assertRaises(ValueError):
                restore_backup(CalibrationBackup(backup, "snapshot"), root)
            self.assertFalse((root / "data/calibrated.yaml").exists())

    def test_interrupted_restore_recovers_previous_generation(self):
        from coc_bot.calibration.transactions import recover_pending_restores
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            transaction = data / "calibration-restore-test"
            (transaction / "old_templates").mkdir(parents=True)
            (transaction / "old_templates/old.png").write_bytes(b"old")
            (transaction / "old.yaml").write_text("generation: old")
            (data / "templates").mkdir()
            (data / "templates/new.png").write_bytes(b"new")
            (data / "calibrated.yaml").write_text("generation: new")
            (transaction / "journal.json").write_text(json.dumps({"had_yaml": True, "had_templates": True, "committed": False}))
            recover_pending_restores(data)
            self.assertEqual((data / "calibrated.yaml").read_text(), "generation: old")
            self.assertTrue((data / "templates/old.png").is_file())
            self.assertFalse(transaction.exists())

    def test_failed_staging_copy_keeps_live_calibration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data/templates").mkdir(parents=True)
            (root / "data/calibrated.yaml").write_text("generation: old")
            backup = root / "snapshot"
            backup.mkdir()
            (backup / "calibrated.yaml").write_text("generation: new")
            with patch("coc_bot.gui.calib_backup.shutil.copy2", side_effect=OSError("copy failed")):
                with self.assertRaises(OSError):
                    restore_backup(CalibrationBackup(backup, "snapshot"), root, safety_snapshot=False)
            self.assertEqual((root / "data/calibrated.yaml").read_text(), "generation: old")

    def test_quit_waits_for_worker_without_blocking_gui(self):
        from coc_bot.gui.app import BotControlApp
        app = Mock()
        app._bot_running.return_value = True
        app._farm_oneshot_running.return_value = False
        BotControlApp._finish_close_when_idle(app)
        app._destroy_app.assert_not_called()
        app.after.assert_called_once()
        app._bot_running.return_value = False
        BotControlApp._finish_close_when_idle(app)
        app._destroy_app.assert_called_once()

    def test_subprocess_stop_kills_and_reaps_child(self):
        stopped = threading.Event()
        children = []
        original = subprocess.Popen
        def spawn(*args, **kwargs):
            child = original(*args, **kwargs)
            children.append(child)
            return child
        timer = threading.Timer(.15, stopped.set)
        timer.start()
        try:
            with patch("coc_bot.runtime.processes.subprocess.Popen", side_effect=spawn):
                with self.assertRaises(ProcessStopped):
                    run_process([sys.executable, "-c", "import time; time.sleep(30)"], stop_check=stopped.is_set)
            self.assertIsNotNone(children[0].poll())
        finally:
            timer.cancel()

    def test_adb_stop_never_launches_input(self):
        client = AdbClient("test-stop-device")
        client.stop_check = lambda: True
        with patch("coc_bot.runtime.processes.subprocess.Popen") as spawn:
            with self.assertRaises(AdbStopped):
                client.run_shell("input tap 1 1")
            spawn.assert_not_called()

    def test_stop_before_run_is_not_reset(self):
        from coc_bot.bot import DonationBot
        bot = Mock()
        bot.config = load_config()
        bot.config.adb_device = "test-startup-stop"
        bot.should_stop.return_value = True
        DonationBot.run(bot)
        bot._start_recorder.assert_not_called()
        bot._run_inner.assert_not_called()

    def test_device_lease_excludes_second_controller_and_releases(self):
        with DeviceLease("test-exclusive-device"):
            with self.assertRaises(DeviceBusy):
                with DeviceLease("test-exclusive-device"):
                    pass
        with DeviceLease("test-exclusive-device"):
            pass

    def test_capture_is_serialized_and_preview_is_a_copy(self):
        device = "test-capture-device"
        state = [0, 0]
        guard = threading.Lock()
        errors = []
        frame = np.full((12, 12, 3), 77, np.uint8)
        def get_frame():
            with guard:
                state[0] += 1
                state[1] = max(state[1], state[0])
            time.sleep(.03)
            with guard:
                state[0] -= 1
            return frame
        def worker():
            try:
                capture = ScreenCapture(AdbClient(device))
                capture._capture_png_exec_out = get_frame
                capture.screenshot()
            except Exception as exc:
                errors.append(exc)
        threads = [threading.Thread(target=worker) for _ in range(3)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(state[1], 1)
        snapshot, age = latest_frame(device)
        snapshot[:] = 0
        self.assertTrue((latest_frame(device)[0] == 77).all())
        self.assertGreaterEqual(age, 0)

    def test_ocr_exits_on_clear_label_and_reuses_unchanged_crop(self):
        image = np.full((15, 40, 3), 131, np.uint8)
        ocr._LABEL_CACHE.clear()
        with patch.object(ocr.shutil, "which", return_value="tesseract"), patch.object(ocr, "run_process", return_value=Mock(stdout="Donate")) as run:
            self.assertEqual(ocr.read_short_label(image), "donate")
            self.assertEqual(ocr.read_short_label(image.copy()), "donate")
            self.assertEqual(run.call_count, 1)

    def test_ocr_uses_remaining_total_budget(self):
        ocr._LABEL_CACHE.clear()
        now = [0.]
        def process(*args, **kwargs):
            self.assertLessEqual(kwargs["timeout"], 2.)
            now[0] += 1.1
            return Mock(stdout="unclear")
        with patch.object(ocr.shutil, "which", return_value="tesseract"), patch.object(ocr.time, "monotonic", side_effect=lambda: now[0]), patch.object(ocr, "run_process", side_effect=process) as run:
            ocr.read_short_label(np.full((15, 40, 3), 129, np.uint8))
        self.assertEqual(run.call_count, 2)

    def test_missing_elixir_confirmation_blocks_all_taps(self):
        executor = DonationExecutor(load_config(), Mock(), Mock())
        executor.config.tap_points = {}
        self.assertFalse(executor._ensure_elixir_resource())
        executor.input.tap.assert_not_called()

    def test_resource_verification_rejects_changed_selection_and_scales(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config()
            config.templates_dir = Path(tmp)
            config.templates = {"donation_elixir_selected": "selected.png"}
            config.rois = {"donation_elixir_selected": [.1, .1, .2, .2]}
            image = np.full((100, 200, 3), 70, np.uint8)
            image[10:30, 20:60] = [55, 170, 240]
            cv2.imwrite(str(Path(tmp) / "selected.png"), image[10:30, 20:60])
            self.assertTrue(elixir_is_selected(config, image))
            self.assertTrue(elixir_is_selected(config, cv2.resize(image, (400, 200), interpolation=cv2.INTER_NEAREST)))
            image[10:30, 20:60] = [70, 70, 70]
            self.assertFalse(elixir_is_selected(config, image))

    def test_resource_tap_scales_and_requires_fresh_confirmation(self):
        config = load_config()
        config.frame_width, config.frame_height = 200, 100
        config.tap_points = {"donation_elixir_button": [40, 20]}
        config.templates = {"donation_elixir_selected": "selected.png"}
        config.rois = {"donation_elixir_selected": [.1, .1, .2, .2]}
        capture, inputs = Mock(), Mock()
        capture.screenshot.return_value = np.zeros((200, 400, 3), np.uint8)
        executor = DonationExecutor(config, capture, inputs)
        executor.classifier = Mock()
        executor.classifier.is_donation_panel.return_value = True
        with patch("coc_bot.donation.resource_mode.elixir_is_selected", side_effect=[False, True]), patch("coc_bot.donation.executor.interrupted_sleep", return_value=False):
            self.assertTrue(executor._ensure_elixir_resource())
        inputs.tap.assert_called_once_with(80, 40, jitter=0)
        self.assertEqual(capture.screenshot.call_count, 2)

    def test_changed_thin_selection_border_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config()
            config.templates_dir = Path(tmp)
            config.templates = {"donation_elixir_selected": "selected.png"}
            config.rois = {"donation_elixir_selected": [0, 0, 1, 1]}
            image = np.full((100, 100, 3), 70, np.uint8)
            image[:2] = 240
            cv2.imwrite(str(Path(tmp) / "selected.png"), image)
            image[:2] = 70
            self.assertFalse(elixir_is_selected(config, image))

    def test_corrupt_runtime_state_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            for value in ("", "invalid", '[]', '{"active_seconds": null}'):
                path.write_text(value)
                self.assertEqual(load_runtime_state(path).active_seconds, 0)

    def test_paused_farm_clock_resumes_without_countdown_jump(self):
        from coc_bot.runtime.tracker import RuntimeTracker
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config()
            config.data_dir = Path(tmp)
            tracker = RuntimeTracker(config)
            start = datetime(2026, 1, 1, tzinfo=timezone.utc)
            tracker.state.last_farm_at = start.isoformat()
            tracker.state.farm_paused_at = (start + timedelta(seconds=100)).isoformat()
            with patch("coc_bot.runtime.tracker.datetime") as clock:
                clock.fromisoformat = datetime.fromisoformat
                clock.now.return_value = start + timedelta(seconds=500)
                self.assertEqual(tracker.seconds_since_last_farm(), 100)
                tracker.resume_farm_clock()
                self.assertEqual(tracker.seconds_since_last_farm(), 100)


if __name__ == "__main__":
    unittest.main()
