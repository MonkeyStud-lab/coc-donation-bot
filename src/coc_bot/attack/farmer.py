from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from loguru import logger

from coc_bot.adb.capture import ScreenCapture
from coc_bot.adb.input import InputController
from coc_bot.attack.deployer import EdgeDeployer
from coc_bot.attack.navigator import AttackNavigator
from coc_bot.config import BotConfig
from coc_bot.donation.navigator import Navigator
from coc_bot.vision.matcher import TemplateMatcher
from coc_bot.vision.screens import BotMode, ScreenType


@dataclass(frozen=True)
class FarmResult:
    success: bool
    reason: str


class AttackFarmer:
    """Orchestrate one unranked e-drag side-dump attack."""

    def __init__(
        self,
        config: BotConfig,
        capture: ScreenCapture,
        input_ctrl: InputController,
        matcher: TemplateMatcher | None = None,
        donation_navigator: Navigator | None = None,
    ) -> None:
        self.config = config
        self.capture = capture
        self.input = input_ctrl
        self.matcher = matcher or TemplateMatcher(threshold=config.template_threshold)
        self.donation_nav = donation_navigator
        self.attack_nav = AttackNavigator(
            config, capture, input_ctrl, self.matcher, donation_navigator
        )
        self.deployer = EdgeDeployer(config, input_ctrl)
        self.stop_check: Callable[[], bool] | None = None
        self._on_mode: Callable[[BotMode], None] | None = None

    def _stopping(self) -> bool:
        return bool(self.stop_check and self.stop_check())

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

        if not self.attack_nav.open_attack_menu():
            if self._stopping():
                return FarmResult(False, "stopped")
            self._abort_to_chat()
            return FarmResult(False, "could not open Attack menu")

        if self._stopping():
            return FarmResult(False, "stopped")

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
                self.attack_nav.return_home_from_attack()
                self._abort_to_chat()
                return FarmResult(False, "matchmaking timeout")

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
        taps = self.deployer.dump_army_along_edge(frame)
        logger.info("Deploy finished — {} map taps", taps)

        if self._stopping():
            return FarmResult(False, "stopped")

        end_screen = self.attack_nav.wait_for_battle_end()
        if self._stopping() or end_screen == ScreenType.UNKNOWN:
            return FarmResult(False, "stopped")
        if end_screen == ScreenType.BATTLE:
            logger.warning("Still in battle after timeout — trying return home")
            self.attack_nav.return_home_from_attack()
            self._abort_to_chat()
            return FarmResult(False, "battle timeout")

        # Always try Return Home after an attack unless already on home/chat.
        if end_screen not in (ScreenType.HOME, ScreenType.CLAN_CHAT):
            logger.info("Leaving results screen (end_screen={})", end_screen.value)
            self.attack_nav.return_home_from_attack()

        if self._stopping():
            return FarmResult(False, "stopped")

        self._set_mode(BotMode.DONATE)
        if self.donation_nav is not None:
            ok = self.donation_nav.ensure_clan_chat()
            if self._stopping():
                return FarmResult(False, "stopped")
            if not ok:
                return FarmResult(False, "attack finished but could not reopen clan chat")

        logger.info("Farm attack completed successfully")
        return FarmResult(True, "ok")

    def _abort_to_chat(self) -> None:
        if self._stopping():
            return
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
