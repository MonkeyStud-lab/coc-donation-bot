from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from loguru import logger

from coc_bot.adb.capture import ScreenCapture
from coc_bot.adb.input import InputController
from coc_bot.attack.deployer import EdgeDeployer
from coc_bot.attack.navigator import AttackNavigator
from coc_bot.config import BotConfig
from coc_bot.donation.navigator import Navigator
from coc_bot.runtime.game_state import GameState, GameStateMachine
from coc_bot.vision.matcher import TemplateMatcher
from coc_bot.vision.screens import BotMode, ScreenType


@dataclass(frozen=True)
class FarmResult:
    success: bool
    reason: str
    # True once troops were deployed — advances the auto-farm interval clock even
    # if leave/chat confirm fails (otherwise failures retry every fail-cooldown).
    counts_toward_interval: bool = False


class AttackFarmer:
    """Orchestrate one unranked e-drag side-dump attack."""

    def __init__(
        self,
        config: BotConfig,
        capture: ScreenCapture,
        input_ctrl: InputController,
        matcher: TemplateMatcher | None = None,
        donation_navigator: Navigator | None = None,
        game_state: GameStateMachine | None = None,
    ) -> None:
        self.config = config
        self.capture = capture
        self.input = input_ctrl
        self.matcher = matcher or TemplateMatcher(threshold=config.template_threshold)
        self.donation_nav = donation_navigator
        self.game_state = game_state
        self.attack_nav = AttackNavigator(
            config, capture, input_ctrl, self.matcher, donation_navigator
        )
        self.deployer = EdgeDeployer(config, input_ctrl)
        self.stop_check: Callable[[], bool] | None = None
        self._on_mode: Callable[[BotMode], None] | None = None

    def _stopping(self) -> bool:
        return bool(self.stop_check and self.stop_check())

    def _gs(self, state: GameState, reason: str) -> None:
        if self.game_state is not None:
            self.game_state.transition(state, reason=reason)

    def _set_mode(self, mode: BotMode) -> None:
        self.attack_nav.mode = mode
        if self.donation_nav is not None:
            self.donation_nav.mode = mode
        if self._on_mode is not None:
            self._on_mode(mode)

    def run_one_attack(self) -> FarmResult:
        if not self.config.farm_calibrated:
            return FarmResult(False, "farm not calibrated (need attack_button, unranked_battle, return_home)")

        logger.info(
            "Starting farm attack (deploy_side={}, unranked Battle)",
            self.config.farm_deploy_side,
        )

        if self._stopping():
            return FarmResult(False, "stopped")

        # Leave chat with full classify, then lock to attack screens.
        self._set_mode(BotMode.HOME)
        self._gs(GameState.HOME, "leave chat for farm")
        if not self.attack_nav.leave_chat_for_home():
            if self._stopping():
                return FarmResult(False, "stopped")
            self._abort_to_chat()
            return FarmResult(False, "could not reach home")

        if self._stopping():
            return FarmResult(False, "stopped")

        self._set_mode(BotMode.ATTACK)

        if self.donation_nav is not None:
            frame = self.capture.screenshot()
            if self.attack_nav.classifier.looks_like_blocking_popup(frame):
                self.donation_nav._dismiss_popup(frame)  # noqa: SLF001

        self._gs(GameState.ATTACK_MENU, "open Attack menu")
        if not self.attack_nav.open_attack_menu():
            if self._stopping():
                return FarmResult(False, "stopped")
            self._abort_to_chat()
            return FarmResult(False, "could not open Attack menu")

        if self._stopping():
            return FarmResult(False, "stopped")

        self._gs(GameState.MATCHMAKING, "start unranked Battle")
        if not self.attack_nav.start_unranked_battle():
            if self._stopping():
                return FarmResult(False, "stopped")
            self._abort_to_chat()
            return FarmResult(False, "could not start unranked Battle")

        if self._stopping():
            return FarmResult(False, "stopped")

        if not self.attack_nav.wait_for_battle():
            if self._stopping():
                return FarmResult(False, "stopped")
            frame = self.capture.screenshot()
            # Opponent may already be loaded even if wait_for_battle mis-timed.
            if (
                self.attack_nav.classify(frame, mode=BotMode.ATTACK) == ScreenType.BATTLE
                or self.attack_nav.classifier._looks_like_battle(frame)  # noqa: SLF001
            ):
                logger.warning(
                    "wait_for_battle returned false but battle is on screen — deploying anyway"
                )
            else:
                logger.warning("Did not reach battle field — aborting without deploy")
                self._gs(GameState.RETURNING_HOME, "matchmaking timeout")
                self.attack_nav.return_home_from_attack()
                self._abort_to_chat()
                return FarmResult(False, "matchmaking timeout")

        self._gs(GameState.IN_BATTLE, "battlefield ready")
        if self._stopping():
            return FarmResult(False, "stopped")

        frame = self.capture.screenshot()
        logger.info(
            "Opponent ready — deploying (pan_swipes={}, e-drag taps={}, heroes={}) along {}",
            self.config.farm_pan_swipes,
            self.config.farm_edrag_deploy_taps,
            self.config.farm_hero_count,
            self.config.farm_deploy_side,
        )
        # Timer starts when the first troop goes down (beginning of dump).
        deploy_started = time.time()
        taps = self.deployer.dump_army_along_edge(frame)
        logger.info("Deploy finished — {} map taps", taps)
        # From here on, this attempt counts toward the farm interval clock.

        if self._stopping():
            return FarmResult(False, "stopped", counts_toward_interval=True)

        # Wait remaining of the fixed battle window, tap Return Home coords, then
        # confirm village with existing Attack!/chat leave rules.
        end_screen = self.attack_nav.wait_for_battle_end(since=deploy_started)
        if self._stopping() or end_screen == ScreenType.UNKNOWN:
            return FarmResult(False, "stopped", counts_toward_interval=True)

        self._gs(GameState.BATTLE_RESULTS, "battle timer done")
        logger.info("Confirming leave after battle timer (screen={})", end_screen.value)
        self._gs(GameState.RETURNING_HOME, "tap Return Home")
        if not self.attack_nav.return_home_from_attack():
            if self._stopping():
                return FarmResult(False, "stopped", counts_toward_interval=True)
            self._abort_to_chat()
            return FarmResult(
                False,
                "could not confirm home after Return Home tap",
                counts_toward_interval=True,
            )

        self._gs(GameState.HOME, "home confirmed after farm")
        if self._stopping():
            return FarmResult(False, "stopped", counts_toward_interval=True)

        # Star Bonus / news modals after Return Home — corner-tap dismiss.
        if self.donation_nav is not None:
            frame = self.capture.screenshot()
            if self.attack_nav.classifier.looks_like_blocking_popup(frame):
                logger.info("Dismissing post-farm popup before reopening chat")
                self.donation_nav._dismiss_popup(frame)  # noqa: SLF001
                time.sleep(0.9)

        self._set_mode(BotMode.DONATE)
        if self.donation_nav is not None:
            ok = self.donation_nav.ensure_clan_chat()
            if self._stopping():
                return FarmResult(False, "stopped", counts_toward_interval=True)
            if not ok:
                return FarmResult(
                    False,
                    "attack finished but could not reopen clan chat",
                    counts_toward_interval=True,
                )

        self._gs(GameState.CLAN_CHAT, "farm success — chat open")
        logger.info("Farm attack completed successfully")
        return FarmResult(True, "ok", counts_toward_interval=True)

    def _abort_to_chat(self) -> None:
        if self._stopping():
            return
        self._gs(GameState.RECOVERING, "farm abort")
        try:
            self.attack_nav.return_home_from_attack()
        except Exception:  # noqa: BLE001
            logger.exception("return_home during farm abort failed")
        self._set_mode(BotMode.DONATE)
        if self.donation_nav is not None and not self._stopping():
            try:
                self.donation_nav.ensure_clan_chat()
            except Exception:  # noqa: BLE001
                logger.exception("ensure_clan_chat during farm abort failed")
        self._gs(GameState.CLAN_CHAT, "farm abort — chat open")
