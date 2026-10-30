"""Settings changes must not interrupt an attack or bypass priority Stop."""
import shutil
import tempfile
import threading
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from coc_bot.config import project_root, load_config, load_user_settings, save_user_settings
from coc_bot.control.lifecycle import BotController, RunOptions
from coc_bot.control.service import ControlService, BusyError
from coc_bot.control.settings import revision, save_settings, RevisionConflict, settings_snapshot


class ActionBot:
    def __init__(self):
        self.entered = threading.Event()
        self.finish_requested = threading.Event()
        self.release = threading.Event()
        self.hard_stopped = False

    def run(self):
        self.entered.set()
        if not self.release.wait(5):
            raise RuntimeError("Fake action timed out")

    def request_stop_after_action(self):
        self.finish_requested.set()

    def request_stop(self):
        self.hard_stopped = True
        self.release.set()


class SettingsRestartTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        home = Path(self.temp.name)
        shutil.copytree(project_root() / "config", home / "config")
        env = patch.dict("os.environ", {"COC_BOT_HOME": str(home),
                         "COC_BOT_CONFIG": str(home / "data/calibrated.yaml")})
        env.start()
        self.addCleanup(env.stop)
        lease = patch("coc_bot.runtime.device_lease.DeviceLease")
        lease.start()
        self.addCleanup(lease.stop)
        self.bots, self.options = [], []
        def factory(options):
            self.options.append(options)
            bot = ActionBot()
            self.bots.append(bot)
            return bot
        self.service = ControlService(BotController(factory))
        self.addCleanup(self.service.close)

    def start(self):
        self.service.operation = "bot"
        options = RunOptions(dry_run=True, debug=True, record=True, record_every=2)
        self.service.controller.start(options)
        # Wait for publication without sleeping or touching a real device.
        while not self.bots:
            threading.Event().wait(.001)
        self.assertTrue(self.bots[0].entered.wait(2))

    def save_in_background(self):
        self.results = []
        expected = revision()
        def save():
            try:
                self.results.append(self.service.apply_settings({"farm_resource_start_percent": 80}, expected))
            except Exception as exc:
                self.results.append(exc)
        thread = threading.Thread(target=save)
        thread.start()
        self.addCleanup(thread.join, 3)
        self.assertTrue(self.bots[0].finish_requested.wait(2))
        return thread

    def test_running_save_waits_then_restarts_with_same_options(self):
        self.start()
        thread = self.save_in_background()
        self.assertNotEqual(load_config().farm_resource_start_percent, 80)
        self.assertFalse(self.bots[0].hard_stopped)
        with self.assertRaises(BusyError):
            self.service.idle()
        with self.assertRaises(BusyError):
            self.service.farm()
        with self.assertRaises(BusyError):
            self.service.apply_settings({}, revision())
        self.bots[0].release.set()
        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertTrue(self.results[0]["restarted"])
        self.assertEqual(load_config().farm_resource_start_percent, 80)
        self.assertEqual(self.options, [self.options[0]] * 2)
        self.assertIsNone(self.service.settings_update)

    def test_interface_save_preserves_running_action_and_operational_yaml(self):
        # A named preset must not silently rewrite custom timings on a theme save.
        original = {"gui": {"timing_preset": "balanced", "extension": "keep"},
                    "timing": {"tap_jitter_px": 3, "action_delay_ms": [121, 199]},
                    "extension": {"private": "untouched"}}
        save_user_settings(original)
        self.start()
        state = self.service.controller.snapshot()
        values = settings_snapshot()["values"]
        values["gui_theme"] = "Ember"
        values["gui_dev_options"] = True
        values["gui_show_debug_activity"] = True
        values["farm_resource_start_percent"] = str(values["farm_resource_start_percent"])
        with patch("coc_bot.runtime.device_lease.DeviceLease") as leases:
            result = self.service.apply_settings(values, revision())
        # File-transaction locks remain required; no Android device lease is acquired.
        self.assertTrue(all(call.args[0].startswith("calibration:") for call in leases.call_args_list))
        self.assertFalse(result["restarted"])
        self.assertEqual(self.service.controller.snapshot().generation, state.generation)
        self.assertTrue(self.service.controller.snapshot().active)
        self.assertEqual(len(self.bots), 1)
        self.assertFalse(self.bots[0].finish_requested.is_set())
        self.assertFalse(self.bots[0].hard_stopped)
        saved = load_user_settings()
        self.assertEqual(saved["timing"], original["timing"])
        self.assertEqual(saved["extension"], original["extension"])
        self.assertEqual(saved["gui"], original["gui"] | {
            "theme": "ember", "dev_options": True, "show_debug_activity": True})

    def test_interface_revision_and_validation_fail_without_stopping(self):
        self.start()
        stale = revision()
        self.service.apply_settings({"gui_theme": "Ember"}, stale)
        with self.assertRaises(RevisionConflict):
            self.service.apply_settings({"gui_theme": "Classic"}, stale)
        with self.assertRaises(ValueError):
            self.service.apply_settings({"gui_theme": "missing"}, revision())
        self.assertFalse(self.bots[0].finish_requested.is_set())

    def test_only_interface_preferences_are_live(self):
        fields = {f["key"]: f["restart_required"] for f in settings_snapshot()["fields"]}
        self.assertEqual({key for key, required in fields.items() if not required},
                         {"gui_theme", "gui_show_debug_activity", "gui_dev_options"})
        self.assertTrue(fields["gui_timing_preset"])

    def test_mixed_theme_and_behavior_changes_still_wait_for_safe_restart(self):
        self.start()
        results = []
        thread = threading.Thread(target=lambda: results.append(self.service.apply_settings(
            {"gui_theme": "Ember", "farm_resource_start_percent": 80}, revision())))
        thread.start()
        self.addCleanup(thread.join, 3)
        self.assertTrue(self.bots[0].finish_requested.wait(2))
        self.assertNotEqual(load_config().gui_theme, "ember")
        with self.assertRaises(BusyError):
            self.service.apply_settings({"gui_theme": "Classic"}, revision())
        self.bots[0].release.set()
        thread.join(3)
        self.assertTrue(results[0]["restarted"])
        self.assertEqual(load_config().gui_theme, "ember")

    def test_stop_cancels_save_and_restart(self):
        self.start()
        thread = self.save_in_background()
        self.service.stop()
        thread.join(3)
        self.assertIsInstance(self.results[0], BusyError)
        self.assertNotEqual(load_config().farm_resource_start_percent, 80)
        self.assertEqual(len(self.options), 1)
        self.assertTrue(self.service.controller.wait(2))

    def test_validation_happens_before_graceful_stop(self):
        self.start()
        for values in ({"farm_resource_target_percent": 86401}, {"collection_daily_limit": 0},
                       {"farm_resource_start_percent": -1}):
            with self.assertRaises(ValueError):
                self.service.apply_settings(values, revision())
        self.assertFalse(self.bots[0].finish_requested.is_set())
        self.assertTrue(self.service.controller.snapshot().active)

    def test_revision_change_while_waiting_leaves_bot_stopped(self):
        self.start()
        thread = self.save_in_background()
        save_settings({"farm_resource_start_percent": 85}, revision())
        self.bots[0].release.set()
        thread.join(3)
        self.assertIsInstance(self.results[0], RevisionConflict)
        self.assertEqual(load_config().farm_resource_start_percent, 85)
        self.assertEqual(len(self.options), 1)
        self.assertFalse(self.service.controller.snapshot().active)

    def test_stopped_save_does_not_start_and_manual_control_rejects_save(self):
        result = self.service.apply_settings({"farm_resource_start_percent": 80}, revision())
        self.assertFalse(result["restarted"])
        self.assertEqual(self.options, [])
        self.service.manual_owner = "viewer"
        try:
            with self.assertRaises(BusyError):
                self.service.apply_settings({}, revision())
        finally:
            self.service.manual_owner = None

    def test_write_failure_does_not_restart(self):
        self.start()
        with patch("coc_bot.control.settings.save_settings", side_effect=OSError("Disk full")):
            thread = self.save_in_background()
            self.bots[0].release.set()
            thread.join(3)
        self.assertIsInstance(self.results[0], OSError)
        self.assertEqual(len(self.options), 1)
        self.assertFalse(self.service.controller.snapshot().active)
        self.assertIsNone(self.service.settings_update)

    def test_stop_after_worker_exits_still_cancels_restart(self):
        self.start()
        exited, proceed = threading.Event(), threading.Event()
        original_wait = self.service.controller.wait
        def wait(timeout):
            result = original_wait(timeout)
            if result:
                exited.set()
                proceed.wait(3)
            return result
        with patch.object(self.service.controller, "wait", side_effect=wait):
            thread = self.save_in_background()
            self.bots[0].release.set()
            self.assertTrue(exited.wait(2))
            self.service.stop()
            proceed.set()
            thread.join(3)
        self.assertIsInstance(self.results[0], BusyError)
        self.assertEqual(len(self.options), 1)

    def test_bot_only_stops_between_donation_and_attack_actions(self):
        from coc_bot.bot import DonationBot
        bot = DonationBot.__new__(DonationBot)
        bot.request_stop_after_action()
        for state in ("open_donation", "donate", "farm"):
            bot._state = state
            self.assertFalse(bot._settings_stop_ready())
        for state in ("scan_chat", "scroll_chat"):
            bot._state = state
            self.assertTrue(bot._settings_stop_ready())

    def test_graceful_request_during_startup_is_remembered(self):
        created, release = threading.Event(), threading.Event()
        bot = ActionBot()
        def factory(options):
            created.set()
            release.wait(3)
            return bot
        controller = BotController(factory)
        self.addCleanup(controller.wait, 3)
        self.addCleanup(controller.close)
        self.addCleanup(release.set)
        controller.start()
        self.assertTrue(created.wait(2))
        controller.stop_after_action()
        release.set()
        self.assertTrue(bot.entered.wait(2))
        self.assertTrue(bot.finish_requested.is_set())
        self.assertFalse(bot.hard_stopped)
