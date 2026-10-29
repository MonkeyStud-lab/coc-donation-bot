"""Plain-language UX helpers for Home / Setup / Tools polish."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from coc_bot.calibration.wizard import STEP_IDS, STEPS, CalibrationPart, part_is_configured
from coc_bot.config import BotConfig, load_config, normalize_farm_deploy_sequence
from coc_bot.gui.calib_instructions import STEP_INSTRUCTIONS, part_instruction
from coc_bot.runtime.game_state import GameState

# Step-level “where should I be?” tips (also used by Setup detail panel).
STEP_SCREEN_HINTS = STEP_INSTRUCTIONS


@dataclass(frozen=True)
class MissingCalibration:
    step_id: str
    part: CalibrationPart

    @property
    def label(self) -> str:
        step = STEPS[self.step_id]
        return f"{step.title} → {self.part.label}"

    @property
    def hint(self) -> str:
        return part_instruction(self.step_id, self.part.key).as_text()


@dataclass(frozen=True)
class FarmReadiness:
    farm_enabled: bool
    farm_calibrated: bool
    has_deploy_sequence: bool
    requires_sequence: bool = True

    @property
    def ready_for_manual(self) -> bool:
        return self.farm_calibrated and (not self.requires_sequence or self.has_deploy_sequence)

    @property
    def ready_for_auto(self) -> bool:
        return self.ready_for_manual and self.farm_enabled

    def summary_lines(self) -> list[str]:
        lines = [
            f"{'✓' if self.farm_calibrated else '✗'}  Farm taps calibrated (Attack / Battle / Return Home)",
            (f"{'✓' if self.has_deploy_sequence else '✗'}  Deploy tap sequence programmed"
             if self.requires_sequence else '✓  Army and plan checks run before deployment'),
            f"{'✓' if self.farm_enabled else '○'}  Auto-farm enabled in Settings"
            + ("" if self.farm_enabled else " (optional for Farm attack now)"),
        ]
        return lines


@dataclass(frozen=True)
class FixItRecipe:
    id: str
    title: str
    body: str
    action_label: str
    action: str  # connect_adb | setup | tools_health | export_debug | calib_missing


def next_missing_calibration(config: BotConfig | None = None) -> MissingCalibration | None:
    """First required part that is not configured."""
    config = config or load_config()
    for step_id in STEP_IDS:
        for part in STEPS[step_id].parts:
            if part.optional:
                continue
            if not part_is_configured(config, part):
                return MissingCalibration(step_id=step_id, part=part)
    return None


def farm_readiness(config: BotConfig | None = None) -> FarmReadiness:
    config = config or load_config()
    seq = normalize_farm_deploy_sequence(config.farm_deploy_sequence)
    return FarmReadiness(
        farm_enabled=bool(config.farm_enabled),
        farm_calibrated=bool(config.farm_calibrated),
        has_deploy_sequence=bool(seq.get("taps")),
        requires_sequence=config.farm_engine=='sequence',
    )


def live_status_label(
    *,
    running: bool,
    practice: bool,
    oneshot_farm: bool,
    game_state: GameState | None,
    on_break: bool,
    loop_state: str | None = None,
) -> tuple[str, str]:
    """
    Return (label, role) for the Home run chip.

    role: secondary | success | accent | danger
    """
    if oneshot_farm:
        return "Farming…", "accent"
    if on_break:
        return "On break", "accent"
    if not running:
        return "Stopped", "secondary"
    if practice:
        prefix = "Practice · "
    else:
        prefix = ""

    if game_state == GameState.ON_BREAK:
        return f"{prefix}On break".strip(), "accent"
    if game_state in (
        GameState.ATTACK_MENU,
        GameState.MATCHMAKING,
        GameState.IN_BATTLE,
        GameState.BATTLE_RESULTS,
        GameState.RETURNING_HOME,
    ):
        return f"{prefix}Farming…".strip(), "accent"
    if game_state in (GameState.DONATING, GameState.OPENING_DONATION):
        return f"{prefix}Donating…".strip(), "success"
    if game_state == GameState.SCROLLING_CHAT:
        return f"{prefix}Scrolling chat".strip(), "success"
    if game_state in (GameState.CLAN_CHAT, GameState.HOME):
        return f"{prefix}Watching chat".strip(), "success"
    if game_state == GameState.RECOVERING:
        return f"{prefix}Recovering…".strip(), "accent"
    if loop_state == "farm":
        return f"{prefix}Farming…".strip(), "accent"
    return f"{prefix}Running".strip(), "success"


def break_timer_caption(*, on_break: bool) -> str:
    return "BREAK LEFT" if on_break else "NEXT BREAK"


FIXIT_RECIPES: tuple[FixItRecipe, ...] = (
    FixItRecipe(
        "adb_offline",
        "ADB is offline",
        "Waydroid/emulator isn’t linked. Start the game, then Connect ADB.",
        "Connect ADB",
        "connect_adb",
    ),
    FixItRecipe(
        "not_calibrated",
        "Start says not calibrated",
        "Required Setup steps are missing. Calibrate the next missing item.",
        "Calibrate what’s missing",
        "calib_missing",
    ),
    FixItRecipe(
        "taps_miss",
        "Taps miss buttons",
        "Recalibrate that button/region in Setup (Backup first if unsure).",
        "Open Setup",
        "setup",
    ),
    FixItRecipe(
        "no_slots",
        "No donation slots found",
        "Recalibrate slot colors and the troop/spell grid with the donation panel open.",
        "Open Setup",
        "setup",
    ),
    FixItRecipe(
        "stuck",
        "Bot looks stuck",
        "Try Tools → Classify screen or Open clan chat. Export debug if you need help.",
        "ADB health check",
        "tools_health",
    ),
    FixItRecipe(
        "need_logs",
        "Need logs for help",
        "Copy recent logs or export a debug bundle from Home → Activity.",
        "Export debug",
        "export_debug",
    ),
)


def settings_snapshot(values: dict[str, Any]) -> dict[str, str]:
    """Normalize widget values for dirty comparison."""
    out: dict[str, str] = {}
    for key, raw in values.items():
        if isinstance(raw, bool):
            out[key] = "1" if raw else "0"
        else:
            out[key] = str(raw).strip()
    return out
