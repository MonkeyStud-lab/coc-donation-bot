"""Bounded ordinary-obstacle clearing after placement fails; no decorations/items."""
import time
import re
import cv2
from coc_bot.upgrades.vision import crop,text,compact,currency,resource_amount
from coc_bot.upgrades.runner import write_json
from coc_bot.vision.battle_menu import home_build_control_visible
from coc_bot.progression.reader import selected_title, balance_amount

ORDINARY = {'tree','trunk','treetrunk','bush','mushroom','stone','rock','log'}


def obstacle(frame, stop=None):
    if not home_build_control_visible(frame):return None
    name=selected_title(frame,(.40,.64,.60,.697),stop)
    if compact(name) not in ORDINARY:return None
    label=compact(text(crop(frame,(.455,.809,.55,.855)),stop=stop))
    if label!='remove':return None
    price=resource_amount(crop(frame,(.465,.715,.535,.751)),stop)
    resource=currency(crop(frame,(.485,.75,.516,.799)))
    if not price or price>50_000 or resource not in ('gold','elixir'):return None
    return {'name':name,'cost':price,'currency':resource,
            'point':(round(frame.shape[1]*.50),round(frame.shape[0]*.79))}


def free_builders(frame, stop=None):
    value=text(crop(frame,(.923,.744,.975,.785)),fraction=True,stop=stop).replace(' ','')
    match=re.fullmatch(r'(\d)/(\d)',value)
    if not match:return None
    free,total=map(int,match.groups())
    return (free,total) if 0<=free<=total<=6 and total else None


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

    def run(self):
        r=self.r
        if not r.config.progression_clear_obstacles:
            return {'status':'no_room','message':'Placement needs room; ordinary-obstacle clearing is disabled'}
        frame=r.capture.screenshot()
        if not home_build_control_visible(frame):return {'status':'blocked','message':'Home was not verified for making room'}
        for point in candidates(frame):
            if r.stopped():return {'status':'stopped'}
            r.input.tap(*point,jitter=0)
            if r.wait(.3):return {'status':'stopped'}
            fresh=r.capture.screenshot();first=obstacle(fresh,r.stop)
            if first is None:continue
            second_frame=r.capture.screenshot();second=obstacle(second_frame,r.stop)
            if first!=second:continue
            available=free_builders(second_frame,r.stop)
            if available is None or available[0]<=r.config.upgrade_builders_reserved:
                return {'status':'waiting','message':'No verified spare builder to clear an obstacle'}
            box={'gold':(.87,.035,.953,.072),'elixir':(.87,.103,.953,.14)}[first['currency']]
            before=balance_amount(crop(second_frame,box),r.stop)
            reserve=r.config.upgrade_gold_reserve if first['currency']=='gold' else r.config.upgrade_elixir_reserve
            if before is None or before-first['cost']<reserve:continue
            state=r.state()
            if state.get('pending'):return {'status':'needs_review','message':'Previous spending is unresolved'}
            state['pending']=first|{'kind':'obstacle','phase':'confirming','at':time.time(),'balance_before':before}
            write_json(r.path,state)
            if r.stopped():return {'status':'needs_review'}
            r.input.tap(*first['point'],jitter=0)
            if r.wait(1):return {'status':'needs_review'}
            after_frame=r.capture.screenshot()
            after=balance_amount(crop(after_frame,box),r.stop)
            if after!=before-first['cost'] or obstacle(after_frame,r.stop) is not None:
                return {'status':'needs_review','message':'Obstacle removal is uncertain; repeating the payment is blocked'}
            state['last_completed']=state.pop('pending')|{'phase':'confirmed'};write_json(r.path,state)
            return {'status':'making_room','message':'Clearing ordinary '+first['name']+'; new construction will retry after the builder finishes'}
        if not r.stopped():
            r.input.tap(round(frame.shape[1]*.5),round(frame.shape[0]*.28),jitter=0)
            r.wait(.3)
        return {'status':'no_room','message':'No verified ordinary obstacle could safely create room; placement remains paused'}
