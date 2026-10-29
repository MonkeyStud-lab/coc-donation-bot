"""Bounded resource-only obstacle removal, with separate seasonal consent."""
import time
import re
import cv2
import numpy as np
from pathlib import Path
from functools import lru_cache
from coc_bot.upgrades.vision import crop,text,compact,currency,resource_amount
from coc_bot.upgrades.runner import write_json
from coc_bot.vision.battle_menu import home_build_control_visible
from coc_bot.progression.reader import selected_title, balance_amount, counter_digit_variants

ORDINARY = {'tree','trunk','treetrunk','bush','mushroom','stone','rock','log'}


@lru_cache(maxsize=1)
def removal_digit_variants():
    with np.load(Path(__file__).with_name('assets')/'removal_digits.npz',allow_pickle=False) as archive:
        return {key:archive[key] for key in archive.files}


def obstacle(frame, stop=None, *, allow_seasonal=False):
    if not home_build_control_visible(frame):return None
    name=selected_title(frame,(.32,.64,.68,.697),stop)
    if not name or len(name)>80 or not compact(name):return None
    if compact(name) not in ORDINARY and not allow_seasonal:return None
    label=compact(text(crop(frame,(.455,.809,.55,.855)),stop=stop))
    if label!='remove':return None
    price_image=crop(frame,(.465,.715,.535,.751))
    price=resource_amount(price_image,stop)
    # The beige removal tile can merge into the white digit mask. Isolate
    # neutral lettering and use inspected price-font variants, retaining the
    # strict glyph score/margin. Conflicting readings never authorize payment.
    white=cv2.inRange(cv2.cvtColor(price_image,cv2.COLOR_BGR2HSV),(0,0,235),(180,30,255))
    from coc_bot.upgrades.digits import read_digits
    alternate=read_digits(cv2.cvtColor(white,cv2.COLOR_GRAY2BGR),extra_templates=removal_digit_variants())
    alternate=int(alternate) if alternate and re.fullmatch(r'\d{1,5}',alternate) else None
    if price is not None and alternate is not None and price!=alternate:return None
    if price is None:price=alternate
    resource=currency(crop(frame,(.485,.75,.516,.799)))
    if not price or price>50_000 or resource not in ('gold','elixir'):return None
    return {'name':name,'cost':price,'currency':resource,
            'point':(round(frame.shape[1]*.50),round(frame.shape[0]*.79))}


@lru_cache(maxsize=2)
def _builder_face(name):
    return cv2.imread(str(Path(__file__).with_name('assets')/(name+'.png')))


def home_builder_visible(frame):
    """Home-only HUD identity, independent of builder count or reservations."""
    image=cv2.resize(frame,(1853,1048));region=image[720:842,1550:1845]
    for name in ('home_builder','home_builder_low'):
        reference=_builder_face(name)
        if reference is None:continue
        _,score,_,(x,y)=cv2.minMaxLoc(cv2.matchTemplate(region,reference,cv2.TM_CCOEFF_NORMED))
        observed=region[y:y+reference.shape[0],x:x+reference.shape[1]]
        if score>=.96 and observed.mean()>=reference.mean()*.85:return True
    return False


def free_builders(frame, stop=None):
    image=cv2.resize(frame,(1853,1048));region=image[720:842,1550:1845]
    from coc_bot.upgrades.digits import read_digits
    readings=set()
    for name in ('home_builder','home_builder_low'):
        reference=_builder_face(name)
        if reference is None:continue
        _,score,_,(x,y)=cv2.minMaxLoc(cv2.matchTemplate(region,reference,cv2.TM_CCOEFF_NORMED))
        observed=region[y:y+reference.shape[0],x:x+reference.shape[1]]
        if score<.96 or observed.mean()<reference.mean()*.85:continue
        cx=1550+x+reference.shape[1]//2;top=720+y;bottom=top+reference.shape[0]
        digits=(image[bottom+1:bottom+39,cx-38:cx+39] if name=='home_builder' else
                image[top+3:top+44,cx+20:cx+120])
        value=read_digits(digits,fraction=True,extra_templates=counter_digit_variants())
        if value is None:
            # The inspected low-hall slash is wider than the older font's.
            # Require all three visible components and its actual diagonal;
            # match both numeric glyphs separately rather than dropping one.
            white=cv2.inRange(cv2.cvtColor(digits,cv2.COLOR_BGR2HSV),(0,0,200),(180,70,255))
            _,_,stats,_=cv2.connectedComponentsWithStats(white)
            parts=sorted([(a,b,w,h) for a,b,w,h,area in stats[1:]
                          if h>=digits.shape[0]*.45 and area>=8])
            if len(parts)==3:
                a,b,w,h=parts[1];yy,xx=np.nonzero(white[b:b+h,a:a+w])
                diagonal=(len(xx)>2 and np.std(xx)>0 and np.std(yy)>0 and np.corrcoef(xx,yy)[0,1]<-.80)
                if diagonal:
                    values=[read_digits(cv2.cvtColor(white[b:b+h,a:a+w],cv2.COLOR_GRAY2BGR),
                                        extra_templates=counter_digit_variants()) for a,b,w,h in (parts[0],parts[2])]
                    if all(v and re.fullmatch(r'\d',v) for v in values):value='/'.join(values)
        if value is None:continue
        match=re.fullmatch(r'(\d)/(\d)',value)
        if not match:continue
        free,total=map(int,match.groups())
        if 0<=free<=total<=6 and total:readings.add((free,total))
    return next(iter(readings)) if len(readings)==1 else None


def home_gems(frame,stop=None):
    """Locate the green gem icon; Dark Elixir occupies the third row later on."""
    locations=[]
    for icon,value in (((.962,.16,.996,.222),(.86,.174,.958,.208)),
                       ((.962,.23,.996,.292),(.86,.244,.958,.278))):
        region=crop(frame,icon)
        if not region.size:continue
        green=cv2.inRange(cv2.cvtColor(region,cv2.COLOR_BGR2HSV),(35,90,180),(90,255,255))
        if green.mean()/255>.23:locations.append(value)
    return balance_amount(crop(frame,locations[0]),stop) if len(locations)==1 else None


def candidates(frame):
    h,w=frame.shape[:2];hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
    mask=cv2.inRange(hsv,(30,80,25),(95,255,125))
    mask|=cv2.inRange(hsv,(0,0,70),(180,45,200))
    mask|=cv2.inRange(hsv,(0,100,40),(30,255,140))
    region=mask[round(h*.24):round(h*.72),round(w*.23):round(w*.77)]
    contours,_=cv2.findContours(region,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    points=[]
    for contour in contours:
        x,y,bw,bh=cv2.boundingRect(contour)
        if not 12<bw<w*.055 or not 12<bh<h*.08 or cv2.contourArea(contour)<80:continue
        points.append((round(w*.23)+x+bw//2,round(h*.24)+y+bh//2))
    return sorted(points,key=lambda p:(p[0]-w*.5)**2+(p[1]-h*.55)**2)[:10]


class SpaceMaker:
    def __init__(self,runner):self.r=runner

    def selected(self):
        """Remove one selected obstacle only after two matching observations."""
        r=self.r
        if not r.config.progression_clear_obstacles:return {'status':'disabled'}
        seasonal=getattr(r.config,'progression_clear_seasonal_obstacles',False)
        frame=r.capture.screenshot();first=obstacle(frame,r.stop,allow_seasonal=seasonal)
        if first is None:return {'status':'not_obstacle'}
        fresh=r.capture.screenshot();second=obstacle(fresh,r.stop,allow_seasonal=seasonal)
        if first!=second:return {'status':'changed','message':'Obstacle selection changed before payment'}
        # Keep every leading digit on large accounts; the narrow starter crop
        # can cut a multi-million balance and make an affordable action fail.
        box={'gold':(.82,.035,.958,.072),'elixir':(.82,.103,.958,.14)}[first['currency']]
        before=balance_amount(crop(fresh,box),r.stop)
        gems=home_gems(fresh,r.stop)
        reserve=r.config.upgrade_gold_reserve if first['currency']=='gold' else r.config.upgrade_elixir_reserve
        if before is None or gems is None or before-first['cost']<reserve:
            return {'status':'waiting','message':'Resource/gem balance or removal budget is unverified'}
        state=r.state()
        if state.get('pending'):return {'status':'needs_review','message':'Previous spending is unresolved'}
        state['pending']=first|{'kind':'obstacle','phase':'confirming','at':time.time(),
                                 'balance_before':before,'gems_before':gems}
        write_json(r.path,state)
        if r.stopped():return {'status':'needs_review'}
        r.input.tap(*first['point'],jitter=0)
        if r.wait(1):return {'status':'needs_review'}
        after_frame=r.capture.screenshot()
        after=balance_amount(crop(after_frame,box),r.stop)
        after_gems=home_gems(after_frame,r.stop)
        # Ordinary removals can award gems when they finish. A decrease is never
        # accepted; unknown receipts never cause a second payment.
        if (after!=before-first['cost'] or type(after_gems) is not int or after_gems<gems
                or obstacle(after_frame,r.stop,allow_seasonal=seasonal) is not None):
            return {'status':'needs_review','message':'Obstacle removal receipt is uncertain; repeating payment is blocked'}
        state['last_completed']=state.pop('pending')|{'phase':'confirmed','gems_after':after_gems}
        write_json(r.path,state)
        return {'status':'making_room','name':first['name'],'currency':first['currency'],'spent':first['cost'],
                'message':'Clearing '+first['name']+'; wait for removal to finish before placing buildings'}

    def run(self):
        r=self.r
        if not r.config.progression_clear_obstacles:
            return {'status':'no_room','message':'Placement needs room; ordinary-obstacle clearing is disabled'}
        frame=r.capture.screenshot()
        if not home_build_control_visible(frame):return {'status':'blocked','message':'Home was not verified for making room'}
        for point in candidates(frame):
            if r.stopped():return {'status':'stopped'}
            if not home_build_control_visible(r.capture.screenshot()):
                return {'status':'blocked','message':'A menu covered the village during obstacle search'}
            r.input.tap(*point,jitter=0)
            if r.wait(.3):return {'status':'stopped'}
            result=self.selected()
            if result['status']!='not_obstacle':return result
        if not r.stopped():
            r.input.tap(round(frame.shape[1]*.5),round(frame.shape[0]*.28),jitter=0)
            r.wait(.3)
        return {'status':'no_room','message':'No verified ordinary obstacle could safely create room; placement remains paused'}
