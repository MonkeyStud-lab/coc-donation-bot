"""Layman calibration instructions for Setup (mirrors terminal wizard prompts)."""

from __future__ import annotations

from dataclasses import dataclass

from coc_bot.calibration.wizard import STEPS


@dataclass(frozen=True)
class CalibInstruction:
    """What the user should prepare in Clash, then what to do in the picker."""

    prepare: str
    do: str

    def as_text(self) -> str:
        return f"1) In Clash of Clans:\n{self.prepare}\n\n2) Then in the bot:\n{self.do}"


# Step-level “where should I be?” (used when a whole step is selected).
STEP_INSTRUCTIONS: dict[str, str] = {
    "home": (
        "Go to your home village (the main base screen).\n"
        "Clan chat must be CLOSED — you should see the chat bubble that opens chat."
    ),
    "clan_chat": (
        "OPEN clan chat.\n"
        "Do NOT open a donation panel yet — just the normal chat messages."
    ),
    "donation_request": (
        "OPEN clan chat and find a request that shows a green Donate button.\n"
        "(If nobody is requesting, ask a clanmate or wait for one.)"
    ),
    "donation_panel": (
        "OPEN clan chat, then tap Donate on a request so the white donation panel is open.\n"
        "At the top you should see “Donation Resource” with elixir (left) and gem (right) toggles."
    ),
    "slot_colors": (
        "OPEN the donation panel (tap Donate on a request).\n"
        "Ideally show both a colored slot you can donate and a grey slot you cannot."
    ),
    "grid": (
        "OPEN the donation panel so the troop bar and spell bar are visible."
    ),
    "farm": (
        "Start on your home village with chat closed for Attack.\n"
        "Later parts need the Attack menu, then a finished battle for Return Home.\n"
        "Leave your farm army as the active army preset."
    ),
    "optional": (
        "Only if you want these extras: open Chat Groups (globe) to teach that "
        "screen and the swords tab back to clan chat, or show loading / a popup."
    ),
}


# Per-part instructions (key = CalibrationPart.key).
PART_INSTRUCTIONS: dict[str, CalibInstruction] = {
    "frame_width": CalibInstruction(
        prepare=(
            "Go to your home village (chat closed).\n"
            "Make sure Waydroid/Clash is visible so the bot can take a screenshot."
        ),
        do=(
            "Confirm the screen size when asked.\n"
            "Nothing to click on the screenshot — the bot reads the image size."
        ),
    ),
    "home": CalibInstruction(
        prepare="Stay on your home village (chat closed).",
        do=(
            "Draw a box around something unique on the home village "
            "(optional — skip if you prefer).\n"
            "Then Confirm."
        ),
    ),
    "open_chat": CalibInstruction(
        prepare=(
            "Go to your home village.\n"
            "Clan chat must be CLOSED so you can see the chat bubble / tab that OPENS chat."
        ),
        do=(
            "Choose “Yes” to crop an image (recommended).\n"
            "Draw a tight box around the chat bubble that opens clan chat, then Confirm.\n"
            "Or choose “No” and click once in the center of that bubble."
        ),
    ),
    "chat_panel": CalibInstruction(
        prepare=(
            "OPEN clan chat.\n"
            "Do NOT open the donation panel — only the chat list."
        ),
        do=(
            "Draw a box around the whole clan chat panel (the area with messages), "
            "then Confirm."
        ),
    ),
    "chat_requests": CalibInstruction(
        prepare="OPEN clan chat (donation panel closed).",
        do=(
            "Draw a box around the part of chat where Donate requests appear "
            "(usually the message area), then Confirm."
        ),
    ),
    "clan_chat": CalibInstruction(
        prepare=(
            "OPEN clan chat.\n"
            "Pick something you see in chat that disappears when the donation panel covers it "
            "(good: the selected Clan tab or chat header)."
        ),
        do="Draw a box around that chat-only UI, then Confirm.",
    ),
    "close_chat": CalibInstruction(
        prepare=(
            "OPEN clan chat.\n"
            "Find the small orange “<” tab on the right edge that CLOSES chat.\n"
            "(This is different from the bubble that opens chat on home.)"
        ),
        do=(
            "Crop or click the center of that orange close tab, then Confirm."
        ),
    ),
    "chat_request_jump": CalibInstruction(
        prepare=(
            "OPEN clan chat.\n"
            "Scroll until you see the exclamation / jump icon at the TOP or BOTTOM of the chat "
            "(it appears when there is a request off-screen)."
        ),
        do="Draw a box around that exclamation icon, then Confirm.",
    ),
    "chat_scroll_down": CalibInstruction(
        prepare=(
            "OPEN clan chat.\n"
            "If you already captured the exclamation jump icon, you can skip this.\n"
            "Otherwise scroll until the bottom jump icon is visible."
        ),
        do="Draw a box around the bottom jump icon, then Confirm.",
    ),
    "donate_button": CalibInstruction(
        prepare=(
            "OPEN clan chat.\n"
            "Find a request that shows a green Donate button on the message "
            "(not inside the donation panel yet)."
        ),
        do="Draw a tight box around the green Donate button, then Confirm.",
    ),
    "donation_panel": CalibInstruction(
        prepare=(
            "OPEN clan chat, tap Donate on a request, and leave the white donation panel open."
        ),
        do=(
            "Draw a tight box around the “Donation Resource” title text at the top of the panel "
            "(optional but helpful), then Confirm."
        ),
    ),
    "donation_elixir_button": CalibInstruction(
        prepare=(
            "Keep the donation panel OPEN.\n"
            "At the top, next to “Donation Resource”, find the two toggles:\n"
            "  LEFT  = pink Elixir + Dark Elixir drops (this one)\n"
            "  RIGHT = green Gem (do not pick this)"
        ),
        do=(
            "Crop or click the CENTER of the LEFT elixir toggle "
            "(not the gem button), then Confirm.\n"
            "The bot taps this before donating so costs stay in elixir, not gems."
        ),
    ),
    "donation_troop_bar": CalibInstruction(
        prepare=(
            "Keep the donation panel OPEN.\n"
            "You should see the row of troop / siege icons you can donate."
        ),
        do=(
            "Draw a box around the whole troop + siege bar "
            "(all the troop icons in that strip), then Confirm."
        ),
    ),
    "donation_spell_bar": CalibInstruction(
        prepare="Keep the donation panel OPEN so the spell icons are visible.",
        do="Draw a box around the whole spell bar, then Confirm.",
    ),
    "tap_outside_donation": CalibInstruction(
        prepare=(
            "Keep the donation panel OPEN.\n"
            "There is no X button — you close it by tapping the dimmed area outside the panel."
        ),
        do=(
            "Click once on a safe empty spot OUTSIDE the white panel "
            "(dimmed chat/background), then Confirm."
        ),
    ),
    "donatable_troop": CalibInstruction(
        prepare=(
            "OPEN the donation panel.\n"
            "Show at least one COLORED troop or siege slot you can donate."
        ),
        do=(
            "Draw a small box on that colored troop/siege slot "
            "(the bot samples the center color), then Confirm."
        ),
    ),
    "disabled_troop": CalibInstruction(
        prepare=(
            "OPEN the donation panel.\n"
            "Show a GREY troop or siege slot that cannot be donated."
        ),
        do="Draw a small box on that grey troop/siege slot, then Confirm.",
    ),
    "donatable_spell": CalibInstruction(
        prepare=(
            "OPEN the donation panel.\n"
            "Show at least one COLORED spell slot you can donate."
        ),
        do="Draw a small box on that colored spell slot, then Confirm.",
    ),
    "disabled_spell": CalibInstruction(
        prepare=(
            "OPEN the donation panel.\n"
            "Show a GREY spell slot that cannot be donated."
        ),
        do="Draw a small box on that grey spell slot, then Confirm.",
    ),
    "troop_bar": CalibInstruction(
        prepare=(
            "OPEN the donation panel so the troop + siege icons are visible.\n"
            "(Calibrate the troop + siege bar area in Donation panel first if this fails.)"
        ),
        do=(
            "Draw a box around ALL visible troop/siege slot cells "
            "(top-left corner, then bottom-right), Confirm, "
            "then enter how many columns and rows you see."
        ),
    ),
    "spell_bar": CalibInstruction(
        prepare=(
            "OPEN the donation panel so the spell icons are visible.\n"
            "(Calibrate the spell bar area in Donation panel first if this fails.)"
        ),
        do=(
            "Draw a box around ALL visible spell slot cells, Confirm, "
            "then enter columns and rows."
        ),
    ),
    "attack_button": CalibInstruction(
        prepare=(
            "Go to your home village.\n"
            "CLOSE clan chat so you see the Attack button (usually bottom-left)."
        ),
        do=(
            "Crop or click the center of the Attack! button, then Confirm."
        ),
    ),
    "unranked_battle": CalibInstruction(
        prepare=(
            "From home, open the Attack menu so you see Ranked vs Battle.\n"
            "You can tap Attack yourself, then continue."
        ),
        do=(
            "Crop or click the center of unranked Battle "
            "(NOT Ranked), then Confirm."
        ),
    ),
    "find_match": CalibInstruction(
        prepare=(
            "Optional: if “Find a Match” is a separate button after Battle, show that screen.\n"
            "If Battle already starts the search, you can skip this part."
        ),
        do="Crop or click the center of Find a Match, then Confirm.",
    ),
    "return_home": CalibInstruction(
        prepare=(
            "Finish (or wait for) an unranked battle until you see Return Home / OK."
        ),
        do="Crop or click the center of Return Home, then Confirm.",
    ),
    "deploy_sequence": CalibInstruction(
        prepare=(
            "Enter an unranked battle first (battlefield visible).\n"
            "Leave your farm army as the active preset."
        ),
        do=(
            "The bot will pan the camera, then open a click editor.\n"
            "Click your deploy taps in order (army bar, then map), then save."
        ),
    ),
    "chat_groups": CalibInstruction(
        prepare=(
            "OPEN clan chat, then tap the globe icon (under the orange “<” tab) "
            "so you see “Chat Groups” and the green “+ New” button."
        ),
        do=(
            "Draw a tight box around the “Chat Groups” title text "
            "(or the green “+ New” button), then Confirm.\n"
            "The bot uses this after donating to detect if global chat opened by mistake."
        ),
    ),
    "clan_chat_tab": CalibInstruction(
        prepare=(
            "Keep Chat Groups OPEN (globe drawer with “Chat Groups” title).\n"
            "On the right edge of the chat, find the TOP icon: a bubble with "
            "crossed swords / shield (above the orange “<” tab)."
        ),
        do=(
            "Crop or click the CENTER of that swords tab, then Confirm.\n"
            "When the bot is stuck in Chat Groups, it taps this to return to clan chat."
        ),
    ),
    "loading": CalibInstruction(
        prepare="Optional: relaunch Clash so the loading screen is showing.",
        do="Draw a box around a unique part of the loading screen, then Confirm.",
    ),
    "popup_dismiss": CalibInstruction(
        prepare="Optional: show a popup that has a clear dismiss / OK button.",
        do="Draw a box around the dismiss/OK control, then Confirm.",
    ),
    "popup": CalibInstruction(
        prepare="Optional: show a popup you want the bot to recognize.",
        do="Draw a box around a unique part of that popup, then Confirm.",
    ),
}


def step_prepare_text(step_id: str) -> str:
    return STEP_INSTRUCTIONS.get(
        step_id,
        "Open Clash of Clans and show the screen this step is about.",
    )


def part_instruction(step_id: str, part_key: str) -> CalibInstruction:
    if part_key in PART_INSTRUCTIONS:
        return PART_INSTRUCTIONS[part_key]
    # Fallback: step prep + generic action from part label.
    step = STEPS.get(step_id)
    label = part_key
    if step is not None:
        for part in step.parts:
            if part.key == part_key:
                label = part.label
                break
    return CalibInstruction(
        prepare=step_prepare_text(step_id),
        do=f"Follow the on-screen picker for “{label}”, then Confirm.",
    )


def format_part_instruction(step_id: str, part_key: str, *, title: str | None = None) -> str:
    instr = part_instruction(step_id, part_key)
    head = title or part_key
    step = STEPS.get(step_id)
    if step is not None:
        for part in step.parts:
            if part.key == part_key:
                head = part.label
                break
    return f"{head}\n\n{instr.as_text()}"


def format_step_instruction(step_id: str) -> str:
    step = STEPS.get(step_id)
    title = step.title if step else step_id
    return f"{title}\n\nIn Clash of Clans:\n{step_prepare_text(step_id)}"
