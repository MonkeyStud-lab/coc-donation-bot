"""Ephemeral donation geometry; never writes or replaces user calibration."""
from dataclasses import dataclass

from coc_bot.vision.donation_calibration import suggest_donation


@dataclass(frozen=True)
class DonationLayout:
    width: int
    height: int
    troops: tuple[int, int, int, int]
    spells: tuple[int, int, int, int]
    elixir: tuple[int, int, int, int]

    @classmethod
    def detect(cls, frame):
        result = suggest_donation(frame)
        if not result['supported']:
            return None
        boxes = {p['part']: tuple(p['selection']) for p in result['proposals']}
        h, w = frame.shape[:2]
        return cls(w, h, boxes['donation_troop_bar'], boxes['donation_spell_bar'],
                   boxes['donation_elixir_button'])

    def agrees(self, other):
        if other is None or (self.width, self.height) != (other.width, other.height):
            return False
        tolerance = max(2, round(self.width * .003))
        return all(abs(a-b) <= tolerance
                   for left, right in ((self.troops, other.troops),
                                       (self.spells, other.spells), (self.elixir, other.elixir))
                   for a, b in zip(left, right))

    def bar(self, key):
        if key == 'donation_troop_bar':
            return self.troops, {'cols': 7, 'rows': 2}
        if key == 'donation_spell_bar':
            return self.spells, {'cols': 7, 'rows': 1}
        return None

    @property
    def elixir_center(self):
        x, y, w, h = self.elixir
        return x + w // 2, y + h // 2


class DonationLayoutSession:
    """Require agreement on entry and invalidate permanently on lost geometry.

    A changed screen must never fall through to saved coordinates mid-donation.
    The caller creates a new session for the next request. Resource selection is
    deliberately NOT inferred here; the separate elixir verifier still applies.
    """
    def __init__(self, layout):
        self.layout = layout
        self.valid = True

    def observe(self, frame):
        if not self.valid:
            return None
        current = DonationLayout.detect(frame)
        if not self.layout.agrees(current):
            self.valid = False
            return None
        return current
