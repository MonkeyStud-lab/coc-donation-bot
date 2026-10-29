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
            return cls.troop_only(frame)
        boxes = {p['part']: tuple(p['selection']) for p in result['proposals']}
        h, w = frame.shape[:2]
        return cls(w, h, boxes['donation_troop_bar'], boxes['donation_spell_bar'],
                   boxes['donation_elixir_button'])

    @classmethod
    def troop_only(cls,frame):
        import cv2
        import numpy as np
        from coc_bot.vision.battle_menu import _white_label
        h,w=frame.shape[:2]
        edges=cv2.Canny(frame,70,150)
        contours,_=cv2.findContours(edges,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
        cards=[]
        for contour in contours:
            x,y,cw,ch=cv2.boundingRect(contour)
            if not (w*.38<x<w*.91 and y>h*.25 and w*.058<cw<w*.077 and h*.14<ch<h*.17):continue
            if any(abs(x-a)<8 and abs(y-b)<8 for a,b,_,_ in cards):continue
            cards.append((x,y,cw,ch))
        if len(cards)<10:return None
        rows=[]
        for y in sorted(c[1] for c in cards):
            if not rows or y-rows[-1]>h*.03:rows.append(y)
        if len(rows)!=2:return None
        top=min(rows);stride=rows[1]-rows[0]
        first=max((sorted(c for c in cards if abs(c[1]-row)<h*.02) for row in rows),key=len)
        if len(first)<6:return None
        x=first[0][0];dx=float(np.median(np.diff([c[0] for c in first])))
        if not w*.065<dx<w*.08 or not h*.145<stride<h*.18:return None
        label=(x/w,(top-h*.145)/h,(x+w*.245)/w,(top-h*.085)/h)
        if _white_label(frame,label)!='donationresource':return None
        return cls(w,h,(x,top,round(dx*7),round(stride*2)),(0,0,0,0),
                   (round(x+dx*3.9),round(top-h*.16),round(dx),round(h*.09)))

    def agrees(self, other):
        if other is None or (self.width, self.height) != (other.width, other.height):
            return False
        tolerance = max(2, round(self.width * .003))
        return all(abs(a-b) <= tolerance
                   for left, right in ((self.troops, other.troops),
                                       (self.spells, other.spells), (self.elixir, other.elixir))
                   for a, b in zip(left, right))

    def bar(self, key):
        if key=='donation_spell_bar' and self.spells[2]==0:return None
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
