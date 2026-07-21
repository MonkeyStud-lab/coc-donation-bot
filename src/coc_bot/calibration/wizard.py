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
)
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
    "units",
    "optional",
)


@dataclass(frozen=True)
class CalibrationStep:
    step_id: str
    title: str
    summary: str
    status_keys: tuple[str, ...]


STEPS: dict[str, CalibrationStep] = {
    "home": CalibrationStep(
        "home",
        "Home screen",
        "Frame size, optional home anchor, open-chat button/tap point",
        ("frame_width", "open_chat"),
    ),
    "clan_chat": CalibrationStep(
        "clan_chat",
        "Clan chat",
        "Chat ROIs, clan_chat anchor, top exclamation + bottom scroll-down icons",
        ("chat_panel", "chat_requests", "clan_chat", "chat_scroll_down", "chat_request_jump"),
    ),
    "donation_request": CalibrationStep(
        "donation_request",
        "Donation request",
        "Donate button template, request header ROI",
        ("donate_button", "request_header"),
    ),
    "donation_panel": CalibrationStep(
        "donation_panel",
        "Donation panel",
        "Troop+siege bar, spell bar, tap-outside-to-close point",
        ("donation_troop_bar", "donation_spell_bar", "tap_outside_donation"),
    ),
    "slot_colors": CalibrationStep(
        "slot_colors",
        "Slot colors",
        "Colored vs grey troop/spell slot samples in the donation panel bars",
        ("donatable_troop", "disabled_troop", "donatable_spell", "disabled_spell"),
    ),
    "grid": CalibrationStep(
        "grid",
        "Grid layout",
        "Column counts for troop/spell/siege/request bars",
        ("grid",),
    ),
    "units": CalibrationStep(
        "units",
        "Unit icons",
        "Template image per troop/spell/siege type",
        ("unit_templates",),
    ),
    "optional": CalibrationStep(
        "optional",
        "Optional UI",
        "Loading screen and popup dismiss templates",
        ("loading",),
    ),
}


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
    print("-" * 60)
    print("Run:  python scripts/calibrate.py --step clan_chat")
    print("      python scripts/calibrate.py --all")


class CalibrationWizard:
    """Interactive calibration with per-step re-run support."""

    def __init__(self, config: BotConfig | None = None) -> None:
        self.config = config or load_config()
        self.client = AdbClient(device=self.config.adb_device)
        self.capture = ScreenCapture(self.client)
        self.input = InputController(self.client, dry_run=False)
        self.templates_dir = self.config.templates_dir
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        if self.config.calibrated:
            logger.info("Loaded existing calibration from data/calibrated.yaml")

    # --- skip/update helpers (answer 'n' to keep existing values) ---

    def _has_roi(self, key: str) -> bool:
        return key in self.config.rois

    def _has_template(self, key: str) -> bool:
        return key in self.config.templates

    def _has_tap(self, key: str) -> bool:
        return bool(self.config.tap_points.get(key))

    def _has_color(self, key: str) -> bool:
        return key in self.config.colors

    def _should_update(self, label: str, *, exists: bool, optional: bool = False) -> bool:
        if not exists:
            if optional:
                if prompt_yes_no(f"Capture {label}?"):
                    return True
                print(f"Skipping {label}.")
                return False
            return True
        if prompt_yes_no(f"Update {label}?"):
            return True
        _keeping(label)
        return False

    def _maybe_update_roi(self, key: str, label: str, w: int, h: int, *, optional: bool = False) -> None:
        if not self._should_update(label, exists=self._has_roi(key), optional=optional):
            return
        coords = prompt_roi(label)
        self.config.rois[key] = _roi_list(coords, w, h)
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
        coords = prompt_roi(label)
        self._save_template_from_frame(frame, coords, rel_path, key)

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
        frame = self.capture.screenshot()
        coords = prompt_roi(label)
        self._save_template_from_frame(frame, coords, rel_path, key)

    def _maybe_update_tap_point(self, key: str, label: str) -> None:
        if not self._should_update(label, exists=self._has_tap(key)):
            return
        pt = prompt_point(label)
        self.config.tap_points[key] = list(pt)
        logger.info("Saved tap point {}", key)

    def _maybe_update_color(self, key: str, label: str, frame) -> None:
        if not self._should_update(label, exists=self._has_color(key)):
            return
        coords = prompt_roi(label)
        self.config.colors[key] = sample_center_color(frame, coords)
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
            return "donate_button" in self.config.templates and "request_header" in self.config.rois
        if step.step_id == "donation_panel":
            return "donation_troop_bar" in self.config.rois and bool(
                self.config.tap_points.get("tap_outside_donation")
                or self.config.tap_points.get("close_donation")
            )
        if step.step_id == "slot_colors":
            return bool(self.config.colors.get("donatable_troop")) and bool(
                self.config.colors.get("disabled_troop")
            )
        if step.step_id == "grid":
            return bool(self.config.grid)
        if step.step_id == "units":
            return len(self.config.unit_templates) > 0
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

    def run_steps(self, step_ids: list[str]) -> None:
        self._ensure_connected()
        handlers = self._handlers()
        for step_id in step_ids:
            if step_id not in handlers:
                logger.error("Unknown step: {}", step_id)
                continue
            print(f"\n{'=' * 60}\n  STEP: {STEPS[step_id].title}\n{'=' * 60}")
            handlers[step_id]()
            self._save()
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
            "units": self.step_units,
            "optional": self.step_optional,
        }

    def step_home(self) -> None:
        print("Go to your village/HOME screen (not in chat).")
        _press_enter()
        frame = self.capture.screenshot()
        h, w = frame.shape[:2]
        self.config.frame_width = w
        self.config.frame_height = h
        logger.info("Frame size: {}x{}", w, h)

        self._maybe_update_template(
            "home",
            "home anchor template",
            "ui/home.png",
            frame,
            optional=True,
        )

        print("\n--- Open chat button (must be captured from HOME screen) ---")
        has_open = self._has_template("open_chat") or self._has_tap("open_chat")
        if not has_open or prompt_yes_no("Update open_chat button?"):
            if prompt_yes_no("Capture open_chat button as image template?"):
                coords = prompt_roi("Chat bubble on the LEFT of home screen")
                self._save_template_from_frame(frame, coords, "ui/open_chat.png", "open_chat")
            else:
                pt = prompt_point("Tap point at CENTER of chat bubble")
                self.config.tap_points["open_chat"] = list(pt)
                logger.info("Saved tap point open_chat")
        else:
            _keeping("open_chat")

    def step_clan_chat(self) -> None:
        w, h = self._frame_size()
        print("Open clan chat. Do NOT open the donation panel.")
        _press_enter()
        frame = self.capture.screenshot()

        self._maybe_update_roi("chat_panel", "chat panel ROI", w, h)
        self._maybe_update_roi("chat_requests", "chat requests ROI", w, h)

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
        w, h = self._frame_size()
        print("Show a donation request with a visible Donate button in clan chat.")
        _press_enter()
        frame = self.capture.screenshot()

        self._maybe_update_template(
            "donate_button",
            "donate button template",
            "ui/donate_button.png",
            frame,
        )
        self._maybe_update_roi(
            "request_header",
            "request header ROI",
            w,
            h,
        )

    def step_donation_panel(self) -> None:
        w, h = self._frame_size()
        print("Tap Donate on a request to OPEN the donation panel, then continue.")
        _press_enter("With donation panel open, press Enter...")
        frame = self.capture.screenshot()

        print(
            "\nThe troop bar holds regular troops AND siege machines in the same area."
        )
        self._maybe_update_roi("donation_troop_bar", "troop donation bar ROI (troops + siege)", w, h)
        self._maybe_update_roi("donation_spell_bar", "spell donation bar ROI", w, h)

        # Legacy — siege shared troop bar in current CoC UI
        self.config.rois.pop("donation_siege_bar", None)

        print(
            "\n--- Close donation panel ---\n"
            "CoC has no X button. Tap OUTSIDE the panel (dimmed chat/background) to close it."
        )
        self._maybe_update_tap_point(
            "tap_outside_donation",
            "Tap point OUTSIDE the donation panel (dimmed area)",
        )

    def step_slot_colors(self) -> None:
        print(
            "Open the donation panel.\n"
            "Colored slots can be donated; grey slots cannot (wrong type or won't fit).\n"
            "For best results, show BOTH a colored and a grey troop slot, and both spell slots."
        )
        _press_enter()
        frame = self.capture.screenshot()

        self._maybe_update_color(
            "donatable_troop",
            "COLORED troop/siege slot (can be donated)",
            frame,
        )
        self._maybe_update_color(
            "disabled_troop",
            "GREY troop/siege slot (cannot be donated)",
            frame,
        )
        self._maybe_update_color(
            "donatable_spell",
            "COLORED spell slot (can be donated)",
            frame,
        )
        self._maybe_update_color(
            "disabled_spell",
            "GREY spell slot (cannot be donated)",
            frame,
        )

    def step_grid(self) -> None:
        if self.config.grid and not prompt_yes_no("Update grid layout?"):
            _keeping("grid")
            return

        current = self.config.grid or {}
        troop_bar = current.get("troop_bar", {})
        spell_bar = current.get("spell_bar", {})
        req_bar = current.get("request", {})
        troop_cols_default = troop_bar.get("cols", 7)
        troop_rows_default = troop_bar.get("rows", 1)
        spell_cols_default = spell_bar.get("cols", 5)
        spell_rows_default = spell_bar.get("rows", 1)
        req_default = req_bar.get("cols", 6)

        print("Enter VISIBLE slot layout (Enter keeps current/default).")
        print("Count only what you see before scrolling — e.g. 2 rows x 7 cols = 14 troop slots.")
        print("The troop bar ROI (donation_panel step) must cover all visible rows.")
        print("Troop bar includes regular troops and siege machines.")
        raw = input(f"Troop+siege columns (slots per row) [{troop_cols_default}]: ").strip()
        troop_cols = int(raw) if raw else troop_cols_default
        raw = input(f"Troop+siege rows [{troop_rows_default}]: ").strip()
        troop_rows = int(raw) if raw else troop_rows_default
        raw = input(f"Spell columns (slots per row) [{spell_cols_default}]: ").strip()
        spell_cols = int(raw) if raw else spell_cols_default
        raw = input(f"Spell rows [{spell_rows_default}]: ").strip()
        spell_rows = int(raw) if raw else spell_rows_default
        raw = input(f"Request header cols [{req_default}]: ").strip()
        req_cols = int(raw) if raw else req_default

        self.config.grid = {
            "troop_bar": {"cols": troop_cols, "rows": troop_rows},
            "spell_bar": {"cols": spell_cols, "rows": spell_rows},
            "request": {"cols": req_cols, "rows": 1},
        }

    def step_units(self) -> None:
        print("Open donation panel. You'll be asked about each unit type.")
        _press_enter()
        self._capture_unit_templates()

    def step_optional(self) -> None:
        self._maybe_update_template_after_setup(
            "loading",
            "loading screen template",
            "ui/loading.png",
            "Relaunch CoC to show the loading screen.",
            optional=True,
        )

        self._maybe_update_template_after_setup(
            "popup_dismiss",
            "popup dismiss button template",
            "ui/popup_dismiss.png",
            "Show a dismissible popup/event.",
            optional=True,
        )

    def _capture_unit_templates(self) -> None:
        units_by_category: dict[str, list[str]] = {"troop": [], "spell": [], "siege": []}
        for unit_id, info in self.config.units.items():
            units_by_category.setdefault(info.category, []).append(unit_id)

        for category in ("troop", "spell", "siege"):
            print(f"\n--- {category.upper()} templates ---")
            for unit_id in units_by_category.get(category, []):
                already = unit_id in self.config.unit_templates
                prompt = f"Update template for '{unit_id}'?" if already else f"Capture template for '{unit_id}'?"
                if already and not prompt_yes_no(prompt):
                    _keeping(f"unit template {unit_id}")
                    continue
                if not already and not prompt_yes_no(prompt):
                    print(f"Skipping {unit_id}.")
                    continue
                print(f"Show '{unit_id}' in the donation panel.")
                _press_enter()
                frame = self.capture.screenshot()
                coords = prompt_roi(f"{unit_id} icon region")
                crop = frame[coords[1] : coords[1] + coords[3], coords[0] : coords[0] + coords[2]]
                rel = f"units/{unit_id}.png"
                save_template(crop, self.templates_dir / rel)
                self.config.unit_templates[unit_id] = rel
                logger.info("Saved unit template {}", unit_id)


def main() -> None:
    setup_logging(debug=False)
    parser = argparse.ArgumentParser(description="CoC donation bot calibration wizard")
    parser.add_argument("--step", action="append", dest="steps", choices=STEP_IDS)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    wizard = CalibrationWizard()
    if args.list:
        print_step_menu(wizard.step_status())
    elif args.steps:
        wizard.run_steps(args.steps)
    elif args.all:
        wizard.run_steps(list(STEP_IDS))
    else:
        wizard.run_interactive()


if __name__ == "__main__":
    main()
