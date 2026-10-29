"""Prepare a farming army from fresh Home Village unlocks and real camp space."""
import re
import time
import subprocess
from functools import lru_cache
from pathlib import Path
import cv2
import numpy as np
from loguru import logger
from coc_bot.attack.army import read_army, agree_cards, check_stop
from coc_bot.control.attack_planner import learned_catalog
from coc_bot.progression.army import composition, HOUSING
from coc_bot.progression.runner import ProgressionRunner
from coc_bot.progression.reader import same_row_observation
from coc_bot.progression.troop_info import read_info,info_point,load_references,remember_reference
from coc_bot.upgrades.vision import text, compact, crop
from coc_bot.upgrades.runner import write_json
from coc_bot.vision.battle_menu import _white_label, direct_match_button


@lru_cache(maxsize=1)
def capacity_digit_variants():
    with np.load(Path(__file__).with_name('assets')/'capacity_digits.npz',allow_pickle=False) as archive:
        return {key:archive[key] for key in archive.files}


def capacity(frame, stop=None):
    # The game widens the hero panel while the troop army is empty. Read the
    # same header row in both inspected layouts; disagreement stays unknown.
    boxes=((.315,.205,.45,.255),(.45,.205,.57,.255))
    def read(image,reader=None):
        reader=reader or _capacity_area
        values=[value for box in boxes if (value:=reader(crop(image,box),stop)) is not None]
        return values[0] if values and len(set(values))==1 else None
    value=read(frame)
    if value is not None:return value
    # A real foreground picker dims the army header. Normalize only after its
    # heading and independent bright Info controls prove that drawer is open.
    # Two bounded preprocessing levels must agree; never invent a digit/count.
    if not (army_editor_close_button(frame,stop) or picker_editor_visible(frame,stop)):return None
    values=[read(cv2.convertScaleAbs(frame,alpha=scale)) for scale in (1.1,1.3,1.5)]
    known=[v for v in values if v is not None]
    if len(known)>=2 and len(set(known))==1:return known[0]
    # Keep native glyph thresholds strict. Require two agreeing readings,
    # including OCR: a native match plus OCR, or two OCR preparations. Every
    # contrary valid reading vetoes the result; unreadable digits stay unknown.
    ocr=[read(cv2.convertScaleAbs(frame,alpha=scale),_ocr_capacity_area) for scale in (1,1.3,1.5)]
    valid=[v for v in ocr if v is not None]
    if valid and len(known)+len(valid)>=2 and len(set(known+valid))==1:return valid[0]
    return None


def _capacity_parts(area, stop=None):
    # Exclude the troop silhouette at the left and the distant trash control.
    # The silhouette can become false leading digits when the camp is not full.
    hsv=cv2.cvtColor(area,cv2.COLOR_BGR2HSV)
    # Bright red separates the alert from the brown (also reddish) header.
    red=cv2.inRange(hsv,(0,110,185),(8,255,255))|cv2.inRange(hsv,(172,110,185),(180,255,255))
    contours,_=cv2.findContours(red,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    h=area.shape[0]
    alerts=[]
    for contour in contours:
        x,y,w,bh=cv2.boundingRect(contour)
        if x>h*.7 and h*.35<w<h*1.2 and h*.35<bh<h and .65<w/bh<1.5:
            alerts.append(x)
    if len(alerts)>1:return None
    if alerts:
        # The red underfilled-army alert's white ! can read as a final 7.
        # Remove its border too, rather than accepting an invented capacity.
        area=area[:,:max(1,alerts[0]-round(h*.08))]
    if stop and stop():return None
    white=cv2.inRange(cv2.cvtColor(area,cv2.COLOR_BGR2HSV),(0,0,170),(180,75,255))
    _,_,stats,_=cv2.connectedComponentsWithStats(white)
    parts=sorted([(x,y,w,bh) for x,y,w,bh,a in stats[1:] if a>8 and h*.28<bh<h*.65])
    separators=[]
    for i,(x,y,w,bh) in enumerate(parts):
        yy,xx=np.nonzero(white[y:y+bh,x:x+w])
        if .3<w/bh<1.1 and len(xx)>2 and np.std(xx)>0 and np.std(yy)>0 and np.corrcoef(xx,yy)[0,1]<-.80:
            separators.append(i)
    if len(separators)!=1:return None
    split=separators[0]
    if not 1<=split<=3 or not 1<=len(parts)-split-1<=3:return None
    return white,parts,split


def _capacity_area(area, stop=None):
    parsed=_capacity_parts(area,stop)
    if parsed is None:return None
    white,parts,split=parsed
    from coc_bot.upgrades.digits import read_digits
    digits=[]
    for i,(x,y,w,bh) in enumerate(parts):
        if i==split:
            digits.append('/');continue
        glyph=white[y:y+bh,x:x+w]
        value='1' if w/bh<.52 and (glyph>0).mean()>.60 else read_digits(cv2.cvtColor(glyph,cv2.COLOR_GRAY2BGR),extra_templates=capacity_digit_variants())
        if value is None or not re.fullmatch(r'\d',value):return None
        digits.append(value)
    used,total=map(int,''.join(digits).split('/'))
    return (used,total) if 0<=used<=total<=352 and total>0 else None


def _ocr_capacity_area(area, stop=None):
    parsed=_capacity_parts(area,stop)
    if parsed is None:return None
    white,parts,_=parsed
    left=min(x for x,y,w,h in parts);right=max(x+w for x,y,w,h in parts)
    top=min(y for x,y,w,h in parts);bottom=max(y+h for x,y,w,h in parts)
    mask=cv2.copyMakeBorder(255-white[top:bottom,left:right],5,5,5,5,cv2.BORDER_CONSTANT,value=255)
    try:value=re.sub(r'\s','',text(mask,fraction=True,stop=stop))
    except (OSError,subprocess.TimeoutExpired):return None
    if not re.fullmatch(r'\d{1,3}/\d{1,3}',value):return None
    used,total=map(int,value.split('/'))
    return (used,total) if 0<=used<=total<=352 and total>0 else None


@lru_cache(maxsize=1)
def _army_heading():
    return cv2.imread(str(Path(__file__).with_name('assets')/'army_heading.png'))


def army_heading_visible(frame, stop=None):
    """A known heading can authorize closing even when capacity is unreadable."""
    if not isinstance(frame,np.ndarray):return False
    for bounds in ((.40,.075,.61,.13),(.13,.075,.29,.13)):
        if _white_label(frame,bounds,stop)=='myarmy':return True
        reference=_army_heading()
        if reference is not None:
            scale=frame.shape[1]/1853
            ref=cv2.resize(reference,None,fx=scale,fy=scale)
            region=crop(frame,bounds);rh,rw=ref.shape[:2]
            if region.shape[0]>=rh and region.shape[1]>=rw:
                _,score,_,(x,y)=cv2.minMaxLoc(cv2.matchTemplate(region,ref,cv2.TM_CCOEFF_NORMED))
                if score>=.97 and region[y:y+rh,x:x+rw].mean()>=ref.mean()*.85:return True
    return False


def army_editor_close_button(frame, stop=None):
    if not army_heading_visible(frame,stop):return None
    box=crop(frame,(.944,.057,.987,.126));hsv=cv2.cvtColor(box,cv2.COLOR_BGR2HSV)
    red=cv2.inRange(hsv,(0,100,100),(10,255,255))|cv2.inRange(hsv,(170,100,100),(180,255,255))
    white=cv2.inRange(hsv,(0,0,205),(180,70,255))
    if red.mean()/255<.20 or white.mean()/255<.06:return None
    return round(frame.shape[1]*.967),round(frame.shape[0]*.091)


def army_page(frame, stop=None):
    if capacity(frame,stop) is None:return False
    if army_heading_visible(frame,stop):return True
    return picker_editor_visible(frame,stop)


def picker_editor_visible(frame, stop=None):
    """A picker may dim its parent; a covering dialog dims the picker too."""
    if not isinstance(frame,np.ndarray) or stop and stop():return False
    boxes=picker_boxes(frame)
    if len(boxes)<3:return False
    if sum(info_point(frame[y:y+h,x:x+w]) is not None for x,y,w,h in boxes)<2:return False
    return army_heading_visible(cv2.convertScaleAbs(frame,alpha=1.25),stop)


def edit_army_button(frame, stop=None):
    # Keep portrait artwork outside the text crop; it adds false letters.
    if _white_label(frame,(.088,.925,.185,.98),stop)!='editarmy':return None
    green=cv2.inRange(cv2.cvtColor(crop(frame,(.045,.915,.193,.99)),cv2.COLOR_BGR2HSV),
                      (30,70,100),(90,255,255))
    if green.mean()/255<.25:return None
    return round(frame.shape[1]*.117),round(frame.shape[0]*.951)


@lru_cache(maxsize=1)
def _empty_army_prompt():
    return cv2.imread(str(Path(__file__).with_name('assets')/'empty_army_edit.png'))


def empty_army_button(frame, stop=None):
    value=capacity(frame,stop)
    if value is None or value[0]!=0 or not army_heading_visible(frame,stop):return None
    reference=_empty_army_prompt()
    if reference is None:return None
    scale=frame.shape[1]/1853
    ref=cv2.resize(reference,None,fx=scale,fy=scale)
    region=crop(frame,(.45,.28,.98,.42));rh,rw=ref.shape[:2]
    if region.shape[0]<rh or region.shape[1]<rw:return None
    _,score,_,(x,y)=cv2.minMaxLoc(cv2.matchTemplate(region,ref,cv2.TM_CCOEFF_NORMED))
    if score<.97 or region[y:y+rh,x:x+rw].mean()<ref.mean()*.9:return None
    return round(frame.shape[1]*.45)+x+rw//2,round(frame.shape[0]*.28)+y+rh//2


def picker_boxes(frame):
    h,w=frame.shape[:2]; top=round(h*.59)
    image=cv2.cvtColor(frame[top:],cv2.COLOR_BGR2GRAY)
    edges=cv2.Canny(image,40,100)
    contours,_=cv2.findContours(edges,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    found=[]
    for contour in sorted(contours,key=cv2.contourArea,reverse=True):
        x,y,bw,bh=cv2.boundingRect(contour);y+=top
        if not w*.080<bw<w*.105 or not h*.14<bh<h*.20 or x<w*.015:continue
        if any(max(0,min(x+bw,a+c)-max(x,a))*max(0,min(y+bh,b+d)-max(y,b))/min(bw*bh,c*d)>.65
               for a,b,c,d in found):continue
        found.append((x,y,bw,bh))
    return sorted(found,key=lambda b:(b[1]//30,b[0]))


def hall_from_titles(heading, selected):
    normalize=lambda v:re.sub(r'[^a-z0-9]','',v.lower())
    current=re.fullmatch(r'townhalllevel(\d{1,2})',normalize(selected))
    upgrade=re.fullmatch(r'upgradetownhalltolevel(\d{1,2})',normalize(heading))
    level=int(current[1]) if current else int(upgrade[1])-1 if upgrade else None
    return level if level is not None and 2<=level<=18 else None


def level_chip(cell):
    h,w=cell.shape[:2]
    left,top=round(w*.035),round(h*.49)
    area=cell[top:round(h*.76),left:round(w*.28)]
    dark=cv2.inRange(cv2.cvtColor(area,cv2.COLOR_BGR2HSV),(0,0,0),(180,255,75))
    contours,_=cv2.findContours(dark,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    matches=[]
    for contour in contours:
        x,y,bw,bh=cv2.boundingRect(contour)
        if w*.12<bw<w*.27 and h*.12<bh<h*.27 and .7<bw/bh<1.3 and cv2.contourArea(contour)/(bw*bh)>.5:
            matches.append(area[y:y+bh,x:x+bw])
    return matches[0] if len(matches)==1 else None


@lru_cache(maxsize=1)
def level_digit_variants():
    with np.load(Path(__file__).with_name('assets')/'level_digits.npz',allow_pickle=False) as archive:
        return {key:archive[key] for key in archive.files}


def picker_level(cell):
    from coc_bot.upgrades.digits import read_digits
    badge=level_chip(cell)
    if badge is None:return None
    value=read_digits(badge,extra_templates=level_digit_variants()) or ''
    return int(value) if re.fullmatch(r'\d{1,2}',value) and 1<=int(value)<=30 else None


def picker_unlocks(frame,catalog,stop=None):
    result={}
    for x,y,w,h in picker_boxes(frame):
        check_stop(stop)
        cell=frame[y:y+h,x:x+w];level=picker_level(cell)
        if level is None:continue
        reference=catalog.identify_reference(cell,kind='troop',stop_check=stop)
        unit,kind,score,margin=reference or catalog.identify(cell,kind='troop',stop_check=stop)
        if unit in HOUSING and kind=='troop' and (reference is not None or score>=.94 and margin>=.025):
            result[unit]={'level':level,'point':(x+w//2,y+round(h*.65))}
    return result


class ArmyPreparation:
    def __init__(self,session):
        self.s=session;self.stop=session.client.stop_check
        self.catalog=learned_catalog(session.config,use_saved_routine=False)
        self.army_references=set()
        self.references=session.config.data_dir/'progression/picker-references'
        load_references(self.references,self.catalog)
        self.small_references=session.config.data_dir/'progression/army-references'
        load_references(self.small_references,self.catalog,picker=False)

    def frame(self):
        check_stop(self.stop);f=self.s.capture.screenshot();check_stop(self.stop);self.last_frame=f;return f

    def tap(self,point):
        check_stop(self.stop);self.s.input.tap(*point,jitter=0);self.s._sleep(.25)

    def hall(self):
        r=ProgressionRunner(self.s.config,self.s.capture,self.s.input,self.s.navigator,self.stop)
        try:
            frame=r.open_menu('buildings')
            if frame is None:raise ValueError('Stopped')
            frame=r.clear_filters(frame)
            for _ in range(20):
                rows=r.reader.rows(frame)
                row=next((v for v in rows if compact(v['name'])=='townhall'),None)
                if row:
                    # The Build list badge is the NEXT level. Inspecting the row
                    # can instead open a requirements dialog on starter accounts.
                    # Small two-digit badges and a settling list can give an
                    # uncertain first observation. Wait for two consecutive
                    # identical complete rows/levels; never use a majority vote
                    # or the saved account level to fill an unreadable badge.
                    target=r.reader.target_level(frame,row)
                    for _ in range(4):
                        fresh=self.frame()
                        if r.reader.menu_kind(fresh)!='buildings':break
                        current=next((v for v in r.reader.rows(fresh) if compact(v['name'])=='townhall'),None)
                        level=r.reader.target_level(fresh,current) if current else None
                        same=bool(row and current and same_row_observation(row,current,fresh.shape))
                        known=getattr(self.s.config,'account_town_hall',None)
                        plausible=type(known) is not int or target is not None and target-1>=known
                        if same and plausible and target is not None and target==level and 3<=target<=19:
                            logger.info('Farming army: Town Hall {} verified from the building list',target-1)
                            from coc_bot.accounts.hall import observe_hall
                            observe_hall(self.s.config,target-1)
                            return target-1
                        logger.debug('Town Hall still settling: prior={}, fresh={}, same_row={}',target,level,same)
                        frame,row,target=fresh,current,level
                        self.s._sleep(.25)
                    raise ValueError('Current Town Hall level badge could not be verified')
                h,w=frame.shape[:2]
                self.s.input.swipe(round(w*.87),round(h*.82),round(w*.87),round(h*.40),350)
                self.s._sleep(.3);frame=self.frame()
                if r.reader.menu_kind(frame)!='buildings':break
            raise ValueError('Town Hall entry was not found')
        finally:
            f=self.frame();close=r.reader.detail_close(f)
            if close:self.tap(close)
            r.close()

    def open(self, *, require_capacity=True):
        visible=army_page if require_capacity else army_heading_visible
        if not self.s.attack_nav.leave_chat_for_home() or not self.s.attack_nav.open_attack_menu():
            raise ValueError('Could not open the farming army menu')
        frame=self.frame()
        from coc_bot.progression.home import recover_home_overlay
        for _ in range(3):
            if not recover_home_overlay(self.s.navigator,frame):break
            self.s._sleep(.4);frame=self.frame()
        if visible(frame,self.stop):return frame
        button=edit_army_button(frame,self.stop)
        if button is None:
            raise ValueError('Edit Army control was not verified')
        self.tap(button)
        for _ in range(5):
            frame=self.frame()
            if visible(frame,self.stop):return frame
            self.s._sleep(.25)
        raise ValueError('My Army did not open')

    def observe(self):
        first=self.frame();second=self.frame()
        if not army_page(first,self.stop) or not army_page(second,self.stop):
            raise ValueError('Army editor changed')
        a,b=capacity(first,self.stop),capacity(second,self.stop)
        if a!=b:raise ValueError('Army capacity changed')
        cards=agree_cards(read_army(first,'army_confirmation',self.catalog,stop_check=self.stop),
                          read_army(second,'army_confirmation',self.catalog,stop_check=self.stop))
        troops=[c for c in cards if c.kind=='troop']
        if any(not c.stable or c.unit_id not in HOUSING or type(c.quantity) is not int for c in troops):
            raise ValueError('Army composition is uncertain')
        if sum(HOUSING[c.unit_id]*c.quantity for c in troops)!=a[0]:
            raise ValueError('Army cards do not match occupied camp space')
        # Counts change on every edit; the portrait does not. Keep one fresh
        # army-page reference per identity instead of hundreds of duplicates.
        new=[c for c in troops if c.unit_id not in self.army_references]
        if new:
            self.catalog.add_references(second,new)
            self.army_references.update(c.unit_id for c in new)
        return second,troops,a

    def unlocked(self,frame,cards):
        if cards:
            first=cards[0];x,y,w,h=first.box
            self.tap((x+w//2,y+h//2))
        else:
            point=empty_army_button(frame,self.stop)
            second=self.frame()
            if (point is None or empty_army_button(second,self.stop)!=point
                or capacity(second,self.stop)!=capacity(frame,self.stop)):
                raise ValueError('Empty army and its troop edit area were not verified')
            self.tap(point)
        frame=self.frame()
        if not army_page(frame,self.stop):raise ValueError('Troop picker lost My Army')
        frame=self.learn_unlocks(frame)
        first=picker_unlocks(frame,self.catalog,self.stop)
        fresh=self.frame()
        if not army_page(fresh,self.stop):raise ValueError('Troop picker changed during unlock verification')
        second=picker_unlocks(fresh,self.catalog,self.stop)
        result={u:v for u,v in second.items() if u in first and v['level']==first[u]['level']
                and max(abs(a-b) for a,b in zip(v['point'],first[u]['point']))<=frame.shape[0]*.01}
        # Current colored cards independently establish at least these unlocks.
        for card in cards:
            result.setdefault(card.unit_id,{'level':1,'point':None})
        return result

    def learn_unlocks(self,frame):
        # Positions locate a fresh card, never decide its identity. Only a
        # readable unlocked level plus its blue Info control permits inspection.
        for box in picker_boxes(frame)[:20]:
            x,y,w,h=box;cell=frame[y:y+h,x:x+w]
            level=picker_level(cell)
            if level is None:continue
            reference=self.catalog.identify_reference(cell,kind='troop',stop_check=self.stop)
            unit,kind,score,margin=reference or self.catalog.identify(cell,kind='troop',stop_check=self.stop)
            if unit in HOUSING and (reference is not None or score>=.94 and margin>=.025):continue
            point=info_point(cell)
            if point is None:continue
            self.tap((x+point[0],y+point[1]))
            first=read_info(self.frame(),self.stop,level);second=read_info(self.frame(),self.stop,level)
            if first is None or first!=second:
                logger.debug('Troop Info rejected: expected level {}, first={}, second={}',level,first,second)
                raise ValueError('Troop Info identity did not agree; no army edits sent')
            self.tap(first['close']);fresh=self.frame()
            if not army_page(fresh,self.stop):raise ValueError('My Army did not return after troop Info')
            current=fresh[y:y+h,x:x+w]
            if picker_level(current)!=level or info_point(current) is None:
                raise ValueError('Troop picker moved during identity inspection')
            if first['unit_id'] is not None:
                remember_reference(self.references,self.catalog,first['unit_id'],cell)
                logger.info('Verified unlocked {} level {} from two Info frames',first['unit_id'],level)
            frame=fresh
        return frame

    def close(self):
        frame=self.frame()
        info=read_info(frame,self.stop)
        if info is not None:
            self.tap(info['close']);frame=self.frame()
        if army_page(frame,self.stop):
            self.tap((round(frame.shape[1]*.50),round(frame.shape[0]*.17)))
            frame=self.frame()
            # Counts may be unreadable while the drawer settles. Closing is a
            # non-spending action proved by the heading and X below, not counts.
            if not army_heading_visible(frame,self.stop):raise ValueError('My Army disappeared before closing')
        point=army_editor_close_button(frame,self.stop)
        if point:
            if army_editor_close_button(self.frame(),self.stop)!=point:
                raise ValueError('My Army close control changed')
            self.tap(point)
            frame=self.frame()
        if direct_match_button(frame,stop_check=self.stop):
            self.tap((round(frame.shape[1]*.80),round(frame.shape[0]*.60)))
        from coc_bot.progression.home import ensure_home
        if not ensure_home(self.s.navigator):raise ValueError('Could not confirm home after army preparation')

    def prepare(self):
        try:
            return self._prepare()
        except Exception:
            if isinstance(getattr(self,'last_frame',None),np.ndarray):
                try:
                    path=self.s.config.data_dir/'progression/screens/army-unconfirmed.png'
                    path.parent.mkdir(parents=True,exist_ok=True);cv2.imwrite(str(path),self.last_frame)
                except (OSError,TypeError):pass
            # A rejected army edit must not strand the next scheduled check in
            # the picker. Close only already-verified, non-spending controls.
            if not (self.stop and self.stop()):
                try:self.close()
                except Exception as exc:logger.warning('Army preparation cleanup could not confirm home: {}',exc)
            raise

    def army_hall(self):
        try:return self.hall()
        except ValueError as exc:
            if str(exc)!='Town Hall entry was not found':raise
            from coc_bot.accounts.store import selected_account
            account=selected_account.get()
            known=getattr(self.s.config,'account_town_hall',None)
            if (account is None or account['tag']!=getattr(self.s.config,'account_tag',None)
                or type(known) is not int or not 2<=known<=18 or account.get('town_hall')!=known):raise
            # Army choice only: actual unlocks and housing are read below.
            # This value never authorizes building/Town Hall spending.
            logger.info('Town Hall upgrade row unavailable; using verified account TH{} for army choice only',known)
            return known

    def _prepare(self):
        logger.info('Preparing farming army from current unlocks and camp space')
        hall=self.army_hall()
        self.open();frame,cards,space=self.observe()
        unlocked=self.unlocked(frame,cards)
        desired=composition(hall,space[1],{u:v['level'] for u,v in unlocked.items()})
        counts={c.unit_id:c.quantity for c in cards}
        if counts!=desired:
            self.adjust(desired,unlocked)
            frame,cards,space=self.observe()
            if {c.unit_id:c.quantity for c in cards}!=desired:
                raise ValueError('Prepared army does not match the farming composition')
        self.close()
        write_json(self.s.config.data_dir/'progression/army.json',{'hall':hall,'capacity':space[1],
                   'troops':desired,'unlocks':{u:v['level'] for u,v in unlocked.items()},'at':time.time()})
        logger.info('Farming army ready: TH{}, {} space, {}',hall,space[1],desired)
        self.catalog.prepared_hall=hall
        return self.catalog

    def adjust(self,desired,unlocked):
        verified=None
        for _ in range(704):
            # Reuse the pair captured immediately after the previous edit.
            # There has been no intervening input; every new edit still needs
            # its own two-frame identity, quantity and capacity confirmation.
            frame,cards,space=verified if verified is not None else self.observe()
            current={c.unit_id:c.quantity for c in cards}
            excess=next((c for c in cards if c.quantity>desired.get(c.unit_id,0)),None)
            if excess:
                x,y,w,h=excess.box
                button=frame[y:y+round(h*.32),x+round(w*.62):x+w]
                hsv=cv2.cvtColor(button,cv2.COLOR_BGR2HSV)
                red=cv2.inRange(hsv,(0,90,100),(10,255,255))|cv2.inRange(hsv,(170,90,100),(180,255,255))
                contours,_=cv2.findContours(red,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
                boxes=[cv2.boundingRect(c) for c in contours if cv2.contourArea(c)>w*h*.015]
                if len(boxes)!=1:raise ValueError('Troop removal control is not verified')
                a,b,c,d=boxes[0];point=(x+round(w*.62)+a+c//2,y+b+d//2)
                unit=excess.unit_id;delta=-1
            else:
                unit=next((u for u,n in desired.items() if current.get(u,0)<n),None)
                if unit is None:return
                visible=picker_unlocks(frame,self.catalog,self.stop)
                if unit not in visible:
                    frame=self.learn_unlocks(frame)
                    visible=picker_unlocks(frame,self.catalog,self.stop)
                if unit not in visible or capacity(frame,self.stop)!=space:
                    raise ValueError('Fresh unlocked troop position is not verified')
                point=visible[unit]['point'];delta=1
            self.tap(point)
            if delta==1 and unit not in current:
                self.learn_added_unit(unit,current,space)
            expected=current|{unit:current.get(unit,0)+delta};expected={u:n for u,n in expected.items() if n}
            expected_space=(space[0]+delta*HOUSING[unit],space[1])
            for attempt in range(3):
                try:
                    after_frame,after,after_space=self.observe()
                    logger.debug('Army edit check: expected {} at {}, observed {} at {}',
                                 expected,expected_space,{c.unit_id:c.quantity for c in after},after_space)
                    if {c.unit_id:c.quantity for c in after}==expected and after_space==expected_space:
                        verified=(after_frame,after,after_space)
                        break
                except ValueError:
                    # A changing badge can disagree across the first pair.
                    # Retry observation only; never replay the edit tap.
                    pass
                if attempt==2:
                    raise ValueError('Army edit did not confirm; no further inputs will be sent')
                self.s._sleep(.3)
        raise ValueError('Army editing exceeded its limit')

    def learn_added_unit(self,unit,current,space):
        """Bridge picker artwork to a new army card using a verified edit delta."""
        if unit not in HOUSING or unit in current:raise ValueError('New-card identity needs a new named troop')
        expected_space=(space[0]+HOUSING[unit],space[1])
        for attempt in range(3):
            first=self.frame();second=self.frame();new=[]
            valid=True
            for frame in (first,second):
                if not army_page(frame,self.stop) or capacity(frame,self.stop)!=expected_space:
                    valid=False;break
                h,w=frame.shape[:2]
                cards=[c for c in read_army(frame,'army_confirmation',self.catalog,stop_check=self.stop)
                       if c.box[1]>=h*.25 and c.box[1]+c.box[3]<=h*.46
                       and w*.05<c.box[2]<w*.12 and h*.1<c.box[3]<h*.24]
                remaining=list(cards)
                for name,n in current.items():
                    matches=[c for c in remaining if c.unit_id==name and c.quantity==n]
                    if len(matches)!=1:valid=False;break
                    remaining.remove(matches[0])
                if not valid or len(remaining)!=1 or type(remaining[0].quantity) is not int or remaining[0].quantity!=1:
                    valid=False;break
                new.append(remaining[0])
            if valid and max(abs(a-b) for a,b in zip(new[0].box,new[1].box))<=6:
                x,y,w,h=new[1].box
                remember_reference(self.small_references,self.catalog,unit,second[y:y+h,x:x+w],picker=False)
                self.army_references.add(unit)
                logger.info('Verified new {} army card from named addition and exact housing change',unit)
                return
            if attempt<2:self.s._sleep(.3)
        raise ValueError('New troop card did not agree with its named addition; no further edits sent')
