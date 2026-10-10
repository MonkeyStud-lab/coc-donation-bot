"""Calibration checklist shared by terminal, desktop and browser."""
from dataclasses import dataclass
from coc_bot.config import BotConfig

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
                "donation_elixir_selected",
                "Selected elixir indicator",
                "template",
                description="Open a donation panel, select the LEFT elixir button, then box the WHOLE selected button including its border and background.",
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
    if part.key == "donation_elixir_selected":
        return bool(config.templates.get(key)) and bool(config.rois.get(key))
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


