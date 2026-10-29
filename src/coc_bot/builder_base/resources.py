"""Collect only inspected Builder Gold/elixir controls, never generic colors.

The map has two camera areas, not two independent screens. Every movement
invalidates targets. A missing bubble after a tap is not proof of collection:
the matching resource balance must also increase. The cart is a separate modal.
"""
import math
import time

import cv2
from loguru import logger

from coc_bot.builder_base.vision import ASSETS
from coc_bot.upgrades.vision import crop, resource_amount


def near(a, b, distance=10):
    return math.dist(a, b) <= distance


class ResourceReader:
    def __init__(self, builder):
        self.builder = builder
        self.templates = {kind: cv2.imread(str(ASSETS/f'collect_{kind}.png'))
                          for kind in ('gold', 'gold_alt', 'elixir')}

    def balances(self, frame):
        # The Home Village has different resources; never reuse these reads there.
        if not (self.builder.home(frame) or self.cart(frame)):
            return {}
        values={}
        from coc_bot.upgrades.digits import read_digits
        from coc_bot.progression.reader import counter_digit_variants,red_digit_variants
        import re
        for kind,box in {
                    'gold': (.855, .034, .958, .071),
                    'elixir': (.855, .102, .958, .140),
                    'gems': (.91, .174, .953, .208),
                }.items():
            region=crop(frame,box);original=resource_amount(region,self.builder.stop)
            digits=read_digits(region,extra_templates=counter_digit_variants()|red_digit_variants())
            alternate=int(digits) if digits and re.fullmatch(r'\d{1,9}',digits) else None
            values[kind]=(None if original is not None and alternate is not None and original!=alternate
                          else original if original is not None else alternate)
        return values

    def cart(self, frame):
        return bool(self.builder.find(frame, 'cart_title', (.38,.06,.62,.15))
                    and self.builder.find(frame, 'cart_close', (.81,.055,.87,.15)))

    def cart_close(self, frame):
        return self.builder.find(frame, 'cart_close', (.81,.055,.87,.15)) if self.cart(frame) else None

    def cart_collect(self, frame):
        if not self.cart(frame):
            return None
        point = self.builder.find(frame, 'cart_collect', (.67,.80,.80,.90), threshold=.91)
        if point is None:
            return None
        # Gray/disabled Collect has the same white text. Require its green face.
        green = cv2.inRange(cv2.cvtColor(crop(frame,(.68,.81,.79,.88)),cv2.COLOR_BGR2HSV),
                            (35,75,100),(90,255,255)).mean()/255
        return point if green > .35 else None

    def bubbles(self, frame):
        if not self.builder.home(frame) or self.cart(frame):
            return []
        h,w = frame.shape[:2]
        x0,y0,x1,y1 = round(w*.15),round(h*.10),round(w*.89),round(h*.84)
        region = frame[y0:y1,x0:x1]
        hits = []
        for kind, template in self.templates.items():
            if template is None:
                continue
            for factor in (.94, 1, 1.06):
                ref = cv2.resize(template,None,fx=w/1853*factor,fy=w/1853*factor)
                rh,rw=ref.shape[:2]
                if rh>region.shape[0] or rw>region.shape[1]:
                    continue
                scores=cv2.matchTemplate(region,ref,cv2.TM_CCOEFF_NORMED)
                for _ in range(12):
                    _,score,_,(x,y)=cv2.minMaxLoc(scores)
                    if score < .88:
                        break
                    point=(x0+x+rw//2,y0+y+rh//2)
                    # Top-right HUD/resource purchase controls are excluded.
                    if not (point[0] > w*.76 and point[1] < h*.23):
                        observed=region[y:y+rh,x:x+rw]
                        if observed.mean() >= ref.mean()*.75:
                            hits.append((score,kind.split('_')[0],point))
                    scores[max(0,y-rh):y+rh,max(0,x-rw):x+rw]=0
        selected=[]
        for score,kind,point in sorted(hits,reverse=True):
            if not any(near(point,other['point'],w*.025) for other in selected):
                selected.append({'resource':kind,'point':point,'confidence':float(score)})
        return sorted(selected,key=lambda hit:(hit['point'][1],hit['point'][0]))


class ResourceCollector:
    def __init__(self, runner):
        self.r=runner
        self.reader=ResourceReader(runner.reader)
        self.report={'status':'completed','confirmed':0,'unverified':0,'cart':'not_seen',
                     'gains':{'gold':0,'elixir':0},'views':0}
        self.remaining=16
        self.deadline=time.monotonic()+150

    def settled_balances(self):
        previous=None
        for _ in range(5):
            current=self.reader.balances(self.r.frame())
            if current == previous:
                return current
            previous=current
            self.r.wait(.4)
        return {}  # Animating/unreadable counters cannot establish an exact gain.

    def record_gain(self, kind, before, after):
        a,b=before.get(kind),after.get(kind)
        if type(a) is int and type(b) is int and b>a:
            self.report['confirmed']+=1
            self.report['gains'][kind]+=b-a
            logger.info('Builder Base collection confirmed: {} +{}',kind,b-a)
            return True
        self.report['unverified']+=1
        return False

    def close_cart(self):
        frame=self.r.frame()
        point=self.reader.cart_close(frame)
        if point:
            self.r.tap(point);self.r.wait(.6)
        if not self.r.reader.home(self.r.frame()):
            raise ValueError('Builder Base home not verified after closing Elixir Cart')

    def collect_cart(self, before=None):
        frame=self.r.frame()
        if not self.reader.cart(frame):
            return False
        self.r.phase('collecting_elixir_cart')
        # Opening the cart animates pending defense rewards into its balance.
        self.r.wait(1.5)
        frame=self.r.frame()
        # Prefer the undimmed village counters from before the cart opened.
        before=before or self.reader.balances(frame)
        point=self.reader.cart_collect(frame)
        second=self.r.frame();again=self.reader.cart_collect(second)
        if point and again and near(point,again):
            self.r.tap(again);self.r.wait(1.5)
            after=self.r.frame()
            self.r.evidence(after,'cart-after-collect')
            self.close_cart()
            self.report['cart']='collected' if self.record_gain('elixir',before,self.settled_balances()) else 'unverified_or_full'
            return True
        else:
            self.report['cart']='empty_or_unavailable'
        self.close_cart()
        return True

    def collect_view(self):
        self.report['views']+=1
        tried=[]
        for _ in range(10):
            if time.monotonic() >= self.deadline:
                self.report['status']='bounded_stop'
                return
            frame=self.r.frame()
            if self.r.reader.reward_button(frame):
                frame=self.r.settle_village(self.r.reader.home)
            if self.reader.cart(frame):
                self.collect_cart();return
            if not self.r.reader.home(frame):
                raise ValueError('Resource collection lost verified Builder Base home')
            choices=[h for h in self.reader.bubbles(frame)
                     if not any(near(h['point'],p,30) for p in tried)]
            if not choices or not self.remaining:
                return
            chosen=choices[0];point=chosen['point'];tried.append(point)
            before=self.reader.balances(frame)
            fresh=self.r.frame()
            match=next((h for h in self.reader.bubbles(fresh)
                        if h['resource']==chosen['resource'] and near(h['point'],point)),None)
            if match is None:
                continue
            self.remaining-=1
            self.r.tap(match['point']);self.r.wait(.8)
            after=self.r.frame()
            if self.reader.cart(after):
                self.collect_cart(before)
            elif self.r.reader.home(after):
                self.record_gain(chosen['resource'],before,self.settled_balances())
            else:
                self.r.evidence(after,'collection-unexpected-screen')
                raise ValueError('Unexpected screen after resource bubble; collection stopped')

    def pan(self, gesture):
        frame=self.r.frame()
        if self.r.reader.reward_button(frame):
            frame=self.r.settle_village(self.r.reader.home)
        if not self.r.reader.home(frame):
            raise ValueError('Cannot survey resources outside Builder Base home')
        h,w=frame.shape[:2];self.r.check()
        self.r.input.swipe(round(w*gesture[0]),round(h*gesture[1]),
                           round(w*gesture[2]),round(h*gesture[3]),duration_ms=350)
        self.r.wait(.6)

    def run(self):
        self.r.check()
        if self.r.config.dry_run:
            return {'status':'practice_skipped'}
        self.r.phase('collecting_resources')
        if self.r.reader.reward_button(self.r.frame()):
            self.r.settle_village(self.r.reader.home)
        initial=self.settled_balances()
        if self.reader.cart(self.r.frame()):
            self.collect_cart()
        self.collect_view()
        # A bounded overlapping survey covers the connected areas and shoreline.
        # No assumption about unlocked second-stage buildings or a stored camera.
        for gesture in ((.35,.32,.70,.74),(.35,.32,.70,.74),
                        (.70,.72,.32,.22),(.70,.72,.32,.22),(.70,.72,.32,.22),
                        (.66,.34,.36,.68)):
            if time.monotonic() >= self.deadline:
                self.report['status']='bounded_stop'
                break
            self.pan(gesture);self.collect_view()
        final=self.settled_balances()
        self.report['before']=initial
        self.report['after']=final
        self.report['gems_unchanged']=(initial.get('gems')==final.get('gems')
                                       if type(initial.get('gems')) is int and type(final.get('gems')) is int else None)
        for kind in ('gold','elixir'):
            if type(initial.get(kind)) is int and type(final.get(kind)) is int:
                self.report['gains'][kind]=final[kind]-initial[kind]
        self.r.record['last_collection']=self.report
        if self.report['gems_unchanged'] is False:
            self.report['status']='needs_review'
            self.r.evidence(self.r.frame(), 'collection-gem-balance-changed')
            self.r.phase('collection_needs_review')
            raise ValueError('Gem balance changed during collection; review evidence before continuing')
        self.r.phase('builder_home')
        return self.report
