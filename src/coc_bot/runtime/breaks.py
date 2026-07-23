from __future__ import annotations

import random
import time
from datetime import datetime, timedelta, timezone

from loguru import logger

from coc_bot.adb.app import AppController
from coc_bot.config import BotConfig
from coc_bot.donation.navigator import Navigator
from coc_bot.runtime.tracker import RuntimeTracker


class BreakManager:
    """Handle 4-hour session limit with randomized breaks and fast resume."""

    def __init__(
        self,
        config: BotConfig,
        tracker: RuntimeTracker,
        app: AppController,
        navigator: Navigator,
    ) -> None:
        self.config = config
        self.tracker = tracker
        self.app = app
        self.navigator = navigator
        self.stop_check = None

    def check_and_break_if_needed(self) -> bool:
        """Returns True if a break cycle was executed."""
        if self.stop_check and self.stop_check():
            return False
        self.tracker.tick()
        if not self.tracker.limit_reached:
            return False
        self._execute_break_cycle()
        return True

    def resume_pending_break(self) -> bool:
        """Resume an interrupted break after process restart."""
        state = self.tracker.state
        if not state.break_until:
            return False
        until = datetime.fromisoformat(state.break_until)
        now = datetime.now(timezone.utc)
        break_seconds = state.last_break_seconds or self.config.break_min_seconds
        if now >= until:
            logger.info("Pending break already elapsed, relaunching game")
            self._relaunch_and_resume()
            self.tracker.reset_after_break(break_seconds)
            return True
        remaining = (until - now).total_seconds()
        logger.info("Resuming pending break for {:.0f}s", remaining)
        self.tracker.pause()
        from coc_bot.stop import interrupted_sleep

        if interrupted_sleep(remaining, self.stop_check):
            logger.info("Break interrupted by stop — leaving CoC stopped")
            return False
        self._relaunch_and_resume()
        self.tracker.reset_after_break(break_seconds)
        return True

    def _execute_break_cycle(self) -> None:
        break_seconds = random.randint(self.config.break_min_seconds, self.config.break_max_seconds)
        logger.info(
            "Session limit reached ({:.0f}s). Starting break for {}s",
            self.tracker.active_seconds,
            break_seconds,
        )
        self.tracker.pause()
        self.app.force_stop()

        until = datetime.now(timezone.utc) + timedelta(seconds=break_seconds)
        self.tracker.set_break_until(until.isoformat(), break_seconds=break_seconds)
        from coc_bot.stop import interrupted_sleep

        if interrupted_sleep(break_seconds, self.stop_check):
            logger.info("Break interrupted by stop — leaving CoC stopped")
            return

        self._relaunch_and_resume()
        self.tracker.reset_after_break(break_seconds)

    def _relaunch_and_resume(self) -> None:
        loading_template = self.navigator.load_template("loading")
        self.app.launch()
        self.app.wait_until_ready(loading_template=loading_template)
        self.navigator.ensure_clan_chat()
        self.tracker.resume()
