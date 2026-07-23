from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

from coc_bot.adb.capture import ScreenCapture
from coc_bot.adb.input import InputController
from coc_bot.attack.deployer import EdgeDeployer
from coc_bot.attack.navigator import AttackNavigator
from coc_bot.config import BotConfig
from coc_bot.donation.navigator import Navigator
from coc_bot.vision.matcher import TemplateMatcher
from coc_bot.vision.screens import ScreenType


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

    def run_one_attack(self) -> FarmResult:
        if not self.config.farm_calibrated:
            return FarmResult(False, "farm not calibrated (need attack_button, unranked_battle, return_home)")

        logger.info(
            "Starting farm attack (deploy_side={}, unranked Battle)",
            self.config.farm_deploy_side,
        )

        if not self.attack_nav.leave_chat_for_home():
            self._abort_to_chat()
            return FarmResult(False, "could not reach home")

        if self.donation_nav is not None:
            frame = self.capture.screenshot()
            if self.attack_nav.classifier.looks_like_blocking_popup(frame):
                self.donation_nav._dismiss_popup(frame)  # noqa: SLF001

        if not self.attack_nav.open_attack_menu():
            self._abort_to_chat()
            return FarmResult(False, "could not open Attack menu")

        if not self.attack_nav.start_unranked_battle():
            self._abort_to_chat()
            return FarmResult(False, "could not start unranked Battle")

        if not self.attack_nav.wait_for_battle():
            self.attack_nav.return_home_from_attack()
            self._abort_to_chat()
            return FarmResult(False, "matchmaking timeout")

        frame = self.capture.screenshot()
        logger.info(
            "Deploying army (pan_swipes={}, e-drag taps={}, heroes={}) along {}",
            self.config.farm_pan_swipes,
            self.config.farm_edrag_deploy_taps,
            self.config.farm_hero_count,
            self.config.farm_deploy_side,
        )
        self.deployer.dump_army_along_edge(frame)

        end_screen = self.attack_nav.wait_for_battle_end()
        if end_screen == ScreenType.BATTLE:
            logger.warning("Still in battle after timeout — trying return home")
            self.attack_nav.return_home_from_attack()
            self._abort_to_chat()
            return FarmResult(False, "battle timeout")

        if end_screen == ScreenType.BATTLE_RESULTS:
            self.attack_nav.return_home_from_attack()
        elif end_screen not in (ScreenType.HOME, ScreenType.CLAN_CHAT):
            self.attack_nav.return_home_from_attack()

        if self.donation_nav is not None:
            ok = self.donation_nav.ensure_clan_chat()
            if not ok:
                return FarmResult(False, "attack finished but could not reopen clan chat")

        logger.info("Farm attack completed successfully")
        return FarmResult(True, "ok")

    def _abort_to_chat(self) -> None:
        try:
            self.attack_nav.return_home_from_attack()
        except Exception:  # noqa: BLE001
            logger.exception("return_home during farm abort failed")
        if self.donation_nav is not None:
            try:
                self.donation_nav.ensure_clan_chat()
            except Exception:  # noqa: BLE001
                logger.exception("ensure_clan_chat during farm abort failed")
