"""Logging-only game-phase tracker with expected vs unexpected transitions.

Does not block actions — unexpected transitions only warn in the log so we can
spot desync (e.g. donating → in battle) without changing bot behavior.
"""

from __future__ import annotations

from enum import Enum

from loguru import logger


class GameState(str, Enum):
    """High-level phase the bot believes the game is in."""

    BOOT = "boot"
    UNKNOWN = "unknown"
    HOME = "home"
    CLAN_CHAT = "clan_chat"
    SCROLLING_CHAT = "scrolling_chat"
    OPENING_DONATION = "opening_donation"
    DONATING = "donating"
    ATTACK_MENU = "attack_menu"
    MATCHMAKING = "matchmaking"
    IN_BATTLE = "in_battle"
    BATTLE_RESULTS = "battle_results"
    RETURNING_HOME = "returning_home"
    RECOVERING = "recovering"
    ON_BREAK = "on_break"


# DonationBot._state string → GameState (coarse "farm" is handled inside AttackFarmer).
LOOP_STATE_TO_GAME: dict[str, GameState] = {
    "boot": GameState.BOOT,
    "scan_chat": GameState.CLAN_CHAT,
    "scroll_chat": GameState.SCROLLING_CHAT,
    "open_donation": GameState.OPENING_DONATION,
    "donate": GameState.DONATING,
    "ensure_chat": GameState.CLAN_CHAT,
}

# Frequent chat idle chatter — log at debug when expected.
_NOISY_OK_PAIRS: frozenset[tuple[GameState, GameState]] = frozenset(
    {
        (GameState.CLAN_CHAT, GameState.SCROLLING_CHAT),
        (GameState.SCROLLING_CHAT, GameState.CLAN_CHAT),
    }
)

_ALL = frozenset(GameState)

# Sanity graph only — unexpected transitions still apply (logging-only).
_VALID_TRANSITIONS: dict[GameState, frozenset[GameState]] = {
    GameState.BOOT: frozenset(
        {
            GameState.CLAN_CHAT,
            GameState.HOME,
            GameState.ON_BREAK,
            GameState.RECOVERING,
            GameState.UNKNOWN,
            GameState.BOOT,
        }
    ),
    GameState.UNKNOWN: _ALL,
    GameState.HOME: frozenset(
        {
            GameState.CLAN_CHAT,
            GameState.ATTACK_MENU,
            GameState.RECOVERING,
            GameState.ON_BREAK,
            GameState.UNKNOWN,
            GameState.RETURNING_HOME,
        }
    ),
    GameState.CLAN_CHAT: frozenset(
        {
            GameState.SCROLLING_CHAT,
            GameState.OPENING_DONATION,
            GameState.HOME,
            GameState.ATTACK_MENU,
            GameState.RECOVERING,
            GameState.ON_BREAK,
            GameState.UNKNOWN,
            GameState.CLAN_CHAT,
        }
    ),
    GameState.SCROLLING_CHAT: frozenset(
        {
            GameState.CLAN_CHAT,
            GameState.OPENING_DONATION,
            GameState.RECOVERING,
            GameState.HOME,
            GameState.UNKNOWN,
            GameState.SCROLLING_CHAT,
        }
    ),
    GameState.OPENING_DONATION: frozenset(
        {
            GameState.DONATING,
            GameState.SCROLLING_CHAT,
            GameState.CLAN_CHAT,
            GameState.RECOVERING,
            GameState.UNKNOWN,
        }
    ),
    GameState.DONATING: frozenset(
        {
            GameState.CLAN_CHAT,
            GameState.RECOVERING,
            GameState.UNKNOWN,
            GameState.SCROLLING_CHAT,
        }
    ),
    GameState.ATTACK_MENU: frozenset(
        {
            GameState.MATCHMAKING,
            GameState.HOME,
            GameState.RECOVERING,
            GameState.UNKNOWN,
            GameState.CLAN_CHAT,
        }
    ),
    GameState.MATCHMAKING: frozenset(
        {
            GameState.IN_BATTLE,
            GameState.BATTLE_RESULTS,
            GameState.HOME,
            GameState.RETURNING_HOME,
            GameState.RECOVERING,
            GameState.UNKNOWN,
            GameState.CLAN_CHAT,
        }
    ),
    GameState.IN_BATTLE: frozenset(
        {
            GameState.BATTLE_RESULTS,
            GameState.RETURNING_HOME,
            GameState.RECOVERING,
            GameState.UNKNOWN,
            GameState.HOME,
        }
    ),
    GameState.BATTLE_RESULTS: frozenset(
        {
            GameState.RETURNING_HOME,
            GameState.HOME,
            GameState.RECOVERING,
            GameState.UNKNOWN,
            GameState.CLAN_CHAT,
        }
    ),
    GameState.RETURNING_HOME: frozenset(
        {
            GameState.HOME,
            GameState.CLAN_CHAT,
            GameState.RECOVERING,
            GameState.UNKNOWN,
            GameState.BATTLE_RESULTS,
        }
    ),
    GameState.RECOVERING: _ALL,
    GameState.ON_BREAK: frozenset(
        {
            GameState.CLAN_CHAT,
            GameState.HOME,
            GameState.BOOT,
            GameState.RECOVERING,
            GameState.UNKNOWN,
        }
    ),
}


_ACTIVITY_BY_STATE: dict[GameState, str] = {
    GameState.CLAN_CHAT: "Watching clan chat",
    GameState.SCROLLING_CHAT: "Scrolling clan chat",
    GameState.OPENING_DONATION: "Opening donation panel",
    GameState.DONATING: "Donating…",
    GameState.ATTACK_MENU: "Opening Attack menu",
    GameState.MATCHMAKING: "Searching for a farm match",
    GameState.IN_BATTLE: "Farm battle in progress",
    GameState.BATTLE_RESULTS: "Farm battle finished — returning home",
    GameState.RETURNING_HOME: "Returning home after farm",
    GameState.ON_BREAK: "Session break — Clash closed until the break ends",
    GameState.RECOVERING: "Recovering (reopening chat)",
    GameState.HOME: "On home village",
}


def _log_activity_for_state(state: GameState, *, reason: str = "") -> None:
    """Emit a short human-facing Activity line for important phase changes."""
    message = _ACTIVITY_BY_STATE.get(state)
    if not message:
        return
    if reason:
        logger.info("Activity: {} ({})", message, reason)
    else:
        logger.info("Activity: {}", message)


class GameStateMachine:
    """Tracks game phase and logs whether each transition looks logical."""

    def __init__(self, initial: GameState = GameState.BOOT) -> None:
        self._state = initial
        logger.info("GameState: initialized → {}", self._state.value)

    @property
    def state(self) -> GameState:
        return self._state

    def transition(self, new_state: GameState, *, reason: str = "") -> bool:
        """
        Move to *new_state* (never blocked).

        Returns True if the transition was in the expected graph, False if unexpected.
        Same-state calls are no-ops and count as expected.
        """
        old = self._state
        if new_state == old:
            return True

        allowed = _VALID_TRANSITIONS.get(old, _ALL)
        expected = new_state in allowed
        self._state = new_state

        suffix = f" ({reason})" if reason else ""
        if expected:
            if (old, new_state) in _NOISY_OK_PAIRS:
                logger.debug(
                    "GameState [ok]: {} → {}{}",
                    old.value,
                    new_state.value,
                    suffix,
                )
            else:
                logger.info(
                    "GameState [ok]: {} → {}{}",
                    old.value,
                    new_state.value,
                    suffix,
                )
                _log_activity_for_state(new_state, reason=reason)
            return True

        _log_activity_for_state(new_state, reason=reason or "unexpected")

        allowed_names = ", ".join(sorted(s.value for s in allowed)) or "(none)"
        logger.warning(
            "GameState [unexpected]: {} → {}{} — not a logical transition "
            "(allowed from {}: {})",
            old.value,
            new_state.value,
            suffix,
            old.value,
            allowed_names,
        )
        return False

    def note_loop_state(self, loop_state: str, *, reason: str = "") -> bool | None:
        """Map DonationBot string states; ignore unknown keys (e.g. coarse 'farm')."""
        mapped = LOOP_STATE_TO_GAME.get(loop_state)
        if mapped is None:
            return None
        return self.transition(mapped, reason=reason or f"loop:{loop_state}")

    def reset(self, state: GameState = GameState.UNKNOWN, *, reason: str = "reset") -> None:
        old = self._state
        self._state = state
        logger.info(
            "GameState [reset]: {} → {} ({})",
            old.value,
            state.value,
            reason,
        )
