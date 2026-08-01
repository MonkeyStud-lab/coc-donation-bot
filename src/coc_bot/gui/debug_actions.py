"""One-shot debug actions for the GUI Debugging tab."""

from __future__ import annotations

import random
import time
from datetime import datetime

from loguru import logger

from coc_bot.adb.app import AppController
from coc_bot.adb.capture import ScreenCapture
from coc_bot.adb.client import AdbClient, AdbError
from coc_bot.adb.input import InputController
from coc_bot.attack.deployer import EdgeDeployer
from coc_bot.attack.navigator import AttackNavigator
from coc_bot.config import load_config
from coc_bot.donation.chat_monitor import ChatMonitor
from coc_bot.donation.navigator import Navigator
from coc_bot.vision.matcher import TemplateMatcher
from coc_bot.vision.rois import ROI, roi_center
from coc_bot.vision.screens import ScreenClassifier


class DebugSession:
    """Shared ADB/vision helpers for manual step tests."""

    def __init__(self) -> None:
        self.config = load_config()
        self.client = AdbClient(device=self.config.adb_device)
        self.capture = ScreenCapture(self.client)
        self.input = InputController(
            self.client,
            jitter_px=self.config.tap_jitter_px,
            delay_ms=self.config.action_delay_ms,
            dry_run=False,
        )
        self.capture.bind_input(self.input)
        self.matcher = TemplateMatcher(
            threshold=self.config.template_threshold,
            scale_range=self.config.scale_range,
        )
        self.classifier = ScreenClassifier(self.config, self.matcher)
        self.navigator = Navigator(self.config, self.capture, self.input, self.matcher)
        self.attack_nav = AttackNavigator(
            self.config, self.capture, self.input, self.matcher, self.navigator
        )
        self.deployer = EdgeDeployer(self.config, self.input)
        self.chat_monitor = ChatMonitor(
            self.config, self.capture, self.input, self.matcher, debug=True
        )
        self.app = AppController(self.client, self.config, self.capture)

    def health_check(self) -> str:
        self.client.health_check()
        return f"ADB OK — device {self.config.adb_device}"

    def classify_screen(self) -> str:
        frame = self.capture.screenshot()
        screen = self.classifier.classify(frame)
        return f"Current screen: {screen.value}"

    def open_clan_chat(self) -> str:
        ok = self.navigator.ensure_clan_chat(
            has_donate_request=lambda f: self.chat_monitor.find_donate_request(f) is not None
        )
        if ok:
            return "Clan chat is open (or was already open)."
        return "Failed to open clan chat — check calibration / that CoC is visible."

    def find_and_classify_request(self) -> str:
        frame = self.capture.screenshot()
        request = self.chat_monitor.find_donate_request(frame)
        if request is None:
            return "No Donate request found on the current screen."
        return (
            f"Found request: kind={request.kind.value}, "
            f"is_specific={request.is_specific}, "
            f"button={request.button_match.center}, "
            f"conf={request.button_match.confidence:.2f}"
        )

    def open_donation_panel(self) -> str:
        frame = self.capture.screenshot()
        request = self.chat_monitor.find_donate_request(frame)
        if request is None:
            return "No Donate button found — open clan chat and ensure a request is visible."
        self.chat_monitor.open_donation(request)
        ok = self.classifier.wait_for_donation_panel(
            self.capture, timeout_seconds=self.config.donation_panel_wait_seconds
        )
        if ok:
            return (
                f"Opened donation panel for kind={request.kind.value} "
                f"(specific={request.is_specific})."
            )
        return "Tapped Donate but donation panel was not detected."

    def close_donation_panel(self) -> str:
        self.navigator.close_donation_panel()
        time.sleep(0.4)
        screen = self.classifier.classify(self.capture.screenshot())
        return f"Close donation attempted — screen now: {screen.value}"

    def scroll_chat_step(self) -> str:
        frame = self.capture.screenshot()
        self.navigator.seek_donation_requests_step(
            frame,
            has_donate_request=lambda f: self.chat_monitor.find_donate_request(f) is not None,
        )
        return "Performed one chat seek/scroll step."

    def anti_idle_nudge(self) -> str:
        frame = self.capture.screenshot()
        h, w = frame.shape[:2]
        if "chat_panel" in self.config.rois:
            cx, cy = roi_center(ROI(*self.config.rois["chat_panel"]), w, h)
        else:
            cx, cy = int(w * 0.32), int(h * 0.55)
        dist = random.randint(45, 90)
        self.input.swipe(cx, cy + dist // 2, cx, cy - dist // 2, duration_ms=200)
        time.sleep(0.12)
        self.input.swipe(cx, cy - dist // 2, cx, cy + dist // 2, duration_ms=200)
        return f"Anti-idle nudge at ({cx}, {cy})."

    def save_screenshot(self) -> str:
        frame = self.capture.screenshot()
        debug_dir = self.config.data_dir / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        path = debug_dir / f"gui_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        import cv2

        cv2.imwrite(str(path), frame)
        return f"Saved screenshot: {path}"

    def force_stop_coc(self) -> str:
        self.app.force_stop()
        return f"Force-stopped {self.config.coc_package}."

    def relaunch_coc(self) -> str:
        pkg = self.config.coc_package
        was_running = self.app.is_running()
        if was_running:
            logger.info("Clash already running — force-stopping before relaunch")
            self.app.force_stop()
            time.sleep(2.0)

        loading = self.navigator.load_template("loading")
        self.app.launch()
        ready = self.app.wait_until_ready(loading_template=loading)
        running = self.app.is_running()
        if ready and running:
            return "Clash relaunched and appears loaded."
        if running and not ready:
            return (
                "Clash process is running but load wait timed out "
                "(optional loading template / slow start). Check the game window."
            )
        return (
            "Clash did not start. Try opening it once from Waydroid manually, "
            "then retry. Also check: waydroid app list | grep -i clash"
        )

    def break_cycle_short(self, wait_seconds: int = 8) -> str:
        """Simulate take-a-break: force-stop, wait, relaunch, reopen chat."""
        logger.info("Debug break cycle — force-stop, wait {}s, relaunch", wait_seconds)
        self.app.force_stop()
        time.sleep(max(3, wait_seconds))
        loading = self.navigator.load_template("loading")
        self.app.launch()
        self.app.wait_until_ready(loading_template=loading)
        ok = self.navigator.ensure_clan_chat(
            has_donate_request=lambda f: self.chat_monitor.find_donate_request(f) is not None
        )
        from coc_bot.vision.screens import ScreenClassifier

        ScreenClassifier.disarm_live_replay_watch()
        if ok:
            return f"Break cycle done (waited {wait_seconds}s) — clan chat open."
        return f"Break cycle finished (waited {wait_seconds}s) but clan chat reopen failed."

    def farm_open_attack_menu(self) -> str:
        frame = self.capture.screenshot()
        screen0 = self.classifier.classify(frame)
        chip = self.attack_nav.attack_button_visible(frame)
        blob = self.attack_nav._find_attack_button_blob(frame)  # noqa: SLF001
        wm = self.client.wm_size()
        ok = self.attack_nav.open_attack_menu()
        screen = self.classifier.classify(self.capture.screenshot())
        debug = self.config.data_dir / "debug"
        hint = (
            f"before={screen0.value} chip={chip} blob={blob} "
            f"frame={frame.shape[1]}x{frame.shape[0]} wm={wm} → "
            f"ok={ok} after={screen.value}. "
            f"Check {debug}/attack_pre_tap.png (yellow circle = tap target) "
            f"and attack_post_tap.png."
        )
        if ok:
            return f"Opened Attack menu — {hint}"
        return f"Failed to open Attack menu — {hint}"

    def farm_start_unranked_search(self) -> str:
        if not self.config.tap_points.get("unranked_battle"):
            return "unranked_battle not calibrated — run Calibration → Farm."
        ok = self.attack_nav.start_unranked_battle()
        time.sleep(1.0)
        screen = self.classifier.classify(self.capture.screenshot())
        if ok:
            return (
                f"Started unranked Battle / search — screen: {screen.value}. "
                "Cancel manually if you do not want a full match."
            )
        return f"Failed to start unranked Battle — screen: {screen.value}"

    def farm_classify_battle(self) -> str:
        frame = self.capture.screenshot()
        screen = self.classifier.classify(frame)
        return (
            f"Screen: {screen.value} "
            f"(farm_calibrated={self.config.farm_calibrated}, "
            f"deploy_side={self.config.farm_deploy_side})"
        )

    def farm_deploy_dry_taps(self) -> str:
        """Pan toward deploy edge, then tap a few ladder points (no full attack wait)."""
        frame = self.capture.screenshot()
        screen = self.classifier.classify(frame)
        side = self.config.farm_deploy_side
        pans = self.config.farm_pan_swipes
        self.deployer.pan_to_deploy_side(frame, side=side)
        points = self.deployer.deploy_points(frame, side=side)
        # Only a short ladder so debug stays quick.
        for x, y in points[:4]:
            self.input.tap(x, y)
            time.sleep(0.1)
        return (
            f"Deploy dry-run: {pans} pan swipe(s) toward {side}, "
            f"then {min(4, len(points))} taps (screen={screen.value}). "
            f"Full ladder has {len(points)} points."
        )

    def prepare_farm_program_deploy(self) -> dict:
        """
        ADB-only prep for the deploy editor (safe on a worker thread).

        Returns side/pan_swipes/frame/initial taps for ``finish_farm_program_deploy``.
        """
        from coc_bot.config import normalize_farm_deploy_sequence

        self.client.health_check()
        side = self.config.farm_deploy_side
        pans = float(self.config.farm_pan_swipes)
        frame = self.capture.screenshot()
        logger.info(
            "Program farm deploy: panning side={} pan_swipes={} then opening editor",
            side,
            pans,
        )
        self.deployer.pan_to_deploy_side(frame, side=side, pan_swipes=pans)
        time.sleep(0.5)
        frame = self.capture.screenshot()
        existing = normalize_farm_deploy_sequence(self.config.farm_deploy_sequence)
        initial = [(int(x), int(y)) for x, y in existing.get("taps") or []]
        return {
            "side": side,
            "pan_swipes": pans,
            "frame": frame,
            "initial": initial,
            "jitter_px": int(self.config.farm_deploy_jitter_px),
        }

    def finish_farm_program_deploy(self, prep: dict, *, master=None) -> str:
        """
        Open the click editor (must run on the Tk UI thread) and save the sequence.
        """
        from coc_bot.calibration.sequence_picker import pick_deploy_sequence
        from coc_bot.config import load_config, save_calibrated

        side = prep["side"]
        pans = float(prep["pan_swipes"])
        frame = prep["frame"]
        initial = prep.get("initial") or []
        points, jitter, used = pick_deploy_sequence(
            frame,
            jitter_px=int(prep.get("jitter_px", 6)),
            initial_points=initial or None,
            refresh_cb=self.capture.screenshot,
            title="Program farm deploy taps",
            master=master,
        )
        if points is None:
            return "Program farm deploy cancelled — sequence unchanged."

        cfg = load_config()
        cfg.farm_deploy_sequence = {
            "side": side,
            "pan_swipes": pans,
            "taps": [[int(x), int(y)] for x, y in points],
        }
        cfg.farm_deploy_jitter_px = max(0, min(40, int(jitter)))
        if used is not None and used.size:
            h, w = used.shape[:2]
            if cfg.frame_width <= 0:
                cfg.frame_width = w
            if cfg.frame_height <= 0:
                cfg.frame_height = h
        save_calibrated(cfg)
        self.config = load_config()
        return (
            f"Saved farm deploy sequence: {len(points)} taps "
            f"(side={side}, pan_swipes={pans}, farm deploy jitter±{jitter}px). "
            "Farm attacks will replay this tap sequence. "
            "Stop/Start the bot if it is already running."
        )

    def farm_program_deploy_sequence(self) -> str:
        """
        Pan then open editor — for CLI / non-GUI callers only.

        From the BotControlApp Tools/Setup buttons, use prepare + finish on the
        UI thread (Tk cannot open windows from a worker thread).
        """
        prep = self.prepare_farm_program_deploy()
        return self.finish_farm_program_deploy(prep, master=None)

    def farm_clear_deploy_sequence(self) -> str:
        """Remove the programmed deploy sequence (farm cannot deploy until reprogrammed)."""
        from coc_bot.config import load_config, save_calibrated

        cfg = load_config()
        cfg.farm_deploy_sequence = {"side": "left", "pan_swipes": 3.0, "taps": []}
        save_calibrated(cfg)
        self.config = load_config()
        return (
            "Cleared farm deploy sequence — program a new sequence before farming. "
            "Stop/Start if the bot is running."
        )

    def farm_one_shot(self, should_stop=None) -> tuple[bool, str]:
        """Run a full unranked farm attack once (leave chat → deploy → return home)."""
        from collections.abc import Callable

        from coc_bot.attack.farmer import AttackFarmer
        from coc_bot.runtime.tracker import RuntimeTracker

        stop: Callable[[], bool] | None = should_stop
        self.client.health_check()
        farmer = AttackFarmer(
            self.config, self.capture, self.input, self.matcher, self.navigator
        )
        if stop is not None:
            farmer.stop_check = stop
            farmer.attack_nav.stop_check = stop
            farmer.deployer.stop_check = stop
            self.navigator.stop_check = stop
        result = farmer.run_one_attack()
        if result.success:
            RuntimeTracker(self.config).mark_farm_success()
        if stop is not None and stop():
            msg = f"Farm one-shot: stopped ({result.reason})"
            return False, msg
        msg = f"Farm one-shot: success={result.success} ({result.reason})"
        return result.success, msg

# Grouped Tools page actions: (group title, [(id, label, description), ...])
DEBUG_GROUPS: list[tuple[str, list[tuple[str, str, str]]]] = [
    (
        "System",
        [
            (
                "health_check",
                "ADB health check",
                "Verify the bot can talk to Waydroid over ADB.",
            ),
            (
                "classify_screen",
                "Classify current screen",
                "Detect home / clan chat / donation panel / popup / unknown.",
            ),
            (
                "save_screenshot",
                "Save screenshot",
                "Write a debug PNG under data/debug/.",
            ),
            (
                "force_stop",
                "Force-stop Clash of Clans",
                "Close the game only (Waydroid stays up). Leaves you on Android home.",
            ),
            (
                "relaunch",
                "Relaunch Clash of Clans",
                "Start CoC again and wait until it looks loaded.",
            ),
            (
                "break_cycle",
                "Test break / take-a-break cycle",
                "Force-stop CoC, wait ~8s, relaunch, reopen clan chat — simulates the "
                "session-limit break used to avoid long continuous play.",
            ),
        ],
    ),
    (
        "Donation",
        [
            (
                "open_clan_chat",
                "Open clan chat",
                "Navigate from home (or recover) until clan chat is open.",
            ),
            (
                "find_classify_request",
                "Find + classify donation request",
                "Look for a Donate button and report specific vs open/hybrid.",
            ),
            (
                "open_donation",
                "Open a donation panel",
                "Tap the first visible Donate and wait for the donation popup.",
            ),
            (
                "close_donation",
                "Close donation panel",
                "Tap outside the donation popup to close it.",
            ),
            (
                "scroll_chat",
                "Scroll / seek chat once",
                "One step of searching chat for donation requests.",
            ),
            (
                "anti_idle",
                "Anti-idle nudge once",
                "Small swipe in the chat area (same idea as inactivity prevention).",
            ),
        ],
    ),
    (
        "Farm",
        [
            (
                "farm_open_attack",
                "Farm: open Attack menu",
                "Leave chat if needed, tap Attack. Does not start a match.",
            ),
            (
                "farm_start_search",
                "Farm: start unranked search",
                "Tap unranked Battle (+ Find a Match if calibrated). May enter clouds — cancel manually if needed.",
            ),
            (
                "farm_classify",
                "Farm: classify battle screen",
                "Report current screen type (attack_menu / matchmaking / battle / results / …).",
            ),
            (
                "farm_deploy_dry",
                "Farm: deploy-edge dry taps",
                "A few taps along the configured deploy edge (no full attack wait).",
            ),
            (
                "farm_program_deploy",
                "Farm: program deploy sequence",
                "Be on the battlefield first. Pans with your Settings, then opens a click "
                "editor — number army-bar + map taps in order (required for farm deploy).",
            ),
            (
                "farm_clear_deploy",
                "Farm: clear deploy sequence",
                "Delete the programmed tap sequence (farm cannot deploy until you program a new one).",
            ),
        ],
    ),
]

DEBUG_ACTIONS: list[tuple[str, str, str]] = [
    action for _group, actions in DEBUG_GROUPS for action in actions
]


def run_debug_action(action_id: str) -> str:
    session = DebugSession()
    mapping = {
        "health_check": session.health_check,
        "classify_screen": session.classify_screen,
        "open_clan_chat": session.open_clan_chat,
        "find_classify_request": session.find_and_classify_request,
        "open_donation": session.open_donation_panel,
        "close_donation": session.close_donation_panel,
        "scroll_chat": session.scroll_chat_step,
        "anti_idle": session.anti_idle_nudge,
        "save_screenshot": session.save_screenshot,
        "force_stop": session.force_stop_coc,
        "relaunch": session.relaunch_coc,
        "break_cycle": session.break_cycle_short,
        "farm_open_attack": session.farm_open_attack_menu,
        "farm_start_search": session.farm_start_unranked_search,
        "farm_classify": session.farm_classify_battle,
        "farm_deploy_dry": session.farm_deploy_dry_taps,
        "farm_program_deploy": session.farm_program_deploy_sequence,
        "farm_clear_deploy": session.farm_clear_deploy_sequence,
    }
    fn = mapping.get(action_id)
    if fn is None:
        raise ValueError(f"Unknown debug action: {action_id}")
    try:
        return fn()
    except AdbError as exc:
        return f"ADB error: {exc}"
    except Exception as exc:  # noqa: BLE001
        logger.exception("Debug action {} failed", action_id)
        return f"Error: {exc}"
