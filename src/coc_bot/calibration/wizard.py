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
        "Chat ROIs, clan_chat anchor, scroll-down indicator",
        ("chat_panel", "chat_requests", "clan_chat", "chat_scroll_down"),
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
        "Troop/spell/siege bars, panel close, quick donate",
        ("donation_troop_bar", "donation_spell_bar", "panel_close"),
    ),
    "slot_colors": CalibrationStep(
        "slot_colors",
        "Slot colors",
        "Donatable troop and spell slot color signatures",
        ("donatable_troop", "donatable_spell"),
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
            ) and "chat_scroll_down" in self.config.templates
        if step.step_id == "donation_request":
            return "donate_button" in self.config.templates and "request_header" in self.config.rois
        if step.step_id == "donation_panel":
            return "donation_troop_bar" in self.config.rois
        if step.step_id == "slot_colors":
            return "donatable_troop" in self.config.colors and "donatable_spell" in self.config.colors
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

        if prompt_yes_no("Capture home anchor template?"):
            coords = prompt_roi("Home anchor region")
            self._save_template_from_frame(frame, coords, "ui/home.png", "home")

        print("\n--- Open chat button (must be captured from HOME screen) ---")
        if prompt_yes_no("Capture open_chat button as image template?"):
            coords = prompt_roi("Chat bubble on the LEFT of home screen")
            self._save_template_from_frame(frame, coords, "ui/open_chat.png", "open_chat")
        else:
            pt = prompt_point("Tap point at CENTER of chat bubble")
            self.config.tap_points["open_chat"] = list(pt)

    def step_clan_chat(self) -> None:
        w, h = self._frame_size()
        print("Open clan chat. Do NOT open the donation panel.")
        _press_enter()
        frame = self.capture.screenshot()

        if prompt_yes_no("Update chat panel ROI?"):
            chat_roi = prompt_roi("Chat panel region (full chat area)")
            self.config.rois["chat_panel"] = _roi_list(chat_roi, w, h)

        if prompt_yes_no("Update chat requests ROI?"):
            requests_roi = prompt_roi("Region where Donate buttons appear in chat")
            self.config.rois["chat_requests"] = _roi_list(requests_roi, w, h)

        print(
            "\n--- clan_chat anchor ---\n"
            "Pick UI that is visible in clan chat but HIDDEN when the donation panel is open.\n"
            "Good: selected Clan tab, chat header. Bad: anything covered by the donate popup."
        )
        if prompt_yes_no("Update clan_chat anchor template?"):
            coords = prompt_roi("clan_chat anchor (visible in chat, hidden when donating)")
            self._save_template_from_frame(frame, coords, "ui/clan_chat.png", "clan_chat")

        print("\n--- Scroll-down indicator ---")
        print("Scroll chat UP until the scroll-down arrow/button appears.")
        _press_enter("When the indicator is visible, press Enter...")
        scroll_frame = self.capture.screenshot()
        scroll_coords = prompt_roi("Scroll-down indicator (only when NOT at bottom)")
        self._save_template_from_frame(scroll_frame, scroll_coords, "ui/chat_scroll_down.png", "chat_scroll_down")

        if prompt_yes_no("Update chat_at_bottom anchor (optional fallback)?"):
            print("Scroll chat to the very bottom first.")
            _press_enter()
            bottom_frame = self.capture.screenshot()
            coords = prompt_roi("UI visible only when chat IS at bottom")
            self._save_template_from_frame(bottom_frame, coords, "ui/chat_at_bottom.png", "chat_at_bottom")

    def step_donation_request(self) -> None:
        w, h = self._frame_size()
        print("Show a donation request with a visible Donate button in clan chat.")
        _press_enter()
        frame = self.capture.screenshot()

        donate_coords = prompt_roi("Donate button region")
        self._save_template_from_frame(frame, donate_coords, "ui/donate_button.png", "donate_button")

        header_roi = prompt_roi("Request header row (requested unit icons when panel opens)")
        self.config.rois["request_header"] = _roi_list(header_roi, w, h)

    def step_donation_panel(self) -> None:
        w, h = self._frame_size()
        print("Tap Donate on a request to OPEN the donation panel, then continue.")
        _press_enter("With donation panel open, press Enter...")
        frame = self.capture.screenshot()

        troop_roi = prompt_roi("Troop donation bar region")
        self.config.rois["donation_troop_bar"] = _roi_list(troop_roi, w, h)

        spell_roi = prompt_roi("Spell donation bar region")
        self.config.rois["donation_spell_bar"] = _roi_list(spell_roi, w, h)

        siege_roi = prompt_roi("Siege donation bar region")
        self.config.rois["donation_siege_bar"] = _roi_list(siege_roi, w, h)

        for ui_key, label in [
            ("panel_close", "Panel close / X button"),
            ("quick_donate", "Quick donate / confirm button"),
        ]:
            if prompt_yes_no(f"Capture {label}?"):
                coords = prompt_roi(label)
                rel = f"ui/{ui_key}.png"
                self._save_template_from_frame(frame, coords, rel, ui_key)

    def step_slot_colors(self) -> None:
        print("Open the donation panel with troops/spells visible in your castle bar.")
        _press_enter()
        frame = self.capture.screenshot()

        troop_slot = prompt_roi("One donatable TROOP slot (single cell)")
        self.config.colors["donatable_troop"] = sample_center_color(frame, troop_slot)

        spell_slot = prompt_roi("One donatable SPELL slot (single cell)")
        self.config.colors["donatable_spell"] = sample_center_color(frame, spell_slot)

    def step_grid(self) -> None:
        current = self.config.grid or {}
        troop_default = current.get("troop_bar", {}).get("cols", 8)
        spell_default = current.get("spell_bar", {}).get("cols", 5)
        siege_default = current.get("siege_bar", {}).get("cols", 3)
        req_default = current.get("request", {}).get("cols", 6)

        print("Enter column counts (Enter keeps current/default).")
        raw = input(f"Troop bar cols [{troop_default}]: ").strip()
        troop_cols = int(raw) if raw else troop_default
        raw = input(f"Spell bar cols [{spell_default}]: ").strip()
        spell_cols = int(raw) if raw else spell_default
        raw = input(f"Siege bar cols [{siege_default}]: ").strip()
        siege_cols = int(raw) if raw else siege_default
        raw = input(f"Request header cols [{req_default}]: ").strip()
        req_cols = int(raw) if raw else req_default

        self.config.grid = {
            "troop_bar": {"cols": troop_cols, "rows": 1},
            "spell_bar": {"cols": spell_cols, "rows": 1},
            "siege_bar": {"cols": siege_cols, "rows": 1},
            "request": {"cols": req_cols, "rows": 1},
        }

    def step_units(self) -> None:
        print("Open donation panel. You'll be asked about each unit type.")
        _press_enter()
        self._capture_unit_templates()

    def step_optional(self) -> None:
        if prompt_yes_no("Capture loading screen template?"):
            print("Relaunch CoC to show the loading screen.")
            _press_enter()
            frame = self.capture.screenshot()
            coords = prompt_roi("Loading screen distinctive region")
            self._save_template_from_frame(frame, coords, "ui/loading.png", "loading")

        if prompt_yes_no("Capture popup dismiss button?"):
            print("Show a dismissible popup/event.")
            _press_enter()
            frame = self.capture.screenshot()
            coords = prompt_roi("Popup close/dismiss button")
            self._save_template_from_frame(frame, coords, "ui/popup_dismiss.png", "popup_dismiss")

    def _capture_unit_templates(self) -> None:
        units_by_category: dict[str, list[str]] = {"troop": [], "spell": [], "siege": []}
        for unit_id, info in self.config.units.items():
            units_by_category.setdefault(info.category, []).append(unit_id)

        for category in ("troop", "spell", "siege"):
            print(f"\n--- {category.upper()} templates ---")
            for unit_id in units_by_category.get(category, []):
                already = unit_id in self.config.unit_templates
                default = "y" if not already else "n"
                prompt = f"Capture template for '{unit_id}'?" + (" (exists)" if already else "")
                if not prompt_yes_no(prompt):
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
