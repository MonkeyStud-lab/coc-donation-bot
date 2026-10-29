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

    def daily_reward_close(self, frame):
        """Only close the inspected daily calendar; never select its rewards."""
        footer=self.find(frame,'daily_reward_footer',(.30,.88,.70,.94),threshold=.97)
        if not footer:
            # The gold panel's background changes with the village behind it.
            # Match its complete native lettering, retaining the independent
            # bright title and Close checks below. Never lower all templates.
            ref=self.templates.get('daily_reward_footer')
            if ref is not None:
                mask=lambda a:cv2.inRange(cv2.cvtColor(a,cv2.COLOR_BGR2HSV),(0,0,200),(180,80,255))
                region=mask(cv2.resize(frame,(1853,1048))[922:985,555:1297])
                footer=cv2.minMaxLoc(cv2.matchTemplate(region,mask(ref),cv2.TM_CCOEFF_NORMED))[1]>=.97
        if (self.find(frame,'daily_reward_title',(.38,.12,.60,.19),threshold=.97) and footer):
            return (self.find(frame,'daily_reward_close_ready',(.82,.10,.87,.18),threshold=.97)
                    or self.find(frame,'daily_reward_close',(.82,.10,.87,.18),threshold=.97))
        return None

    def daily_reward_claim(self, frame):
        """The free calendar's whole green Claim button, excluding gray Claimed."""
        if self.daily_reward_close(frame) is None:return None
        return self.find(frame,'daily_reward_claim',(.13,.37,.86,.87),threshold=.97)

    def free_boat_confirmation(self, frame):
        if (self.find(frame,'setup_boat_title',(.37,.06,.64,.16),threshold=.94)
            and self.find(frame,'setup_boat_description',(.33,.59,.67,.68),threshold=.94)
            and self.find(frame,'setup_boat_free',(.93,.105,.99,.89),threshold=.94)):
            label=self.find(frame,'setup_boat_rebuild',(.40,.76,.61,.88),threshold=.94)
            if label:
                green=cv2.inRange(cv2.cvtColor(crop(frame,(.416,.754,.584,.875)),cv2.COLOR_BGR2HSV),
                                  (30,90,140),(90,255,255)).mean()/255
                if green>.55:return label
        return None

    def setup_boat_target(self,frame):
        """Locate the tutorial boat to inspect its actions, not to infer readiness."""
        from coc_bot.vision.battle_menu import home_build_control_visible
        if not home_build_control_visible(frame) or self.home(frame):return None
        point=self.find(frame,'setup_ready_boat',(.14,.12,.90,.80),threshold=.96)
        if point is None:return None
        h,w=frame.shape[:2];x,y=point
        box=(max(0,x/w-.055),max(0,y/h-.18),min(1,x/w+.055),max(0,y/h-.035))
        arrow=self.find(frame,'setup_ready_arrow',box,threshold=.96)
        if arrow is None:
            # The tutorial arrow stretches while bobbing. Its silhouette stays
            # the same; require that shape directly above the verified boat.
            reference=self.templates.get('setup_ready_arrow')
            def orange(image):return cv2.inRange(cv2.cvtColor(image,cv2.COLOR_BGR2HSV),(10,145,180),(36,255,255))
            def silhouette(contour,mask):
                a,b,bw,bh=cv2.boundingRect(contour);filled=np.zeros_like(mask)
                cv2.drawContours(filled,[contour],-1,255,-1)
                return cv2.resize(filled[b:b+bh,a:a+bw],(96,96),interpolation=cv2.INTER_NEAREST)>0
            if reference is not None:
                target=orange(reference);contours,_=cv2.findContours(target,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
                expected=silhouette(max(contours,key=cv2.contourArea),target) if contours else None
                region=orange(crop(frame,box));contours,_=cv2.findContours(region,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
                scale=w/1853
                for contour in contours:
                    a,b,bw,bh=cv2.boundingRect(contour)
                    if expected is None or not 60*scale<bw<150*scale or not 50*scale<bh<140*scale or cv2.contourArea(contour)<1800*scale*scale:continue
                    observed=silhouette(contour,region)
                    if (observed&expected).sum()/(observed|expected).sum()>=.94:
                        arrow=(round(w*box[0])+a+bw//2,round(h*box[1])+b+bh//2);break
        return point if arrow and abs(arrow[0]-x)<w*.025 and h*.045<y-arrow[1]<h*.18 else None

    def selected_boat_rebuild(self,frame):
        from coc_bot.vision.battle_menu import home_build_control_visible
        if not home_build_control_visible(frame):return None
        if (self.find(frame,'setup_selected_boat',(.43,.63,.56,.70),threshold=.96)
            and self.find(frame,'setup_selected_boat_free',(.45,.69,.55,.75),threshold=.96)):
            return self.find(frame,'setup_selected_boat_rebuild',(.44,.80,.55,.86),threshold=.96)
        return None

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

    def research_sorting(self,frame):
        """The inspected Star Laboratory popup sorts rows; it has no filters."""
        return bool(self.find(frame,'research_sorting_title',(.47,.125,.61,.185),threshold=.98)
                    and self.find(frame,'research_sort_cost_max',(.49,.20,.60,.275),threshold=.98)
                    and self.find(frame,'research_sort_cost_min',(.64,.20,.75,.275),threshold=.98))

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

    def storage_capacity(self, frame, resource):
        """Read the game's Max tooltip, with its resource-specific vertical position."""
        if resource not in ('gold','elixir') or not self.home(frame):return None
        box=(.75,.085,.99,.19) if resource=='gold' else (.75,.15,.99,.265)
        maximum=self.find(frame,'storage_max',box,threshold=.96)
        production=self.find(frame,'storage_production',(.75,box[1],.99,box[3]+.06),threshold=.94)
        if maximum is None or production is None:return None
        scale=frame.shape[1]/1853;x,y=maximum
        area=frame[round(y-19*scale):round(y+20*scale),round(x+32*scale):round(x+161*scale)]
        value=resource_amount(area,self.stop)
        return value if type(value) is int and 0<value<=20_000_000 else None

    def storage_capacities(self, runner):
        result={}
        for resource,y in (('gold',.055),('elixir',.12)):
            frame=runner.frame()
            if not self.home(frame):return result
            if self.storage_capacity(frame,resource) is None:
                for other,oy in (('gold',.055),('elixir',.12)):
                    if self.storage_capacity(frame,other) is not None:
                        runner.tap((round(frame.shape[1]*.87),round(frame.shape[0]*oy)))
                        runner.wait(.25);frame=runner.frame()
                # The balance toggles its tooltip. Never tap a resource icon or
                # purchase '+', and never toggle off an already-open target.
                runner.tap((round(frame.shape[1]*.87),round(frame.shape[0]*y)))
                runner.wait(.25)
            first=self.storage_capacity(runner.frame(),resource)
            second=self.storage_capacity(runner.frame(),resource)
            if first is not None and first==second:result[resource]=first
        frame=runner.frame()
        if self.home(frame):
            for resource,y in (('gold',.055),('elixir',.12)):
                if self.storage_capacity(frame,resource) is not None:
                    runner.tap((round(frame.shape[1]*.87),round(frame.shape[0]*y)))
        return result

    def detail_close(self, frame):
        title = compact(self.label(frame, (.30, .035, .72, .09)))
        # The native outlined 5 can read as S. This correction locates only
        # the non-spending close control; independent payment checks remain.
        if title in ('upgradetolevels','upgrradetolevels') and self.find(frame,'upgrade_benefits',(.48,.12,.81,.18),threshold=.97):
            title = 'upgradetolevel'
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
        if compact(candidate.name) in ('nightwitch','sneakyarcher','ragedbarbarian'):
            return self.research_confirmation(frame,candidate)
        named=compact(self.white_text(crop(frame, (.17, .14, .41, .19)))) == compact(candidate.name)
        if not named and compact(candidate.name)=='starlaboratory':
            named=self.find(frame,'upgrade_star_laboratory_title',(.17,.14,.41,.19),threshold=.97) is not None
        if not named:
            return None
        # Builder building dialog has a single resource button, no Confirm text.
        price = resource_amount(crop(frame, (.415, .842, .543, .925)), self.stop)
        from coc_bot.upgrades.vision import currency
        if price != candidate.cost or candidate.currency not in ('gold','elixir'):
            return None
        if currency(crop(frame,(.546,.83,.597,.92))) != candidate.currency:
            return None
        green = cv2.inRange(cv2.cvtColor(crop(frame, (.418, .83, .59, .93)), cv2.COLOR_BGR2HSV),
                            (30, 70, 140), (90, 255, 255))
        if green.mean()/255 < .3:
            return None
        return {'point': (round(frame.shape[1]*.504), round(frame.shape[0]*.875)),
                'name': candidate.name, 'cost': price, 'currency': candidate.currency}

    def research_confirmation(self, frame, candidate):
        if compact(candidate.name)=='sneakyarcher':
            heading=self.white_text(crop(frame,(.35,.04,.65,.095)))
            if (candidate.currency!='elixir' or not re.fullmatch(r'(?i)\s*upgrade\s+to\s+level\s+2\s*\??\s*',heading)
                or not self.find(frame,'research_sneaky_archer',(.24,.25,.42,.63),threshold=.96)
                or compact(self.label(frame,(.585,.256,.80,.292)))!='unlocksspecialabilitycloak'):
                return None
            price=resource_amount(crop(frame,(.71,.845,.787,.89)),self.stop)
            from coc_bot.upgrades.vision import currency
            if price!=candidate.cost or currency(crop(frame,(.788,.825,.824,.90)))!='elixir':return None
            green=cv2.inRange(cv2.cvtColor(crop(frame,(.675,.81,.832,.925)),cv2.COLOR_BGR2HSV),
                             (30,70,140),(90,255,255)).mean()/255
            if green<.3:return None
            return {'point':(round(frame.shape[1]*.751),round(frame.shape[0]*.87)),
                    'name':candidate.name,'cost':price,'currency':'elixir','target_level':2}
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
        if compact(candidate.name) in ('sneakyarcher','ragedbarbarian'):
            # This only authorizes closing the verified X, never another
            # payment. The active research timer/lab occupancy proves success.
            return self.detail_close(frame) is not None
        if compact(candidate.name)=='nightwitch':
            heading=compact(self.label(frame,(.30,.035,.72,.09)))
            unit=compact(self.label(frame,(.335,.18,.60,.23)))
            return bool(self.detail_close(frame) and heading=='upgradeunits'
                        and unit.startswith(compact(candidate.name)+'level'))
        return super().running_detail(frame,candidate)

    def white_text(self, image):
        from coc_bot.upgrades.vision import text
        white = cv2.inRange(cv2.cvtColor(image, cv2.COLOR_BGR2HSV), (0, 0, 190), (180, 75, 255))
        return text(255-white, stop=self.stop)

    def candidates(self, frame):
        from coc_bot.upgrades.vision import Candidate
        from coc_bot.progression.reader import ProgressionReader
        if self.menu_kind(frame) not in ('buildings','research'):
            return [], False
        # Early villages often put the lab/storage under Other upgrades and
        # have no Suggested research section at all. Read existing white-name
        # rows in either section; green New entries require a placement flow.
        parser=ProgressionReader(self.stop)
        parser.row_min_value=110;parser.row_close_pixels=3;parser.row_background_fraction=.40
        # Reuse the shared native row geometry, but retain Builder resource
        # identity: the otherwise identical Home menu must never qualify.
        parser.menu_kind=self.menu_kind
        h,w=frame.shape[:2];result=[]
        for row in parser.rows(frame):
            x,y,bw,bh=row['box']
            title=frame[y+3:min(y+bh,y+round(h*.035)),round(w*.775):round(w*.925)]
            green=cv2.inRange(cv2.cvtColor(title,cv2.COLOR_BGR2HSV),(35,80,170),(90,255,255))
            if row['new'] or np.count_nonzero(green)>max(12,title.size//400):continue
            if row['name'] and type(row['cost']) is int and row['cost']>0 and row['currency'] in ('gold','elixir'):
                result.append(Candidate(row['name'],row['cost'],row['currency'],row['point']))
        # Prioritize the lab, then army unlocks and storage. This ordering never
        # makes a locked/new row eligible or claims the entire hall is maxed.
        order={'starlaboratory':0,'builderbarracks':1,'goldstorage':2,'elixirstorage':2}
        if self.menu_kind(frame)=='buildings':
            result.sort(key=lambda c:order.get(compact(c.name),3))
        return result, False

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
