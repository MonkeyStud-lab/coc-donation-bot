"""Normal clan requests for non-donating accounts. No gems or raid medals."""
from functools import lru_cache
from pathlib import Path
import time
import cv2
from coc_bot.attack.army import check_stop
from coc_bot.attack.recovery import atomic_json
from coc_bot.accounts.store import read
from coc_bot.progression.preparation import ArmyPreparation, army_heading_visible, _capacity_area


@lru_cache(maxsize=16)
def reference(name):
    return cv2.imread(str(Path(__file__).parents[1]/'vision/assets'/('request_'+name+'.png')))


def match(frame, name, bounds):
    from coc_bot.upgrades.vision import crop
    ref=reference(name)
    if ref is None:return None
    scale=frame.shape[1]/1853
    ref=cv2.resize(ref,None,fx=scale,fy=scale)
    region=crop(frame,bounds);rh,rw=ref.shape[:2]
    if region.shape[0]<rh or region.shape[1]<rw:return None
    _,score,_,(x,y)=cv2.minMaxLoc(cv2.matchTemplate(region,ref,cv2.TM_CCOEFF_NORMED))
    if score<.97 or abs(float(region[y:y+rh,x:x+rw].mean())-float(ref.mean()))>8:return None
    return round(bounds[0]*frame.shape[1])+x,round(bounds[1]*frame.shape[0])+y,rw,rh


def center(box):
    return box[0]+box[2]//2,box[1]+box[3]//2


def request_dialog(frame):
    if match(frame,'dialog_title',(.27,.05,.73,.16)) is None:return None
    send=match(frame,'send',(.50,.60,.73,.80))
    cancel=match(frame,'cancel',(.27,.60,.49,.80))
    return {'send':center(send),'cancel':center(cancel)} if send and cancel else None


def castle_contents(frame, stop=None):
    if not army_heading_visible(frame,stop):return None
    values=[]
    for name in ('troop','spell','siege'):
        icon=match(frame,'castle_'+name,(.02,.69,.79,.79))
        if icon is None:
            if name=='troop':return None
            continue
        x,y,w,h=icon
        area=frame[y:y+h,x+w:x+w+round(frame.shape[1]*.043)]
        value=_capacity_area(area,stop)
        if value is None:return None
        values.append((name,*value))
    return tuple(values)


def available_button(frame, stop=None):
    if not army_heading_visible(frame,stop):return None
    box=match(frame,'available',(.80,.73,.99,.86))
    return center(box) if box else None


def eligible(config):
    return bool(getattr(config,'account_tag',None) and
                'donating' not in getattr(config,'account_roles',()) and
                (getattr(config,'account_town_hall',0) or 0)>=3 and not config.dry_run)


def request_if_empty(session):
    config=session.config
    if not eligible(config):return False
    path=config.data_dir/'reinforcements/state.json'
    state=read(path,{})
    if state.get('account_tag')==config.account_tag and time.time()<state.get('next_check_at',0):return False
    def record(status, delay=600):
        atomic_json(path,{'account_tag':config.account_tag,'status':status,'at':time.time(),
                          'next_check_at':time.time()+delay})
    record('checking')
    prep=ArmyPreparation(session)
    stop=session.client.stop_check
    try:
        first=prep.open(require_capacity=False)
        check_stop(stop)
        second=session.capture.screenshot()
        a,b=castle_contents(first,stop),castle_contents(second,stop)
        point=available_button(second,stop)
        if not a or a!=b or any(row[1]!=0 for row in b) or point is None:
            record('not_empty_or_request_unavailable');return True
        if available_button(first,stop)!=point:return True
        check_stop(stop);session.input.tap(*point,jitter=0);session._sleep(.5)
        first=session.capture.screenshot();second=session.capture.screenshot()
        dialog=request_dialog(first)
        if not dialog or dialog!=request_dialog(second):
            record('request_dialog_unverified');return True
        # Intent is durable before Send. A restart cannot immediately duplicate
        # a request whose acknowledgement was lost. Native cooldown also gates it.
        record('send_pending',1200)
        check_stop(stop);session.input.tap(*dialog['send'],jitter=0);session._sleep(1.)
        frame=session.capture.screenshot()
        if army_heading_visible(frame,stop) and available_button(frame,stop) is None:
            record('sent',1200)
        else:record('send_unconfirmed',1200)
        return True
    finally:
        if not (stop and stop()):
            frame=session.capture.screenshot();dialog=request_dialog(frame)
            if dialog and dialog==request_dialog(session.capture.screenshot()):
                check_stop(stop);session.input.tap(*dialog['cancel'],jitter=0);session._sleep(.5)
            prep.close()
