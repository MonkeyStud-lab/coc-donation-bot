from __future__ import annotations

from pathlib import Path

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


def _roi_list(coords: tuple[int, int, int, int], w: int, h: int) -> list[float]:
    nr = normalize_roi(*coords, w, h)
    return [nr.x, nr.y, nr.w, nr.h]


class CalibrationWizard:
    """Interactive first-time calibration CLI."""

    def __init__(self, config: BotConfig | None = None) -> None:
        self.config = config or load_config()
        self.client = AdbClient(device=self.config.adb_device)
        self.capture = ScreenCapture(self.client)
        self.input = InputController(self.client, dry_run=False)
        self.templates_dir = self.config.templates_dir
        self.templates_dir.mkdir(parents=True, exist_ok=True)

    def run(self) -> None:
        logger.info("Starting calibration wizard")
        self.client.ensure_connected()

        print("\n=== Step 1: Home screen ===")
        print("Navigate to your village/home screen, then press Enter.")
        input()
        home_frame = self.capture.screenshot()
        h, w = home_frame.shape[:2]
        self.config.frame_width = w
        self.config.frame_height = h
        logger.info("Frame size: {}x{}", w, h)

        if prompt_yes_no("Capture home anchor template?"):
            coords = prompt_roi("Home anchor region")
            crop = home_frame[coords[1] : coords[1] + coords[3], coords[0] : coords[0] + coords[2]]
            rel = "ui/home.png"
            save_template(crop, self.templates_dir / rel)
            self.config.templates["home"] = rel

        print("\n=== Step 2: Clan chat ===")
        print("Open clan chat, then press Enter.")
        input()
        chat_frame = self.capture.screenshot()

        chat_roi = prompt_roi("Chat panel region")
        self.config.rois["chat_panel"] = _roi_list(chat_roi, w, h)

        requests_roi = prompt_roi("Chat requests list region (where donate buttons appear)")
        self.config.rois["chat_requests"] = _roi_list(requests_roi, w, h)

        if prompt_yes_no("Capture open_chat template from current screen?"):
            coords = prompt_roi("Open chat button/icon region")
            crop = chat_frame[coords[1] : coords[1] + coords[3], coords[0] : coords[0] + coords[2]]
            rel = "ui/open_chat.png"
            save_template(crop, self.templates_dir / rel)
            self.config.templates["open_chat"] = rel
        else:
            pt = prompt_point("Tap point to open clan chat from home")
            self.config.tap_points["open_chat"] = list(pt)

        if prompt_yes_no("Capture clan_chat anchor template?"):
            coords = prompt_roi("Unique clan chat UI element")
            crop = chat_frame[coords[1] : coords[1] + coords[3], coords[0] : coords[0] + coords[2]]
            rel = "ui/clan_chat.png"
            save_template(crop, self.templates_dir / rel)
            self.config.templates["clan_chat"] = rel

        print("\n--- Chat scroll-down indicator (required for reliable scrolling) ---")
        print("Scroll chat UP away from the bottom until the 'scroll down' UI appears.")
        print("(This is usually an arrow/button shown when newer messages are below.)")
        input("When that indicator is visible, press Enter...")
        scroll_frame = self.capture.screenshot()
        scroll_coords = prompt_roi("Scroll-down indicator (only visible when NOT at bottom)")
        scroll_crop = scroll_frame[
            scroll_coords[1] : scroll_coords[1] + scroll_coords[3],
            scroll_coords[0] : scroll_coords[0] + scroll_coords[2],
        ]
        rel = "ui/chat_scroll_down.png"
        save_template(scroll_crop, self.templates_dir / rel)
        self.config.templates["chat_scroll_down"] = rel
        logger.info("Saved chat_scroll_down template")

        if prompt_yes_no("Capture chat_at_bottom anchor (optional legacy fallback)?"):
            print("Scroll chat all the way to the bottom first.")
            input("Press Enter when at bottom...")
            at_bottom_frame = self.capture.screenshot()
            coords = prompt_roi("UI element visible only when chat IS at bottom")
            crop = at_bottom_frame[coords[1] : coords[1] + coords[3], coords[0] : coords[0] + coords[2]]
            rel = "ui/chat_at_bottom.png"
            save_template(crop, self.templates_dir / rel)
            self.config.templates["chat_at_bottom"] = rel

        print("\n=== Step 3: Donation request ===")
        print("Ensure a donation request with Donate button is visible, then press Enter.")
        input()
        req_frame = self.capture.screenshot()

        donate_coords = prompt_roi("Donate button region")
        donate_crop = req_frame[
            donate_coords[1] : donate_coords[1] + donate_coords[3],
            donate_coords[0] : donate_coords[0] + donate_coords[2],
        ]
        rel = "ui/donate_button.png"
        save_template(donate_crop, self.templates_dir / rel)
        self.config.templates["donate_button"] = rel

        header_roi = prompt_roi("Request header row (requested unit icons)")
        self.config.rois["request_header"] = _roi_list(header_roi, w, h)

        print("\n=== Step 4: Donation panel ===")
        print("Tap the Donate button manually to open the donation panel, then press Enter.")
        input()
        panel_frame = self.capture.screenshot()

        troop_roi = prompt_roi("Troop donation bar region")
        self.config.rois["donation_troop_bar"] = _roi_list(troop_roi, w, h)

        spell_roi = prompt_roi("Spell donation bar region")
        self.config.rois["donation_spell_bar"] = _roi_list(spell_roi, w, h)

        siege_roi = prompt_roi("Siege donation bar region")
        self.config.rois["donation_siege_bar"] = _roi_list(siege_roi, w, h)

        for ui_key, label in [
            ("panel_close", "Panel close button"),
            ("quick_donate", "Quick donate / confirm button"),
        ]:
            if prompt_yes_no(f"Capture {label} template?"):
                coords = prompt_roi(label)
                crop = panel_frame[coords[1] : coords[1] + coords[3], coords[0] : coords[0] + coords[2]]
                rel = f"ui/{ui_key}.png"
                save_template(crop, self.templates_dir / rel)
                self.config.templates[ui_key] = rel

        print("\n=== Step 5: Donatable slot colors ===")
        troop_slot = prompt_roi("A donatable TROOP slot (single cell)")
        self.config.colors["donatable_troop"] = sample_center_color(panel_frame, troop_slot)

        spell_slot = prompt_roi("A donatable SPELL slot (single cell)")
        self.config.colors["donatable_spell"] = sample_center_color(panel_frame, spell_slot)

        print("\n=== Step 6: Grid configuration ===")
        print("Enter grid settings (press Enter for defaults).")
        raw = input("Troop bar cols [8]: ").strip()
        troop_cols = int(raw) if raw else 8
        raw = input("Spell bar cols [5]: ").strip()
        spell_cols = int(raw) if raw else 5
        raw = input("Siege bar cols [3]: ").strip()
        siege_cols = int(raw) if raw else 3
        raw = input("Request header cols [6]: ").strip()
        req_cols = int(raw) if raw else 6

        self.config.grid = {
            "troop_bar": {"cols": troop_cols, "rows": 1},
            "spell_bar": {"cols": spell_cols, "rows": 1},
            "siege_bar": {"cols": siege_cols, "rows": 1},
            "request": {"cols": req_cols, "rows": 1},
        }

        print("\n=== Step 7: Unit templates ===")
        self._capture_unit_templates(panel_frame)

        if prompt_yes_no("Capture loading screen template (optional)?"):
            print("Relaunch CoC to show loading screen, then press Enter.")
            input()
            loading_frame = self.capture.screenshot()
            coords = prompt_roi("Loading screen distinctive region")
            crop = loading_frame[coords[1] : coords[1] + coords[3], coords[0] : coords[0] + coords[2]]
            rel = "ui/loading.png"
            save_template(crop, self.templates_dir / rel)
            self.config.templates["loading"] = rel

        if prompt_yes_no("Capture popup dismiss button template (optional)?"):
            print("Show a dismissible popup/event screen, then press Enter.")
            input()
            popup_frame = self.capture.screenshot()
            coords = prompt_roi("Popup close/dismiss button region")
            crop = popup_frame[coords[1] : coords[1] + coords[3], coords[0] : coords[0] + coords[2]]
            rel = "ui/popup_dismiss.png"
            save_template(crop, self.templates_dir / rel)
            self.config.templates["popup_dismiss"] = rel

        save_calibrated(self.config)
        logger.info("Calibration saved to data/calibrated.yaml")
        print("\nCalibration complete!")

    def _capture_unit_templates(self, panel_frame) -> None:
        units_by_category: dict[str, list[str]] = {"troop": [], "spell": [], "siege": []}
        for unit_id, info in self.config.units.items():
            units_by_category.setdefault(info.category, []).append(unit_id)

        for category in ("troop", "spell", "siege"):
            print(f"\n--- {category.upper()} templates ---")
            for unit_id in units_by_category.get(category, []):
                if not prompt_yes_no(f"Capture template for '{unit_id}'?"):
                    continue
                print(f"Ensure '{unit_id}' icon is visible in the donation panel.")
                input("Press Enter to capture...")
                frame = self.capture.screenshot()
                coords = prompt_roi(f"{unit_id} icon region")
                crop = frame[coords[1] : coords[1] + coords[3], coords[0] : coords[0] + coords[2]]
                rel = f"units/{unit_id}.png"
                save_template(crop, self.templates_dir / rel)
                self.config.unit_templates[unit_id] = rel
                logger.info("Saved template for {}", unit_id)


def main() -> None:
    setup_logging(debug=False)
    wizard = CalibrationWizard()
    wizard.run()


if __name__ == "__main__":
    main()
