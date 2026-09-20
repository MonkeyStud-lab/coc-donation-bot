from __future__ import annotations

import random
import time
from datetime import datetime, timedelta, timezone

from loguru import logger

from coc_bot.adb.app import AppController
from coc_bot.config import BotConfig
from coc_bot.donation.navigator import Navigator
from coc_bot.runtime.game_state import GameState, GameStateMachine
from coc_bot.runtime.tracker import RuntimeTracker


class BreakManager:
    """Handle session-limit breaks with randomized length and fast resume."""

    def __init__(
        self,
        config: BotConfig,
        tracker: RuntimeTracker,
        app: AppController,
        navigator: Navigator,
        game_state: GameStateMachine | None = None,
    ) -> None:
        self.config = config
        self.tracker = tracker
        self.app = app
        self.navigator = navigator
        self.game_state = game_state
        self.stop_check = None

    def _gs(self, state: GameState, reason: str) -> None:
        if self.game_state is not None:
            self.game_state.transition(state, reason=reason)

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
        try:
            until = datetime.fromisoformat(state.break_until)
        except (TypeError, ValueError):
            logger.warning(
                "Ignoring corrupt break_until {!r} in runtime state", state.break_until
            )
            state.break_until = None
            return False
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        break_seconds = state.last_break_seconds or self._break_range()[0]
        if now >= until:
            logger.info("Pending break already elapsed, relaunching game")
            if not self._relaunch_and_resume():
                return False
            self.tracker.reset_after_break(break_seconds)
            return True
        remaining = (until - now).total_seconds()
        logger.info("Resuming pending break for {:.0f}s", remaining)
        self._gs(GameState.ON_BREAK, "resume pending break")
        self.tracker.pause()
        from coc_bot.stop import interrupted_sleep

        if interrupted_sleep(remaining, self.stop_check):
            logger.info("Break interrupted by stop — leaving CoC stopped")
            return False
        if not self._relaunch_and_resume():
            return False
        self.tracker.reset_after_break(break_seconds)
        return True

    def _break_range(self) -> tuple[int, int]:
        """Sanitised (min, max) break length — tolerates swapped/float YAML values."""
        try:
            lo = int(self.config.break_min_seconds)
        except (TypeError, ValueError):
            lo = 300
        try:
            hi = int(self.config.break_max_seconds)
        except (TypeError, ValueError):
            hi = lo
        lo = max(1, lo)
        hi = max(lo, hi)
        if int(self.config.break_min_seconds or 0) > int(self.config.break_max_seconds or 0):
            logger.warning(
                "break_min_seconds > break_max_seconds in config — using {}..{}s", lo, hi
            )
        return lo, hi

    def _execute_break_cycle(self) -> None:
        lo, hi = self._break_range()
        break_seconds = random.randint(lo, hi)
        logger.info(
            "Session limit reached ({:.0f}s). Starting break for {}s",
            self.tracker.active_seconds,
            break_seconds,
        )
        self._gs(GameState.ON_BREAK, "session limit")
        self.tracker.pause()
        self.app.force_stop()

        until = datetime.now(timezone.utc) + timedelta(seconds=break_seconds)
        self.tracker.set_break_until(until.isoformat(), break_seconds=break_seconds)
        from coc_bot.stop import interrupted_sleep

        if interrupted_sleep(break_seconds, self.stop_check):
            logger.info("Break interrupted by stop — leaving CoC stopped")
            return

        if not self._relaunch_and_resume():
            # Leave the session limit tripped and the tracker paused: the next
            # loop tick re-enters a break cycle (force-stop, wait, relaunch)
            # instead of donating against a game that never loaded.
            logger.error("Break relaunch failed — will retry with another break cycle")
            return
        self.tracker.reset_after_break(break_seconds)

    def _relaunch_and_resume(self, attempts: int = 2) -> bool:
        """
        Relaunch Clash after a break and get back to clan chat.

        Returns False if the game never finished loading (or Stop was pressed);
        callers must NOT resume the donation loop in that case.
        """
        loading_template = self.navigator.load_template("loading")
        for attempt in range(1, attempts + 1):
            if self.stop_check and self.stop_check():
                return False
            self.app.launch()
            if self.app.wait_until_ready(loading_template=loading_template):
                break
            if self.stop_check and self.stop_check():
                return False
            logger.warning(
                "Clash did not load after relaunch (attempt {}/{})", attempt, attempts
            )
            if attempt < attempts:
                self.app.force_stop()
        else:
            logger.error("Giving up: Clash did not load after {} relaunch attempt(s)", attempts)
            return False

        self.navigator.ensure_clan_chat()
        self._gs(GameState.CLAN_CHAT, "break relaunch")
        # Past boot popups / possible Live Replay — stop watching for it.
        from coc_bot.vision.screens import ScreenClassifier

        ScreenClassifier.disarm_live_replay_watch()
        self.tracker.resume()
        return True
