"""Lifecycle regression tests: no Tk, live config, disk writes, or ADB."""

import threading
import unittest
from unittest.mock import patch

from coc_bot.control import BotController, RunOptions, RunState


class FakeBot:
    def __init__(self):
        self.entered = threading.Event()
        self.stopped = threading.Event()
        self.release = threading.Event()
        self.run_calls = 0
        self.stop_calls = 0

    def run(self):
        self.run_calls += 1
        self.entered.set()
        if not self.release.wait(3):
            raise TimeoutError("Test did not release fake worker")

    def request_stop(self):
        self.stop_calls += 1
        self.stopped.set()


class ControllerTests(unittest.TestCase):
    def make_controller(self, factory):
        controller = BotController(factory)
        self.addCleanup(controller.wait, 3)
        self.addCleanup(controller.close)
        return controller

    def test_simultaneous_starts_create_one_worker(self):
        bot = FakeBot()
        controller = self.make_controller(lambda options: bot)
        self.addCleanup(bot.release.set)
        gate = threading.Barrier(9)
        results = []
        def start():
            gate.wait(3)
            results.append(controller.start())
        threads = [threading.Thread(target=start) for _ in range(8)]
        for thread in threads:
            thread.start()
        gate.wait(3)
        for thread in threads:
            thread.join(3)
            self.assertFalse(thread.is_alive())
        self.assertEqual(results.count(True), 1)
        self.assertTrue(bot.entered.wait(3))
        self.assertEqual(bot.run_calls, 1)

    def test_stop_during_construction_never_enters_run(self):
        creating, release_factory = threading.Event(), threading.Event()
        bot = FakeBot()
        def factory(options):
            creating.set()
            if not release_factory.wait(3):
                raise TimeoutError("Factory not released")
            return bot
        controller = self.make_controller(factory)
        self.addCleanup(release_factory.set)
        self.assertTrue(controller.start())
        self.assertTrue(creating.wait(3))
        self.assertTrue(controller.stop())
        self.assertEqual(controller.snapshot().state, RunState.STOPPING)
        self.assertFalse(controller.start())
        release_factory.set()
        self.assertTrue(controller.wait(3))
        self.assertEqual(bot.run_calls, 0)
        self.assertEqual(bot.stop_calls, 1)
        self.assertFalse(controller.snapshot().active)

    def test_stop_returns_without_waiting_and_blocks_start_until_exit(self):
        bot = FakeBot()
        controller = self.make_controller(lambda options: bot)
        self.addCleanup(bot.release.set)
        controller.start()
        self.assertTrue(bot.entered.wait(3))
        controller.stop()
        controller.stop()  # Idempotent request, no repeated engine calls.
        self.assertTrue(bot.stopped.is_set())
        self.assertEqual(bot.stop_calls, 1)
        self.assertFalse(controller.wait(0))
        self.assertTrue(controller.snapshot().active)
        self.assertFalse(controller.start())
        bot.release.set()
        self.assertTrue(controller.wait(3))
        self.assertEqual(controller.snapshot().state, RunState.STOPPED)

    def test_close_while_idle_rejects_all_new_runs(self):
        controller = self.make_controller(lambda options: FakeBot())
        controller.close()
        self.assertFalse(controller.start())
        self.assertTrue(controller.snapshot().closing)
        self.assertFalse(controller.stop())

    def test_close_during_startup_cancels_and_retains_ownership(self):
        creating, release = threading.Event(), threading.Event()
        bot = FakeBot()
        def factory(options):
            creating.set()
            if not release.wait(3):
                raise TimeoutError("Factory not released")
            return bot
        controller = self.make_controller(factory)
        self.addCleanup(release.set)
        controller.start()
        self.assertTrue(creating.wait(3))
        controller.close()
        self.assertTrue(controller.snapshot().active)
        self.assertFalse(controller.start())
        release.set()
        self.assertTrue(controller.wait(3))
        self.assertEqual(bot.run_calls, 0)
        self.assertEqual(bot.stop_calls, 1)
        self.assertFalse(controller.start())

    def test_factory_failure_is_reported_and_can_be_retried(self):
        bot = FakeBot()
        bot.release.set()
        calls = []
        def factory(options):
            calls.append(options)
            if len(calls) == 1:
                raise ValueError("Missing test calibration")
            return bot
        controller = self.make_controller(factory)
        controller.start()
        self.assertTrue(controller.wait(3))
        failed = controller.snapshot()
        self.assertEqual(failed.state, RunState.FAILED)
        self.assertEqual(failed.error, "Missing test calibration")
        self.assertIn("ValueError", failed.error_traceback)
        options = RunOptions(dry_run=True, record=True, record_every=2)
        self.assertTrue(controller.start(options))
        self.assertTrue(controller.wait(3))
        self.assertEqual(calls[-1], options)
        self.assertGreater(controller.snapshot().generation, failed.generation)
        self.assertIsNone(controller.snapshot().error)

    def test_run_failure_clears_engine_reference(self):
        class BrokenBot(FakeBot):
            def run(self):
                raise RuntimeError("Fake device disconnected")
        controller = self.make_controller(lambda options: BrokenBot())
        controller.start()
        self.assertTrue(controller.wait(3))
        self.assertEqual(controller.snapshot().state, RunState.FAILED)
        self.assertIsNone(controller.bot)

    def test_thread_start_failure_does_not_leave_busy_state(self):
        controller = self.make_controller(lambda options: FakeBot())
        with patch("threading.Thread.start", side_effect=RuntimeError("No threads")):
            with self.assertRaisesRegex(RuntimeError, "No threads"):
                controller.start()
        self.assertFalse(controller.snapshot().active)
        self.assertEqual(controller.snapshot().state, RunState.FAILED)


if __name__ == "__main__":
    unittest.main()
