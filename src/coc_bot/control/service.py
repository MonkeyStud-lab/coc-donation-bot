"""Interface-independent command ownership and structured status.

No interface can begin a second operation while a worker or manual editor owns
the device. Stop goes straight to the current cancellation event.
"""
from dataclasses import asdict
from contextlib import contextmanager
import threading
from coc_bot.control.lifecycle import BotController, RunOptions
from coc_bot.control.events import EventHistory


class BusyError(RuntimeError):
    pass


class JobRunner:
    def __init__(self, function, finished):
        self.cancel = threading.Event()
        self.function, self.finished = function, finished

    def request_stop(self):
        self.cancel.set()

    def run(self):
        result = self.function(self.cancel)
        self.finished(result)


class ControlService:
    def __init__(self, controller=None, session_factory=None):
        self.controller = controller or BotController()
        self.events = EventHistory()
        self.lock = threading.RLock()
        self.operation = None
        self.result = None
        self.manual_owner = None
        self.manual_cancel = None
        self.session_factory = session_factory
        self._timer_snapshot = {"farm_seconds": None, "break_seconds": None}
        self._finished_generation = -1
        self._break_active = False
        self.peers = []

    def saved_timers(self):
        """Read frozen persisted clocks without rerolling or rewriting anything."""
        from datetime import datetime, timezone
        from coc_bot.config import load_config
        from coc_bot.runtime.persistence import load_runtime_state
        config = load_config()
        state = load_runtime_state(config.data_dir / "runtime_state.json")
        farm = None
        if config.farm_enabled and state.last_farm_at:
            try:
                last = datetime.fromisoformat(state.last_farm_at)
                paused = datetime.fromisoformat(state.farm_paused_at) if state.farm_paused_at else last
                farm = max(0, (state.next_farm_interval_seconds or config.farm_interval_seconds)
                           - (paused-last).total_seconds())
            except (TypeError, ValueError):
                pass
        self._timer_snapshot = {"farm_seconds": farm,
            "break_seconds": max(0, (state.next_session_limit_seconds or config.session_limit_seconds)
                                 - state.active_seconds)}
        self._break_active = False
        if state.break_until:
            try:
                until = datetime.fromisoformat(state.break_until)
                if until.tzinfo is None:
                    until = until.replace(tzinfo=timezone.utc)
                remaining = max(0, (until-datetime.now(timezone.utc)).total_seconds())
                if remaining:
                    self._timer_snapshot["break_seconds"] = remaining
                    self._break_active = True
            except ValueError:
                pass

    def idle(self):
        if any(s.controller.snapshot().active or s.manual_owner for s in [self, *self.peers]):
            raise BusyError("Stop the bot and finish the current tool first.")

    def start(self, practice=False):
        with self.lock:
            self.idle()
            from coc_bot.config import load_config
            config = load_config()
            if not config.calibrated:
                raise ValueError("Finish the required Setup parts first.")
            self.operation, self.result = "bot", None
            if not self.controller.start(RunOptions(dry_run=practice)):
                raise BusyError("Bot is stopping. Try again when it has stopped.")
            self.events.append("INFO", "Bot starting")

    def stop(self):
        self.controller.stop()
        if self.manual_cancel is not None:
            self.manual_cancel.set()
        self.events.append("INFO", "Stop requested")

    def job(self, name, function):
        with self.lock:
            self.idle()
            self.operation, self.result = name, None
            def finished(result):
                with self.lock:
                    self.result = result
                self.events.append("INFO", name + " completed" if isinstance(result, dict) else str(result))
            if not self.controller.start_job(lambda _: JobRunner(function, finished)):
                raise BusyError("Another job is running")
            self.events.append("INFO", name + " started")

    def session(self, cancel):
        if self.session_factory:
            session = self.session_factory()
        else:
            from coc_bot.control.diagnostics import DebugSession
            session = DebugSession()
        for obj in (session.client, session.input, session.navigator,
                    session.attack_nav, session.deployer, session.app):
            obj.stop_check = cancel.is_set
        return session

    def farm(self):
        with self.lock:
            if self.controller.snapshot().active and self.operation == "bot":
                bot = self.controller.bot
                if bot is None or self.controller.snapshot().stop_requested:
                    raise BusyError("Wait for startup or stopping to finish")
                bot.request_farm_attack()
                return "Farm queued"
            self.job("farm", lambda cancel: self.session(cancel).farm_one_shot(cancel.is_set))
            return "Farm started"

    def diagnostic(self, action):
        # Explicit allowlist: never accept module names, paths or shell commands.
        actions = {
            "health_check": "health_check", "classify_screen": "classify_screen",
            "open_clan_chat": "open_clan_chat", "find_classify_request": "find_and_classify_request",
            "open_donation": "open_donation_panel", "close_donation": "close_donation_panel",
            "scroll_chat": "scroll_chat_step", "anti_idle": "anti_idle_nudge",
            "save_screenshot": "save_screenshot", "force_stop": "force_stop_coc",
            "relaunch": "relaunch_coc", "break_cycle": "break_cycle_short",
            "farm_open_attack": "farm_open_attack_menu", "farm_start_search": "farm_start_unranked_search",
            "farm_classify": "farm_classify_battle", "farm_deploy_dry": "farm_deploy_dry_taps",
            "farm_clear_deploy": "farm_clear_deploy_sequence",
            "close_waydroid": "close_waydroid",
        }
        if action not in actions:
            raise ValueError("Unknown diagnostic action")
        def execute(cancel):
            from coc_bot.runtime.device_lease import DeviceLease
            session = self.session(cancel)
            with DeviceLease(session.config.adb_device):
                return getattr(session, actions[action])()
        self.job(action, execute)

    def snapshot(self):
        with self.lock:
            activity = None
            state = asdict(self.controller.snapshot())
            state.pop("error_traceback", None)
            if not state["active"]:
                if self._finished_generation != state["generation"]:
                    self.saved_timers()
                    self._finished_generation = state["generation"]
                    if state["error"]:
                        self.events.append("ERROR", state["error"])
                elif self._break_active:
                    self.saved_timers()
            bot = self.controller.bot
            if self.operation == "bot" and bot is not None and state["active"]:
                phase = getattr(getattr(getattr(bot, "game_state", None), "state", None), "value", None)
                activity = {"boot": "Starting", "home": "At home", "clan_chat": "Watching clan chat",
                    "scrolling_chat": "Checking requests", "opening_donation": "Opening donation",
                    "donating": "Donating", "attack_menu": "Opening attack", "matchmaking": "Finding opponent",
                    "in_battle": "In battle", "battle_results": "Leaving battle", "returning_home": "Returning home",
                    "recovering": "Recovering", "on_break": "On break"}.get(phase)
                tracker = getattr(bot, "tracker", None)
                if tracker is not None:
                    since = tracker.seconds_since_last_farm()
                    self._timer_snapshot = {
                        "farm_seconds": max(0, tracker.effective_farm_interval_seconds() - since)
                        if since is not None and bot.config.farm_enabled else None,
                        "break_seconds": max(0, tracker.peek_remaining_seconds()),
                    }
                    self._break_active = False
                    until_text = getattr(getattr(tracker, "state", None), "break_until", None)
                    if until_text:
                        from datetime import datetime, timezone
                        try:
                            until = datetime.fromisoformat(until_text)
                            if until.tzinfo is None:
                                until = until.replace(tzinfo=timezone.utc)
                            remaining = (until-datetime.now(timezone.utc)).total_seconds()
                            if remaining > 0:
                                self._break_active = True
                                self._timer_snapshot["break_seconds"] = remaining
                        except ValueError:
                            pass
            return state | {"operation": self.operation, "result": self.result,
                            "timers": dict(self._timer_snapshot),
                            "manual_control": self.manual_owner is not None,
                            "activity": activity,
                            "on_break": self._break_active}

    def close(self):
        self.stop()
        self.controller.close()
        return self.controller.wait(30) and self.manual_owner is None

    @contextmanager
    def mutation(self):
        """Also exclude a desktop bot running in a different process."""
        from coc_bot.config import load_config
        from coc_bot.runtime.device_lease import DeviceLease
        with self.lock:
            self.idle()
            with DeviceLease(load_config().adb_device):
                yield
