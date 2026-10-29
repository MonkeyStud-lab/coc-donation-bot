"""Learn picker artwork from two verified, non-spending troop Info readings."""
import hashlib
import json
import os
import re
from pathlib import Path
import cv2
from coc_bot.attack.army import ArmyCard
from coc_bot.progression.army import HOUSING
from coc_bot.upgrades.runner import write_json
from coc_bot.upgrades.vision import crop, text, compact


def info_point(cell):
    h,w=cell.shape[:2];left=round(w*.74)
    area=cell[:round(h*.28),left:]
    hsv=cv2.cvtColor(area,cv2.COLOR_BGR2HSV)
    blue=cv2.inRange(hsv,(85,70,100),(125,255,255))
    white=cv2.inRange(hsv,(0,0,200),(180,70,255))
    if blue.mean()/255<.30 or white.mean()/255<.03:return None
    return round(w*.83),round(h*.16)


def _yellow_one(area):
    yellow=cv2.inRange(cv2.cvtColor(area,cv2.COLOR_BGR2HSV),(15,100,180),(45,255,255))
    _,_,stats,_=cv2.connectedComponentsWithStats(yellow)
    glyphs=[(x,y,w,h) for x,y,w,h,a in stats[1:] if h>area.shape[0]*.35 and a>12]
    if len(glyphs)<2:return False
    previous,last=sorted(glyphs,key=lambda b:b[0])[-2:]
    x,y,w,h=last
    # The final numeric word must contain exactly one thin glyph. A dropped
    # digit in 11/21 cannot be repaired from the expected picker level alone.
    return (x-(previous[0]+previous[2])>h*.35 and w/h<.52
            and (yellow[y:y+h,x:x+w]>0).mean()>.60)


def read_info(frame,stop=None,expected_level=None):
    close=crop(frame,(.864,.035,.909,.116));hsv=cv2.cvtColor(close,cv2.COLOR_BGR2HSV)
    red=cv2.inRange(hsv,(0,100,100),(10,255,255))|cv2.inRange(hsv,(170,100,100),(180,255,255))
    white=cv2.inRange(hsv,(0,0,200),(180,65,255))
    if red.mean()/255<.35 or white.mean()/255<.06:return None
    area=crop(frame,(.30,.035,.70,.095))
    heading=text(area,stop=stop)
    match=re.fullmatch(r'(.+?)\s+Level\s*([0-9!Il|]*)',heading,re.I)
    if match is None:return None
    raw=match[2]
    level=int(raw) if raw.isdigit() else 1 if raw in ('','!','I','l','|') and _yellow_one(area) else None
    if level is None or not 1<=level<=30 or expected_level is not None and level!=expected_level:return None
    if level==1 and not _yellow_one(area):return None
    # Troops with a favorite-target stat have an extra field. Housing space
    # therefore moves between columns/rows; inspect the actual stats grid.
    slots=[(.485,.50,.61,.537),(.699,.395,.824,.432)]
    slots += [(x,y,x+.125,y+.037) for y in (.175,.287,.395,.50) for x in (.485,.699)
              if (x,y,x+.125,y+.037) not in slots]
    if not any(compact(text(crop(frame,box),stop=stop))=='housingspace' for box in slots):return None
    name=compact(match[1])
    unit=next((u for u in HOUSING if compact(u.replace('_',' '))==name),None)
    return {'unit_id':unit,'level':level,'close':(round(frame.shape[1]*.886),round(frame.shape[0]*.075))}


def load_references(root,catalog,*,picker=True):
    for unit in HOUSING:
        try:
            path=Path(root)/(unit+'.png');meta=json.loads(path.with_suffix('.json').read_text())
            if not isinstance(meta,dict):continue
            source='two_info_frames' if picker else 'verified_edit'
            if meta.get('source')!=source or meta.get('unit_id')!=unit:continue
            if hashlib.sha256(path.read_bytes()).hexdigest()!=meta.get('sha256'):continue
            image=cv2.imread(str(path))
            if image is None or not 80<=image.shape[0]<=300 or not 70<=image.shape[1]<=300:continue
            h,w=image.shape[:2]
            catalog.add_references(image,[ArmyCard('learned',(0,0,w,h),unit,'troop',None,confirmed=True)],picker=picker)
        except (OSError,ValueError,TypeError):continue


def remember_reference(root,catalog,unit,cell,*,picker=True):
    if unit not in HOUSING:raise ValueError('Unsupported troop reference')
    h,w=cell.shape[:2]
    catalog.add_references(cell,[ArmyCard('learned',(0,0,w,h),unit,'troop',None,confirmed=True)],picker=picker)
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    target=root/(unit+'.png');temporary=root/(unit+'.tmp.png')
    if not cv2.imwrite(str(temporary),cell):raise ValueError('Could not save verified troop artwork')
    os.replace(temporary,target)
    write_json(target.with_suffix('.json'),{'source':'two_info_frames' if picker else 'verified_edit','unit_id':unit,
               'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
