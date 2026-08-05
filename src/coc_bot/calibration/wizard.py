from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
from loguru import logger

from coc_bot.adb.capture import ScreenCapture
from coc_bot.adb.client import AdbClient
from coc_bot.adb.input import InputController
from coc_bot.calibration.template_capture import (
    prompt_point,
    prompt_roi,
    prompt_yes_no,
    sample_center_color,
    save_template,
)  # noqa: F401 — prompt_point/roi used by _pick_* helpers
from coc_bot.config import BotConfig, load_config, save_calibrated
from coc_bot.logging_utils import setup_logging
from coc_bot.vision.rois import normalize_roi


STEP_IDS = (
    "home",
    "clan_chat",
    "donation_request",
    "donation_panel",
    "slot_colors",
    "grid",
    "farm",
    "optional",
)


@dataclass(frozen=True)
class CalibrationPart:
    """One tangible item inside a calibration step (shown as a subsection in the GUI)."""

    key: str
    label: str
    kind: str  # tap | template | roi | color | grid | meta
    optional: bool = False
    description: str = ""


@dataclass(frozen=True)
class CalibrationStep:
    step_id: str
    title: str
    summary: str
    status_keys: tuple[str, ...]
    parts: tuple[CalibrationPart, ...] = ()


STEPS: dict[str, CalibrationStep] = {
    "home": CalibrationStep(
        "home",
        "Home screen",
        "Stay on home village with clan chat CLOSED — teach screen size and the bubble that opens chat",
        ("frame_width", "open_chat"),
        (
            CalibrationPart(
                "frame_width",
                "Screen size",
                "meta",
                description="Stay on home; bot reads screenshot size",
            ),
            CalibrationPart(
                "home",
                "Home anchor",
                "template",
                optional=True,
                description="Optional: box something unique on the home village",
            ),
            CalibrationPart(
                "open_chat",
                "Open chat (chat bubble)",
                "tap",
                description="On home with chat CLOSED — crop the bubble that opens clan chat",
            ),
        ),
    ),
    "clan_chat": CalibrationStep(
        "clan_chat",
        "Clan chat",
        "OPEN clan chat (do not open the donation panel) — teach chat areas and close/jump controls",
        ("chat_panel", "chat_requests", "clan_chat", "chat_scroll_down", "chat_request_jump"),
        (
            CalibrationPart(
                "chat_panel",
                "Chat panel area",
                "roi",
                description="Open clan chat — box the whole chat panel",
            ),
            CalibrationPart(
                "chat_requests",
                "Donate requests area",
                "roi",
                description="Open clan chat — box where Donate requests appear",
            ),
            CalibrationPart(
                "clan_chat",
                "Clan chat anchor",
                "template",
                description="Open clan chat — box UI hidden when the donation panel covers chat",
            ),
            CalibrationPart(
                "close_chat",
                "Close chat tab",
                "tap",
                optional=True,
                description="Open clan chat — orange < tab that closes chat",
            ),
            CalibrationPart(
                "chat_request_jump",
                "Request jump icon",
                "template",
                optional=True,
                description="Open clan chat — exclamation at top or bottom of the chat log",
            ),
            CalibrationPart(
                "chat_scroll_down",
                "Scroll-down icon",
                "template",
                optional=True,
                description="Open clan chat — bottom jump icon (skip if jump icon already set)",
            ),
        ),
    ),
    "donation_request": CalibrationStep(
        "donation_request",
        "Donation request",
        "OPEN clan chat and show a green Donate button on a request",
        ("donate_button",),
        (
            CalibrationPart(
                "donate_button",
                "Donate button",
                "template",
                description="Open clan chat — tight box around the green Donate button",
            ),
        ),
    ),
    "donation_panel": CalibrationStep(
        "donation_panel",
        "Donation panel",
        "OPEN clan chat, tap Donate, leave the white donation panel open",
        (
            "donation_elixir_button",
            "donation_troop_bar",
            "donation_spell_bar",
            "tap_outside_donation",
        ),
        (
            CalibrationPart(
                "donation_panel",
                "Donation Resource title",
                "template",
                optional=True,
                description="Donation panel open — crop the “Donation Resource” title",
            ),
            CalibrationPart(
                "donation_elixir_button",
                "Elixir resource button",
                "tap",
                description=(
                    "Donation panel open — the left Elixir / Dark Elixir toggle "
                    "next to “Donation Resource” (not the gem button)"
                ),
            ),
            CalibrationPart(
                "donation_troop_bar",
                "Troop + siege bar area",
                "roi",
                description="Donation panel open — box the troop + siege icon row",
            ),
            CalibrationPart(
                "donation_spell_bar",
                "Spell bar area",
                "roi",
                description="Donation panel open — box the spell icon row",
            ),
            CalibrationPart(
                "tap_outside_donation",
                "Tap outside to close",
                "tap",
                description="Donation panel open — click empty dimmed area outside the panel",
            ),
        ),
    ),
    "slot_colors": CalibrationStep(
        "slot_colors",
        "Slot colors",
        "OPEN the donation panel — sample colored slots you can donate and grey ones you cannot",
        ("donatable_troop", "disabled_troop", "donatable_spell", "disabled_spell"),
        (
            CalibrationPart(
                "donatable_troop",
                "Donatable troop color",
                "color",
                description="Donation panel open — small box on a colored troop/siege slot",
            ),
            CalibrationPart(
                "disabled_troop",
                "Grey troop color",
                "color",
                description="Donation panel open — small box on a grey troop/siege slot",
            ),
            CalibrationPart(
                "donatable_spell",
                "Donatable spell color",
                "color",
                description="Donation panel open — small box on a colored spell slot",
            ),
            CalibrationPart(
                "disabled_spell",
                "Grey spell color",
                "color",
                description="Donation panel open — small box on a grey spell slot",
            ),
        ),
    ),
    "grid": CalibrationStep(
        "grid",
        "Grid layout",
        "OPEN the donation panel — draw boxes around all troop and spell slot cells",
        ("grid",),
        (
            CalibrationPart(
                "troop_bar",
                "Troop + siege grid",
                "grid",
                description="Donation panel open — box all troop/siege cells, then enter columns and rows",
            ),
            CalibrationPart(
                "spell_bar",
                "Spell grid",
                "grid",
                description="Donation panel open — box all spell cells, then enter columns and rows",
            ),
        ),
    ),
    "farm": CalibrationStep(
        "farm",
        "Farm / unranked attack",
        "Home for Attack, Attack menu for Battle, end of battle for Return Home, then battlefield for deploy taps",
        ("attack_button", "unranked_battle", "return_home"),
        (
            CalibrationPart(
                "attack_button",
                "Attack! button",
                "tap",
                description="Home village, chat closed — Attack! button (usually bottom-left)",
            ),
            CalibrationPart(
                "unranked_battle",
                "Unranked Battle",
                "tap",
                description="Attack menu open — Battle (not Ranked)",
            ),
            CalibrationPart(
                "find_match",
                "Find a Match / start search",
                "tap",
                optional=True,
                description="Only if Find a Match is a separate button after Battle",
            ),
            CalibrationPart(
                "return_home",
                "Return Home",
                "tap",
                description="After a battle — Return Home / OK button",
            ),
            CalibrationPart(
                "deploy_sequence",
                "Deploy tap sequence",
                "meta",
                optional=True,
                description="In an unranked battle — program army bar and map taps in order",
            ),
        ),
    ),
    "optional": CalibrationStep(
        "optional",
        "Optional UI",
        "Only if you want extras — show Chat Groups, loading, or a popup when asked",
        ("loading", "chat_groups", "clan_chat_tab"),
        (
            CalibrationPart(
                "chat_groups",
                "Chat Groups title",
                "template",
                optional=True,
                description=(
                    "Open Chat Groups (globe icon) — crop the “Chat Groups” title "
                    "(or the green “+ New” button)"
                ),
            ),
            CalibrationPart(
                "clan_chat_tab",
                "Clan chat tab (swords)",
                "tap",
                optional=True,
                description=(
                    "Chat Groups still open — crop/click the swords+shield bubble "
                    "(top tab) that returns to clan chat"
                ),
            ),
            CalibrationPart(
                "loading",
                "Loading screen",
                "template",
                optional=True,
                description="Optional: show Clash loading, then box something unique on it",
            ),
            CalibrationPart(
                "popup_dismiss",
                "Popup dismiss",
                "template",
                optional=True,
                description="Optional: show a popup, then box its dismiss / OK button",
            ),
            CalibrationPart(
                "popup",
                "Popup anchor",
                "template",
                optional=True,
                description="Optional: show a popup, then box a unique part of it",
            ),
        ),
    ),
}


def part_is_configured(config: BotConfig, part: CalibrationPart) -> bool:
    """Whether a subsection item is present in the current calibration."""
    key = part.key
    if part.kind == "meta":
        if key == "frame_width":
            return int(config.frame_width or 0) > 0 and int(config.frame_height or 0) > 0
        if key == "deploy_sequence":
            from coc_bot.config import normalize_farm_deploy_sequence

            seq = normalize_farm_deploy_sequence(config.farm_deploy_sequence)
            return bool(seq.get("taps"))
        return False
    if part.kind == "tap":
        if key == "tap_outside_donation":
            return bool(
                config.tap_points.get("tap_outside_donation")
                or config.tap_points.get("close_donation")
            )
        return bool(config.tap_points.get(key)) or bool(config.templates.get(key))
    if part.kind == "template":
        return bool(config.templates.get(key))
    if part.kind == "roi":
        return key in config.rois
    if part.kind == "color":
        return bool(config.colors.get(key))
    if part.kind == "grid":
        grid = config.grid or {}
        if key in ("troop_bar", "spell_bar"):
            return bool(grid.get(key))
        return bool(grid)
    return False


def parent_step_id(tree_iid: str) -> str:
    """Map a tree selection iid (step or step::part) to the wizard --step id."""
    if "::" in tree_iid:
        return tree_iid.split("::", 1)[0]
    return tree_iid


def _roi_list(coords: tuple[int, int, int, int], w: int, h: int) -> list[float]:
    nr = normalize_roi(*coords, w, h)
    return [nr.x, nr.y, nr.w, nr.h]


def _press_enter(message: str = "Press Enter when ready...") -> None:
    input(message)


def _keeping(label: str) -> None:
    print(f"Keeping existing {label}.")


def print_step_menu(status: dict[str, bool]) -> None:
    print("\nCalibration steps:")
    print("-" * 60)
    for step_id in STEP_IDS:
        step = STEPS[step_id]
        mark = "[x]" if status.get(step_id) else "[ ]"
        print(f"  {mark} {step_id:18} — {step.title}")
        print(f"      {step.summary}")
        for part in step.parts:
            opt = " (optional)" if part.optional else ""
            print(f"        · {part.label}{opt} [{part.key}]")
    print("-" * 60)
    print("Run:  python scripts/calibrate.py --step clan_chat")
    print("      python scripts/calibrate.py --step farm --part return_home")
    print("      python scripts/calibrate.py --all")


class CalibrationWizard:
    """Interactive calibration with per-step / per-part re-run support."""

    def __init__(self, config: BotConfig | None = None) -> None:
        self.config = config or load_config()
        self.client = AdbClient(device=self.config.adb_device)
        self.capture = ScreenCapture(self.client)
        self.input = InputController(self.client, dry_run=False)
        self.capture.bind_input(self.input)
        self.templates_dir = self.config.templates_dir
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        # When set, step_* methods only run the matching CalibrationPart key.
        self._only_part: str | None = None
        if self.config.calibrated:
            logger.info("Loaded existing calibration from data/calibrated.yaml")

    # --- skip/update helpers (answer 'n' to keep existing values) ---

    def _want_part(self, key: str) -> bool:
        """True if we should run this part (full step, or this key alone)."""
        return self._only_part is None or self._only_part == key

    def _has_roi(self, key: str) -> bool:
        return key in self.config.rois

    def _has_template(self, key: str) -> bool:
        return key in self.config.templates

    def _has_tap(self, key: str) -> bool:
        return bool(self.config.tap_points.get(key))

    def _has_color(self, key: str) -> bool:
        return key in self.config.colors

    def _should_update(self, label: str, *, exists: bool, optional: bool = False) -> bool:
        """Ask before changing anything — answer 'n' keeps or skips."""
        if not exists:
            if optional:
                if prompt_yes_no(f"Capture {label}?"):
                    return True
                print(f"Skipping {label}.")
                return False
            # Required but missing: still allow skip so a part can be deferred.
            if prompt_yes_no(f"{label} is missing — capture it now?"):
                return True
            print(f"Skipping {label} (still missing).")
            return False
        if prompt_yes_no(f"Update {label}?"):
            return True
        _keeping(label)
        return False

    def _fresh_frame(self):
        return self.capture.screenshot()

    def _pick_roi(self, label: str, frame=None):
        if frame is None:
            frame = self._fresh_frame()
        return prompt_roi(label, frame, refresh_cb=self._fresh_frame, return_frame=True)

    def _pick_point(self, label: str, frame=None) -> tuple[int, int]:
        if frame is None:
            frame = self._fresh_frame()
        return prompt_point(label, frame, refresh_cb=self._fresh_frame)

    def _maybe_update_roi(self, key: str, label: str, w: int, h: int, *, optional: bool = False) -> None:
        if not self._should_update(label, exists=self._has_roi(key), optional=optional):
            return
        coords, frame = self._pick_roi(label)
        fh, fw = frame.shape[:2]
        self.config.rois[key] = _roi_list(coords, fw, fh)
        self.config.frame_width = fw
        self.config.frame_height = fh
        logger.info("Saved ROI {}", key)

    def _maybe_update_template(
        self,
        key: str,
        label: str,
        rel_path: str,
        frame,
        *,
        optional: bool = False,
    ) -> None:
        if not self._should_update(label, exists=self._has_template(key), optional=optional):
            return
        coords, picked_frame = self._pick_roi(label, frame)
        self._save_template_from_frame(picked_frame, coords, rel_path, key)

    def _maybe_update_template_after_setup(
        self,
        key: str,
        label: str,
        rel_path: str,
        setup_message: str,
        *,
        optional: bool = False,
    ) -> None:
        if not self._should_update(label, exists=self._has_template(key), optional=optional):
            return
        print(setup_message)
        _press_enter()
        frame = self._fresh_frame()
        coords, picked_frame = self._pick_roi(label, frame)
        self._save_template_from_frame(picked_frame, coords, rel_path, key)

    def _maybe_update_tap_point(self, key: str, label: str) -> None:
        if not self._should_update(label, exists=self._has_tap(key)):
            return
        pt = self._pick_point(label)
        self.config.tap_points[key] = list(pt)
        logger.info("Saved tap point {}", key)

    def _maybe_update_color(self, key: str, label: str, frame) -> None:
        if not self._should_update(label, exists=self._has_color(key)):
            return
        coords, picked_frame = self._pick_roi(label, frame)
        self.config.colors[key] = sample_center_color(picked_frame, coords)
        logger.info("Saved color {}", key)

    def _ensure_connected(self) -> None:
        self.client.ensure_connected()

    def _frame_size(self) -> tuple[int, int]:
        w, h = self.config.frame_width, self.config.frame_height
        if w <= 0 or h <= 0:
            frame = self.capture.screenshot()
            h, w = frame.shape[:2]
            self.config.frame_width = w
            self.config.frame_height = h
            self._save()
        return w, h

    def _save(self) -> None:
        save_calibrated(self.config)
        logger.info("Saved data/calibrated.yaml")

    def _save_template_from_frame(
        self,
        frame,
        coords: tuple[int, int, int, int],
        rel_path: str,
        template_key: str,
    ) -> None:
        crop = frame[coords[1] : coords[1] + coords[3], coords[0] : coords[0] + coords[2]]
        save_template(crop, self.templates_dir / rel_path)
        self.config.templates[template_key] = rel_path
        logger.info("Saved template {}", template_key)

    def step_status(self) -> dict[str, bool]:
        status: dict[str, bool] = {}
        for step_id, step in STEPS.items():
            status[step_id] = self._step_configured(step)
        return status

    def _step_configured(self, step: CalibrationStep) -> bool:
        if step.step_id == "home":
            has_open = bool(self.config.tap_points.get("open_chat")) or bool(
                self.config.templates.get("open_chat")
            )
            return self.config.frame_width > 0 and has_open
        if step.step_id == "clan_chat":
            return all(
                k in self.config.rois or k in self.config.templates
                for k in ("chat_panel", "chat_requests", "clan_chat", "chat_scroll_down")
            ) and (
                "chat_scroll_down" in self.config.templates or "chat_request_jump" in self.config.templates
            )
        if step.step_id == "donation_request":
            return "donate_button" in self.config.templates
        if step.step_id == "donation_panel":
            return (
                "donation_troop_bar" in self.config.rois
                and bool(
                    self.config.tap_points.get("tap_outside_donation")
                    or self.config.tap_points.get("close_donation")
                )
                and bool(self.config.tap_points.get("donation_elixir_button"))
            )
        if step.step_id == "slot_colors":
            return bool(self.config.colors.get("donatable_troop")) and bool(
                self.config.colors.get("disabled_troop")
            )
        if step.step_id == "grid":
            return bool(self.config.grid)
        if step.step_id == "farm":
            return bool(
                self.config.tap_points.get("attack_button")
                and self.config.tap_points.get("unranked_battle")
                and self.config.tap_points.get("return_home")
            )
        if step.step_id == "optional":
            return "loading" in self.config.templates or "popup_dismiss" in self.config.templates
        return False

    def run_interactive(self) -> None:
        self._ensure_connected()
        print("\n=== CoC Donation Bot — Calibration ===")
        if self.config.calibrated:
            print("Existing calibration loaded. Re-run any step without losing the rest.\n")

        handlers = self._handlers()
        while True:
            print_step_menu(self.step_status())
            print("\nEnter step name (e.g. clan_chat), comma-separated list, 'all', or 'q' to quit:")
            raw = input("> ").strip().lower()
            if raw in ("q", "quit", "exit"):
                print("Done.")
                break
            if raw == "all":
                self.run_steps(list(STEP_IDS))
                continue
            if not raw:
                continue
            selected = [s.strip() for s in raw.replace(" ", ",").split(",") if s.strip()]
            invalid = [s for s in selected if s not in STEP_IDS]
            if invalid:
                print(f"Unknown step(s): {', '.join(invalid)}")
                continue
            self.run_steps(selected)

    def run_steps(self, step_ids: list[str], *, only_part: str | None = None) -> None:
        self._ensure_connected()
        handlers = self._handlers()
        for step_id in step_ids:
            if step_id not in handlers:
                logger.error("Unknown step: {}", step_id)
                continue
            if only_part is not None:
                valid = {p.key for p in STEPS[step_id].parts}
                if only_part not in valid:
                    logger.error(
                        "Unknown part '{}' for step {} (valid: {})",
                        only_part,
                        step_id,
                        ", ".join(sorted(valid)),
                    )
                    continue
                if only_part == "deploy_sequence":
                    print(
                        "\nDeploy tap sequence is programmed from the GUI:\n"
                        "  Setup → Farm → Deploy tap sequence → Recalibrate Selected\n"
                        "  (or Tools → Farm: program deploy sequence)\n"
                        "Enter an unranked battle first.\n"
                    )
                    continue
            title = STEPS[step_id].title
            if only_part:
                print(f"\n{'=' * 60}\n  STEP: {title} → part: {only_part}\n{'=' * 60}")
            else:
                print(f"\n{'=' * 60}\n  STEP: {title}\n{'=' * 60}")
            self._only_part = only_part
            try:
                handlers[step_id]()
            finally:
                self._only_part = None
            self._save()
            if only_part:
                print(f"\n✓ Part '{step_id}::{only_part}' saved.\n")
            else:
                print(f"\n✓ Step '{step_id}' saved.\n")
        print("Calibration update complete.")

    def _handlers(self) -> dict[str, Callable[[], None]]:
        return {
            "home": self.step_home,
            "clan_chat": self.step_clan_chat,
            "donation_request": self.step_donation_request,
            "donation_panel": self.step_donation_panel,
            "slot_colors": self.step_slot_colors,
            "grid": self.step_grid,
            "farm": self.step_farm,
            "optional": self.step_optional,
        }

    def step_home(self) -> None:
        need_home_screen = self._want_part("frame_width") or self._want_part("home") or self._want_part(
            "open_chat"
        )
        if need_home_screen:
            print("Go to your village/HOME screen (not in chat).")
            _press_enter()
        frame = self.capture.screenshot() if need_home_screen else self._fresh_frame()

        if self._want_part("frame_width"):
            has_size = int(self.config.frame_width or 0) > 0
            if not has_size or prompt_yes_no("Update screen size from screenshot?"):
                h, w = frame.shape[:2]
                self.config.frame_width = w
                self.config.frame_height = h
                logger.info("Frame size: {}x{}", w, h)
            else:
                _keeping("frame_width")

        if self._want_part("home"):
            self._maybe_update_template(
                "home",
                "home anchor template",
                "ui/home.png",
                frame,
                optional=True,
            )

        if self._want_part("open_chat"):
            print("\n--- Open chat button (must be captured from HOME screen) ---")
            print(
                "This is the chat bubble / ``>`` tab that OPENS clan chat from home.\n"
                "Capture it as an IMAGE (recommended): the bot uses that picture to tell\n"
                "home apart from battle. Closing chat uses a different orange ``<`` tab\n"
                "(Clan chat step)."
            )
            has_tpl = self._has_template("open_chat")
            has_tap = self._has_tap("open_chat")
            if self._should_update(
                "open_chat chat-bubble image",
                exists=has_tpl,
                optional=False,
            ):
                coords, picked = self._pick_roi(
                    "Drag a box tightly around the chat bubble on HOME", frame
                )
                self._save_template_from_frame(picked, coords, "ui/open_chat.png", "open_chat")
                x, y, bw, bh = coords
                self.config.tap_points["open_chat"] = [int(x + bw / 2), int(y + bh / 2)]
                logger.info("Saved open_chat template + tap at center")
            elif not has_tap and self._should_update(
                "open_chat tap point", exists=False, optional=False
            ):
                pt = self._pick_point("Tap point at CENTER of open-chat control", frame)
                self.config.tap_points["open_chat"] = list(pt)
                logger.info("Saved tap point open_chat")
            elif has_tap and not has_tpl and prompt_yes_no("Update open_chat tap point only?"):
                pt = self._pick_point("Tap point at CENTER of open-chat control", frame)
                self.config.tap_points["open_chat"] = list(pt)
                logger.info("Saved tap point open_chat")

    def step_clan_chat(self) -> None:
        need = any(
            self._want_part(k)
            for k in (
                "chat_panel",
                "chat_requests",
                "clan_chat",
                "close_chat",
                "chat_scroll_down",
                "chat_request_jump",
            )
        )
        if not need:
            return
        w, h = self._frame_size()
        print("Open clan chat. Do NOT open the donation panel.")
        _press_enter()
        frame = self.capture.screenshot()

        if self._want_part("chat_panel"):
            self._maybe_update_roi("chat_panel", "chat panel area", w, h)
        if self._want_part("chat_requests"):
            self._maybe_update_roi("chat_requests", "donate requests area", w, h)

        if self._want_part("clan_chat"):
            print(
                "\n--- clan_chat anchor ---\n"
                "Pick UI that is visible in clan chat but HIDDEN when the donation panel is open.\n"
                "Good: selected Clan tab, chat header. Bad: anything covered by the donate popup."
            )
            self._maybe_update_template(
                "clan_chat",
                "clan_chat anchor template",
                "ui/clan_chat.png",
                frame,
            )

        if self._want_part("close_chat"):
            print(
                "\n--- Close chat tab (orange ``<`` on the right edge of the open chat panel) ---\n"
                "This is DIFFERENT from the open-chat bubble on home.\n"
                "With clan chat OPEN, tap the small orange tab with the left arrow."
            )
            has_close = self._has_tap("close_chat") or self._has_template("close_chat")
            if self._should_update("close_chat control", exists=has_close, optional=True):
                if prompt_yes_no("Capture close_chat as image template?"):
                    coords, picked = self._pick_roi("Orange < close-chat tab", frame)
                    self._save_template_from_frame(
                        picked, coords, "ui/close_chat.png", "close_chat"
                    )
                pt = self._pick_point("Tap point at CENTER of the orange < close tab", frame)
                self.config.tap_points["close_chat"] = list(pt)
                logger.info("Saved tap point close_chat")

        if self._want_part("chat_scroll_down"):
            print(
                "\n--- Scroll-down / jump icon at bottom (optional legacy template) ---\n"
                "If you already captured the bottom exclamation as chat_scroll_down, you can skip this.\n"
                "Otherwise scroll chat UP until the bottom icon appears, then capture it."
            )
            self._maybe_update_template_after_setup(
                "chat_scroll_down",
                "bottom chat jump icon (optional if chat_request_jump captured)",
                "ui/chat_scroll_down.png",
                "When the bottom icon is visible, press Enter...",
                optional=True,
            )

        if not self._want_part("chat_request_jump"):
            return
        print(
            "\n--- Exclamation jump icon (top OR bottom of chat log) ---\n"
            "Same icon appears at the TOP when a request is above the current view,\n"
            "or at the BOTTOM when a request is below. Tapping either jumps to a request.\n"
            "Capture once — the bot searches both ends. (Your chat_scroll_down template\n"
            "at the bottom also works as a fallback.)\n"
            "Tip: scroll until the icon is visible at whichever edge applies, then capture it."
        )
        self._maybe_update_template_after_setup(
            "chat_request_jump",
            "exclamation jump icon (top or bottom of chat log)",
            "ui/chat_request_jump.png",
            "When the exclamation is visible at the top or bottom, press Enter...",
            optional=True,
        )

    def step_donation_request(self) -> None:
        if not self._want_part("donate_button"):
            return
        print(
            "Show a donation request with a visible Donate button in clan chat.\n"
            "Requested troops/spells appear in the chat message only — NOT in the donation panel."
        )
        _press_enter()
        frame = self.capture.screenshot()

        self._maybe_update_template(
            "donate_button",
            "donate button template",
            "ui/donate_button.png",
            frame,
        )
        self.config.rois.pop("request_header", None)

    def step_donation_panel(self) -> None:
        need = any(
            self._want_part(k)
            for k in (
                "donation_panel",
                "donation_elixir_button",
                "donation_troop_bar",
                "donation_spell_bar",
                "tap_outside_donation",
            )
        )
        if not need:
            return
        w, h = self._frame_size()
        print("Tap Donate on a request to OPEN the donation panel, then continue.")
        _press_enter("With donation panel open, press Enter...")
        frame = self.capture.screenshot()

        if self._want_part("donation_panel"):
            print(
                "\n--- Donation Resource title (optional but recommended) ---\n"
                "Crop tightly around the unique “Donation Resource” text at the top of\n"
                "the white panel. The bot also detects the white card automatically."
            )
            self._maybe_update_template(
                "donation_panel",
                "Donation Resource title template",
                "ui/donation_panel.png",
                frame,
                optional=True,
            )

        if self._want_part("donation_elixir_button"):
            print(
                "\n--- Elixir resource button (not gems) ---\n"
                "At the top of the panel, next to “Donation Resource”, there are two toggles:\n"
                "  LEFT  = Elixir + Dark Elixir (use this)\n"
                "  RIGHT = green Gem (do NOT use — spending gems)\n"
                "Capture the LEFT elixir toggle so the bot can switch back if gems is selected."
            )
            has_elixir = self._has_tap("donation_elixir_button") or self._has_template(
                "donation_elixir_button"
            )
            if self._should_update(
                "donation_elixir_button (elixir toggle)",
                exists=has_elixir,
                optional=False,
            ):
                if prompt_yes_no("Capture elixir button as image template?"):
                    coords, picked = self._pick_roi(
                        "LEFT Elixir / Dark Elixir toggle (not the gem)", frame
                    )
                    self._save_template_from_frame(
                        picked, coords, "ui/donation_elixir_button.png", "donation_elixir_button"
                    )
                pt = self._pick_point(
                    "Tap point at CENTER of the LEFT elixir toggle", frame
                )
                self.config.tap_points["donation_elixir_button"] = list(pt)
                logger.info("Saved tap point donation_elixir_button")

        if self._want_part("donation_troop_bar") or self._want_part("donation_spell_bar"):
            print(
                "\nThe troop bar holds regular troops AND siege machines in the same area."
            )
        if self._want_part("donation_troop_bar"):
            self._maybe_update_roi(
                "donation_troop_bar", "troop + siege bar area", w, h
            )
        if self._want_part("donation_spell_bar"):
            self._maybe_update_roi("donation_spell_bar", "spell bar area", w, h)

        # Legacy — siege shared troop bar in current CoC UI
        self.config.rois.pop("donation_siege_bar", None)

        if self._want_part("tap_outside_donation"):
            print(
                "\n--- Close donation panel ---\n"
                "CoC has no X button. Tap OUTSIDE the panel (dimmed chat/background) to close it."
            )
            self._maybe_update_tap_point(
                "tap_outside_donation",
                "Tap point OUTSIDE the donation panel (dimmed area)",
            )

    def step_slot_colors(self) -> None:
        color_keys = (
            "donatable_troop",
            "disabled_troop",
            "donatable_spell",
            "disabled_spell",
        )
        if not any(self._want_part(k) for k in color_keys):
            return
        print(
            "Open the donation panel.\n"
            "Colored slots can be donated; grey slots cannot (wrong type or won't fit).\n"
            "For best results, show BOTH a colored and a grey troop slot, and both spell slots."
        )
        _press_enter()
        frame = self.capture.screenshot()

        if self._want_part("donatable_troop"):
            self._maybe_update_color(
                "donatable_troop",
                "COLORED troop/siege slot (can be donated)",
                frame,
            )
        if self._want_part("disabled_troop"):
            self._maybe_update_color(
                "disabled_troop",
                "GREY troop/siege slot (cannot be donated)",
                frame,
            )
        if self._want_part("donatable_spell"):
            self._maybe_update_color(
                "donatable_spell",
                "COLORED spell slot (can be donated)",
                frame,
            )
        if self._want_part("disabled_spell"):
            self._maybe_update_color(
                "disabled_spell",
                "GREY spell slot (cannot be donated)",
                frame,
            )

    def step_grid(self) -> None:
        want_troop = self._want_part("troop_bar")
        want_spell = self._want_part("spell_bar")
        if not want_troop and not want_spell:
            return

        # Full-step: one deny skips the whole grid. Part-only: ask that bar only.
        if self._only_part is None and self.config.grid:
            if not prompt_yes_no("Update grid layout?"):
                _keeping("grid")
                return

        print(
            "\nRecommended: draw the grid on screen (covers all visible slot cells exactly).\n"
            "  python scripts/pick_grid.py\n"
        )
        if self._only_part is None and prompt_yes_no(
            "Launch grid picker now (needs a visible display or remote desktop)?"
        ):
            import subprocess
            import sys

            subprocess.run(
                [sys.executable, str(Path(__file__).resolve().parents[3] / "scripts" / "pick_grid.py")]
            )
            return

        if not prompt_yes_no("Enter column/row counts manually?"):
            print("Skipped grid numbers. Run later: python scripts/pick_grid.py")
            return

        current = dict(self.config.grid or {})
        troop_bar = dict(current.get("troop_bar") or {})
        spell_bar = dict(current.get("spell_bar") or {})
        troop_cols_default = troop_bar.get("cols", 7)
        troop_rows_default = troop_bar.get("rows", 1)
        spell_cols_default = spell_bar.get("cols", 5)
        spell_rows_default = spell_bar.get("rows", 1)

        print("Enter VISIBLE slot layout (Enter keeps default).")
        if want_troop:
            raw = input(f"Troop+siege columns [{troop_cols_default}]: ").strip()
            troop_cols = int(raw) if raw else troop_cols_default
            raw = input(f"Troop+siege rows [{troop_rows_default}]: ").strip()
            troop_rows = int(raw) if raw else troop_rows_default
            current["troop_bar"] = {"cols": troop_cols, "rows": troop_rows}
        if want_spell:
            raw = input(f"Spell columns [{spell_cols_default}]: ").strip()
            spell_cols = int(raw) if raw else spell_cols_default
            raw = input(f"Spell rows [{spell_rows_default}]: ").strip()
            spell_rows = int(raw) if raw else spell_rows_default
            current["spell_bar"] = {"cols": spell_cols, "rows": spell_rows}
        self.config.grid = current

    def step_farm(self) -> None:
        """Calibrate unranked Battle farming taps (each part can be skipped)."""
        w, h = self._frame_size()
        if self._only_part is None:
            print(
                "\n=== Farm / unranked attack ===\n"
                "IMPORTANT: Leave your farm army as the ACTIVE army preset.\n"
                "The bot does not train troops or switch armies.\n"
                "Deploy tap sequence: Setup → Farm → Deploy tap sequence.\n"
            )

        if self._want_part("attack_button"):
            print("Go to your village HOME screen (chat closed).")
            _press_enter()
            frame = self.capture.screenshot()
            print("\n--- Attack button (bottom of home) ---")
            has_attack = self._has_tap("attack_button") or self._has_template("attack_button")
            if self._should_update("attack_button", exists=has_attack):
                if prompt_yes_no("Capture attack_button as image template?"):
                    coords, picked = self._pick_roi("Attack button", frame)
                    self._save_template_from_frame(
                        picked, coords, "ui/attack_button.png", "attack_button"
                    )
                pt = self._pick_point("Tap point at CENTER of Attack button", frame)
                self.config.tap_points["attack_button"] = list(pt)
                logger.info("Saved tap point attack_button")

        if self._want_part("unranked_battle"):
            print(
                "\nOpen the Attack menu so you see Ranked vs Battle (unranked).\n"
                "You can tap Attack yourself, then press Enter."
            )
            _press_enter()
            frame = self.capture.screenshot()
            print("\n--- Unranked Battle (NOT Ranked) ---")
            has_battle = self._has_tap("unranked_battle") or self._has_template("unranked_battle")
            if self._should_update("unranked_battle", exists=has_battle):
                if prompt_yes_no("Capture unranked_battle as image template?"):
                    coords, picked = self._pick_roi("Unranked Battle button", frame)
                    self._save_template_from_frame(
                        picked, coords, "ui/unranked_battle.png", "unranked_battle"
                    )
                pt = self._pick_point(
                    "Tap point at CENTER of unranked Battle (not Ranked)", frame
                )
                self.config.tap_points["unranked_battle"] = list(pt)
                logger.info("Saved tap point unranked_battle")

        if self._want_part("find_match"):
            print(
                "\nIf Find a Match is a separate button after Battle, show that screen.\n"
                "Otherwise skip Find a Match (Battle may start search immediately)."
            )
            has_fm = self._has_tap("find_match") or self._has_template("find_match")
            if self._should_update("Find a Match / next button", exists=has_fm, optional=True):
                _press_enter()
                frame = self.capture.screenshot()
                if prompt_yes_no("Capture find_match as image template?"):
                    coords, picked = self._pick_roi("Find a Match button", frame)
                    self._save_template_from_frame(
                        picked, coords, "ui/find_match.png", "find_match"
                    )
                pt = self._pick_point("Tap point at CENTER of Find a Match", frame)
                self.config.tap_points["find_match"] = list(pt)
                logger.info("Saved tap point find_match")

        if self._want_part("return_home"):
            print(
                "\n--- Return Home (after a finished attack) ---\n"
                "Finish or wait for any battle end screen that shows Return Home / OK."
            )
            has_rh = self._has_tap("return_home")
            if self._should_update("return_home", exists=has_rh):
                _press_enter()
                frame = self.capture.screenshot()
                if prompt_yes_no("Capture return_home / battle_end as image template?"):
                    coords, picked = self._pick_roi("Return Home button", frame)
                    self._save_template_from_frame(
                        picked, coords, "ui/return_home.png", "return_home"
                    )
                    self.config.templates["battle_end"] = self.config.templates.get(
                        "return_home", "ui/return_home.png"
                    )
                pt = self._pick_point("Tap point at CENTER of Return Home", frame)
                self.config.tap_points["return_home"] = list(pt)
                logger.info("Saved tap point return_home")

        if "deploy_strip" in self.config.rois:
            del self.config.rois["deploy_strip"]
            logger.info("Removed obsolete deploy_strip ROI (not used anymore)")

        if self._only_part is None:
            print(
                "\nFarm calibration done. Program deploy taps via Setup → Farm → "
                "Deploy tap sequence when ready.\n"
            )

    def step_optional(self) -> None:
        if self._want_part("chat_groups"):
            self._maybe_update_template_after_setup(
                "chat_groups",
                "Chat Groups title (or + New) template",
                "ui/chat_groups.png",
                "Tap the globe icon to open Chat Groups, then crop the “Chat Groups” "
                "title text (or the green “+ New” button).",
                optional=True,
            )

        if self._want_part("clan_chat_tab"):
            print(
                "\n--- Clan chat tab (swords + shield bubble, top of the chat edge) ---\n"
                "Keep Chat Groups OPEN. This is the top icon ABOVE the orange “<” tab.\n"
                "Tapping it leaves Chat Groups and returns to clan chat."
            )
            has_tab = self._has_tap("clan_chat_tab") or self._has_template("clan_chat_tab")
            if self._should_update("clan_chat_tab control", exists=has_tab, optional=True):
                if prompt_yes_no("Capture clan_chat_tab as image template?"):
                    frame = self.capture.screenshot()
                    coords, picked = self._pick_roi("Swords/shield clan chat tab", frame)
                    if coords is not None and picked is not None:
                        self._save_template_from_frame(
                            picked, coords, "ui/clan_chat_tab.png", "clan_chat_tab"
                        )
                        x, y, bw, bh = coords
                        self.config.tap_points["clan_chat_tab"] = [
                            int(x + bw / 2),
                            int(y + bh / 2),
                        ]
                        logger.info("Saved clan_chat_tab template + tap at center")
                else:
                    frame = self.capture.screenshot()
                    pt = self._pick_point("Tap CENTER of swords/shield clan chat tab", frame)
                    self.config.tap_points["clan_chat_tab"] = list(pt)
                    logger.info("Saved tap point clan_chat_tab")

        if self._want_part("loading"):
            self._maybe_update_template_after_setup(
                "loading",
                "loading screen template",
                "ui/loading.png",
                "Relaunch CoC to show the loading screen.",
                optional=True,
            )

        if self._want_part("popup_dismiss"):
            self._maybe_update_template_after_setup(
                "popup_dismiss",
                "popup dismiss button template",
                "ui/popup_dismiss.png",
                "Show a dismissible popup/event.",
                optional=True,
            )

        if self._want_part("popup"):
            self._maybe_update_template_after_setup(
                "popup",
                "popup anchor template",
                "ui/popup.png",
                "Show a blocking popup/event card.",
                optional=True,
            )


def main() -> None:
    """CLI entry for calibration (used by scripts/calibrate.py and coc-bot-calibrate)."""
    setup_logging(debug=False)
    parser = argparse.ArgumentParser(
        description="Calibrate CoC donation bot (full run, steps, or a single part)",
    )
    parser.add_argument(
        "--step",
        action="append",
        dest="steps",
        choices=STEP_IDS,
        metavar="STEP",
        help=f"Run one step only (repeatable). Choices: {', '.join(STEP_IDS)}",
    )
    parser.add_argument(
        "--part",
        default=None,
        metavar="PART",
        help="With --step, run only this CalibrationPart key (e.g. return_home)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all steps in order (same as legacy full calibration)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List steps and whether each appears configured",
    )
    args = parser.parse_args()

    wizard = CalibrationWizard()
    if args.list:
        print_step_menu(wizard.step_status())
    elif args.steps:
        if args.part and len(args.steps) != 1:
            parser.error("--part requires exactly one --step")
        wizard.run_steps(args.steps, only_part=args.part)
    elif args.all:
        if args.part:
            parser.error("--part cannot be used with --all")
        wizard.run_steps(list(STEP_IDS))
    else:
        if args.part:
            parser.error("--part requires --step")
        wizard.run_interactive()


if __name__ == "__main__":
    main()
