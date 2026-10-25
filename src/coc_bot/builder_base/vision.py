"""Builder Base anchors and the inspected English landscape layout."""
from pathlib import Path
import re

import cv2
import numpy as np

from coc_bot.upgrades.vision import UpgradeReader, compact, crop, resource_amount

ASSETS = Path(__file__).with_name('assets')


class BuilderReader(UpgradeReader):
    def __init__(self, stop=None):
        super().__init__(stop)
        self.templates = {}

    def find(self, frame, name, box=(0, 0, 1, 1), threshold=.88):
        if name not in self.templates:
            self.templates[name] = cv2.imread(str(ASSETS / (name+'.png')))
        template = self.templates[name]
        if template is None:
            return None
        h, w = frame.shape[:2]
        if not 1.6 < w/h < 1.95:
            return None
        region = crop(frame, box)
        best = None
        for factor in (.96, 1, 1.04):
            scale = w/1853*factor
            ref = cv2.resize(template, None, fx=scale, fy=scale)
            rh, rw = ref.shape[:2]
            if region.shape[0] < rh or region.shape[1] < rw:
                continue
            _, score, _, point = cv2.minMaxLoc(cv2.matchTemplate(region, ref, cv2.TM_CCOEFF_NORMED))
            observed = region[point[1]:point[1]+rh, point[0]:point[0]+rw]
            bright = observed.mean() >= ref.mean()*.78
            if bright and score >= threshold and (best is None or score > best[0]):
                best = (score, (round(w*box[0])+point[0]+rw//2,
                                round(h*box[1])+point[1]+rh//2))
        return best[1] if best else None

    def home(self, frame):
        return bool(self.find(frame, 'builder_gold', (.94, 0, 1, .09))
                    and self.find(frame, 'builder_axes', (0, .80, .13, .98)))

    def battle(self, frame):
        return bool(self.find(frame, 'defender', (.045, .012, .145, .06))
                    and self.find(frame, 'attacker', (.875, .012, .97, .06))
                    and (self.find(frame, 'battle_starts', (.43, .012, .57, .055))
                         or self.find(frame, 'battle_ends', (.43, .012, .57, .055))))

    def attack_menu(self, frame):
        return bool(self.find(frame, 'start_attack', (.38, .14, .66, .24))
                    and self.find(frame, 'find_now', (.65, .60, .84, .72)))

    def supported_army(self, frame):
        """First release accepts the inspected six-camp Night Witch army only."""
        return (self.attack_menu(frame)
                and bool(self.find(frame, 'menu_machine', (.17,.39,.224,.48)))
                and all(self.find(frame, 'menu_witch', (x,.39,x+.055,.48))
                        for x in (.227,.286,.345,.404,.463,.522)))

    def reward_button(self, frame):
        if (self.find(frame, 'star_bonus', (.38,.16,.62,.25))
                and self.find(frame, 'bonus_received', (.37,.50,.63,.60))):
            return self.find(frame, 'bonus_okay', (.42,.72,.58,.84))
        return None

    def menu_kind(self, frame):
        # The square Builder Gold icon distinguishes this from the identical
        # Home Village heading. Never infer village identity from that heading.
        if not self.find(frame, 'builder_gold', (.68, .02, .72, .08)):
            return None
        return super().menu_kind(frame)

    def availability(self, frame, kind):
        from coc_bot.upgrades.digits import read_digits
        if self.menu_kind(frame) != kind:
            return None
        box = {'buildings': (.775, .945, .81, .977),
               'research': (.915, .944, .954, .975)}.get(kind)
        if box is None:
            return None
        from coc_bot.upgrades.vision import text
        raw = read_digits(crop(frame, box), fraction=True) or text(crop(frame, box), fraction=True, stop=self.stop)
        match = re.fullmatch(r'([0-3])/([123])' if kind == 'buildings' else r'([01])/(1)', raw)
        if not match:
            return None
        free, total = map(int, match.groups())
        return (free, total) if free <= total else None

    def balances(self, frame):
        return {key: resource_amount(crop(frame, box), self.stop) for key, box in {
            'gold': (.56, .033, .679, .073),
            'elixir': (.56, .104, .679, .143),
        }.items()}

    def detail_close(self, frame):
        title = compact(self.label(frame, (.30, .035, .72, .09)))
        if title not in ('upgradetolevel','upgradeunits'):
            return None
        hsv = cv2.cvtColor(crop(frame, (.816, .025, .866, .11)), cv2.COLOR_BGR2HSV)
        red = cv2.bitwise_or(cv2.inRange(hsv, (0, 110, 120), (10, 255, 255)),
                            cv2.inRange(hsv, (170, 110, 120), (180, 255, 255)))
        if red.mean()/255 < .25:
            return None
        return round(frame.shape[1]*.839), round(frame.shape[0]*.064)

    def confirmation(self, frame, candidate):
        if self.detail_close(frame) is None:
            return None
        if compact(candidate.name) == 'nightwitch':
            return self.research_confirmation(frame,candidate)
        if compact(self.white_text(crop(frame, (.18, .14, .40, .19)))) != compact(candidate.name):
            return None
        # Builder building dialog has a single resource button, no Confirm text.
        price = resource_amount(crop(frame, (.415, .842, .543, .925)), self.stop)
        name = {'gold': 'confirm_gold'}.get(candidate.currency)
        if price != candidate.cost or not name:
            return None
        if not self.find(frame, name, (.546, .83, .597, .92), threshold=.84):
            return None
        green = cv2.inRange(cv2.cvtColor(crop(frame, (.418, .83, .59, .93)), cv2.COLOR_BGR2HSV),
                            (30, 70, 140), (90, 255, 255))
        if green.mean()/255 < .3:
            return None
        return {'point': (round(frame.shape[1]*.504), round(frame.shape[0]*.875)),
                'name': candidate.name, 'cost': price, 'currency': candidate.currency}

    def research_confirmation(self, frame, candidate):
        # This dialog does not print the troop's name. Require its distinctive
        # portrait AND ability title; a background menu row cannot prove identity.
        if (candidate.currency != 'elixir' or compact(candidate.name) != 'nightwitch'
                or not self.find(frame,'research_night_witch',(.20,.26,.33,.46))
                or not self.find(frame,'research_bat_swarm',(.20,.73,.34,.78))):
            return None
        price=resource_amount(crop(frame,(.68,.845,.787,.89)),self.stop)
        if price != candidate.cost or not self.find(frame,'research_elixir',(.788,.825,.824,.90)):
            return None
        green=cv2.inRange(cv2.cvtColor(crop(frame,(.675,.81,.832,.925)),cv2.COLOR_BGR2HSV),
                          (30,70,140),(90,255,255)).mean()/255
        if green < .3:
            return None
        return {'point':(round(frame.shape[1]*.751),round(frame.shape[0]*.87)),
                'name':candidate.name,'cost':price,'currency':candidate.currency}

    def running_detail(self, frame, candidate):
        # Closing a recognized research detail is safe even if its transition
        # has not finished. Only the menu timer and occupied lab confirm success.
        if compact(candidate.name)=='nightwitch':
            heading=compact(self.label(frame,(.30,.035,.72,.09)))
            unit=compact(self.label(frame,(.335,.18,.60,.23)))
            return bool(self.detail_close(frame) and heading=='upgradeunits'
                        and unit.startswith('nightwitchlevel'))
        return super().running_detail(frame,candidate)

    def white_text(self, image):
        from coc_bot.upgrades.vision import text
        white = cv2.inRange(cv2.cvtColor(image, cv2.COLOR_BGR2HSV), (0, 0, 190), (180, 75, 255))
        return text(255-white, stop=self.stop)

    def candidates(self, frame):
        from coc_bot.upgrades.vision import Candidate, amount, currency
        h, w = frame.shape[:2]
        headings = self._headings(frame)
        top = next((b+round(h*.008) for label, a, b in headings if label == 'suggestedupgrades'), None)
        bottom = next((a-round(h*.003) for label, a, b in headings if label == 'otherupgrades'), None)
        if top is None or bottom is None or bottom <= top:
            return [], False
        strip = frame[top:bottom, round(w*.905):round(w*.91)]
        mask = cv2.inRange(cv2.cvtColor(strip, cv2.COLOR_BGR2HSV), (7, 45, 120), (30, 190, 220))
        rows = mask.mean(axis=1)/255 > .70
        result = []; start = None
        for y, value in enumerate(np.append(rows, False)):
            if value and start is None:
                start = y
            elif not value and start is not None:
                a, b = top+start, top+y; height = b-a; start = None
                if height < h*.045:
                    continue
                # New construction uses green names; only existing white names qualify.
                name = self.white_text(frame[a+round(height*.04):a+round(height*.48), round(w*.775):round(w*.93)])
                price = resource_amount(frame[a+round(height*.46):b-round(height*.04), round(w*.85):round(w*.983)], self.stop)
                resource = currency(frame[a+round(height*.30):b, round(w*.979):round(w*.996)])
                if name and price and resource:
                    result.append(Candidate(name, price, resource, (round(w*.86), (a+b)//2)))
        return result, True

    def cards(self, frame):
        """Only inspected single-unit Night Witch and Battle Machine cards.

        Match artwork, never a slot number. Unknown troops remain untouched.
        Green health strips distinguish deployed units from ready units.
        """
        if not self.battle(frame):
            return []
        h, w = frame.shape[:2]
        result = []
        for index, cx in enumerate((.10, .189, .268, .347, .426, .505, .584, .663, .742, .821)):
            box = (cx-.036, .80, cx+.036, .99)
            unit = 'battle_machine' if index == 0 else 'night_witch'
            if index == 0 and self.find(frame, 'battle_copter', box, threshold=.86):
                unit = 'battle_copter'
            variants = [unit] + (['night_witch_active', 'night_witch_survivor'] if unit == 'night_witch'
                                else ['battle_machine_active'] if unit == 'battle_machine' else [])
            if not any(self.find(frame, name, box, threshold=.86) for name in variants):
                continue
            # Raised cards (number band at y=.79) are deployed. Health can be
            # green, yellow or red; second-stage survivors have health while
            # still waiting to deploy, so color alone is insufficient.
            band = crop(frame, (cx-.01, .796, cx+.025, .822))
            hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
            deployed = cv2.inRange(hsv, (90, 100, 180), (170, 255, 255)).mean()/255 > .6
            health = cv2.cvtColor(crop(frame, (cx-.025, .831, cx+.025, .858)), cv2.COLOR_BGR2HSV)
            deployed |= cv2.inRange(health, (10, 120, 160), (85, 255, 255)).mean()/255 > .12
            if index == 0:
                health = cv2.cvtColor(crop(frame, (cx-.025, .792, cx+.025, .811)), cv2.COLOR_BGR2HSV)
                deployed = cv2.inRange(health, (10, 120, 160), (85, 255, 255)).mean()/255 > .12
            art = cv2.cvtColor(crop(frame, (cx-.02, .90, cx+.02, .96)), cv2.COLOR_BGR2HSV)
            if (art[:, :, 1] > 60).mean() < .15:
                continue
            result.append({'slot': index, 'unit': unit, 'point': (round(w*cx), round(h*.90)),
                           'deployed': bool(deployed)})
        return result

    def result_button(self, frame):
        # Added from the inspected results layout; both text anchors required.
        if self.battle(frame):
            return None
        point = self.find(frame, 'return_home', (.25, .65, .75, 1))
        return point if point and self.find(frame, 'result_heading', (.20, .05, .80, .60)) else None
