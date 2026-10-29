"""Known non-purchase notices, independent of scenery and account identity."""
from functools import lru_cache
from pathlib import Path
import cv2
import numpy as np
import hashlib


@lru_cache(maxsize=24)
def _reference(name):
    return cv2.imread(str(Path(__file__).with_name('assets')/(name+'.png')))


def event_ended_button(frame):
    if not isinstance(frame,np.ndarray) or not 1.6<frame.shape[1]/frame.shape[0]<1.95:return None
    image=cv2.resize(frame,(1853,1048))
    def matches(name,box):
        ref=_reference(name)
        if ref is None:return False
        x0,y0,x1,y1=box;region=image[y0:y1,x0:x1]
        _,score,_,(x,y)=cv2.minMaxLoc(cv2.matchTemplate(region,ref,cv2.TM_CCOEFF_NORMED))
        observed=region[y:y+ref.shape[0],x:x+ref.shape[1]]
        return score>=.96 and observed.mean()>=ref.mean()*.82
    if not (matches('event_ended_title',(680,400,1170,510))
            and matches('event_ended_confirm',(770,800,1090,970))):return None
    # After the trading period, this free notice reports medals already
    # converted into resources. Match its fixed wording, never the variable
    # amount, and retain the same title/button/brightness checks.
    if not (matches('event_ended_message',(400,560,1440,750)) or
            (matches('event_converted_message',(400,560,1440,750)) and
             matches('event_converted_prefix',(400,650,1200,725)))):return None
    green=cv2.inRange(cv2.cvtColor(image[830:940,800:1060],cv2.COLOR_BGR2HSV),(30,80,140),(90,255,255)).mean()/255
    return (round(frame.shape[1]*.50),round(frame.shape[0]*.847)) if green>.50 else None


def welcome_back_button(frame):
    if not isinstance(frame,np.ndarray) or not 1.6<frame.shape[1]/frame.shape[0]<1.95:return None
    image=cv2.resize(frame,(1853,1048))
    for name,box in [('welcome_title',(590,90,1270,158)),('welcome_okay',(870,850,1020,905))]:
        ref=_reference(name)
        if ref is None:return None
        x0,y0,x1,y1=box;region=image[y0:y1,x0:x1]
        _,score,_,(x,y)=cv2.minMaxLoc(cv2.matchTemplate(region,ref,cv2.TM_CCOEFF_NORMED))
        observed=region[y:y+ref.shape[0],x:x+ref.shape[1]]
        if score<.97 or observed.mean()<ref.mean()*.85:return None
    green=cv2.inRange(cv2.cvtColor(image[835:918,850:1044],cv2.COLOR_BGR2HSV),
                      (30,70,140),(90,255,255)).mean()/255
    return (round(frame.shape[1]*.511),round(frame.shape[0]*.835)) if green>.5 else None


def defense_results_return_button(frame):
    """The completed defense summary, not an in-progress or inferred replay."""
    if not isinstance(frame,np.ndarray) or not 1.6<frame.shape[1]/frame.shape[0]<1.95:return None
    image=cv2.resize(frame,(1853,1048));point=None
    for name,box in [('defense_results_defender',(565,80,730,140)),
                     ('defense_results_attacker',(1120,80,1290,140)),
                     ('defense_results_damage',(825,250,1040,315)),
                     ('defense_results_return',(10,815,240,1040))]:
        ref=_reference(name)
        if ref is None:return None
        x0,y0,x1,y1=box;region=image[y0:y1,x0:x1]
        _,score,_,(x,y)=cv2.minMaxLoc(cv2.matchTemplate(region,ref,cv2.TM_CCOEFF_NORMED))
        observed=region[y:y+ref.shape[0],x:x+ref.shape[1]]
        if score<.97 or observed.mean()<ref.mean()*.85:return None
        if name=='defense_results_return':
            point=(round((x0+x+ref.shape[1]/2)*frame.shape[1]/1853),
                   round((y0+y+ref.shape[0]/2)*frame.shape[0]/1048))
    return point


def home_star_bonus_button(frame):
    """Acknowledge delivered Home Village loot, never an offer or purchase."""
    if not isinstance(frame,np.ndarray) or not 1.6<frame.shape[1]/frame.shape[0]<1.95:return None
    image=cv2.resize(frame,(1853,1048));point=None
    for name,box in [('home_star_bonus_title',(560,60,1320,160)),
                     ('home_star_bonus_message',(640,410,1570,490)),
                     ('home_star_bonus_okay',(790,820,1095,960))]:
        ref=_reference(name)
        if ref is None:return None
        x0,y0,x1,y1=box;region=image[y0:y1,x0:x1]
        _,score,_,(x,y)=cv2.minMaxLoc(cv2.matchTemplate(region,ref,cv2.TM_CCOEFF_NORMED))
        observed=region[y:y+ref.shape[0],x:x+ref.shape[1]]
        if score<.97 or observed.mean()<ref.mean()*.90:return None
        if name=='home_star_bonus_okay':
            point=(round((x0+x+ref.shape[1]/2)*frame.shape[1]/1853),
                   round((y0+y+ref.shape[0]/2)*frame.shape[0]/1048))
    green=cv2.inRange(cv2.cvtColor(image[834:944,795:1083],cv2.COLOR_BGR2HSV),
                      (30,70,140),(90,255,255)).mean()/255
    return point if green>.5 else None


def event_story_button(frame):
    value=story_dialogue(frame)
    return value['point'] if value else None


def battle_menu_tip_button(frame):
    """The first-use Battle Logs/Edit Army speech is navigation only."""
    if not isinstance(frame,np.ndarray) or not 1.6<frame.shape[1]/frame.shape[0]<1.95:return None
    image=cv2.resize(frame,(1853,1048));point=None
    for name,box in [('battle_tip_caption',(790,700,1320,840)),
                     ('battle_tip_corner',(790,665,860,740)),
                     ('battle_tip_bottom',(1240,810,1310,890))]:
        ref=_reference(name)
        if ref is None:return None
        x0,y0,x1,y1=box;region=image[y0:y1,x0:x1]
        _,score,_,(x,y)=cv2.minMaxLoc(cv2.matchTemplate(region,ref,cv2.TM_CCOEFF_NORMED))
        observed=region[y:y+ref.shape[0],x:x+ref.shape[1]]
        if score<.97 or observed.mean()<ref.mean()*.90:return None
        if name=='battle_tip_caption':
            point=(round((x0+x+ref.shape[1]/2)*frame.shape[1]/1853),
                   round((y0+y+ref.shape[0]/2)*frame.shape[0]/1048))
    return point


def story_dialogue(frame):
    """Ornate speech bubbles have text, white interiors and no action buttons."""
    if not isinstance(frame,np.ndarray) or not 1.6<frame.shape[1]/frame.shape[0]<1.95:return None
    image=cv2.resize(frame,(1853,1048))
    points=[]
    for name,box in [('event_story_corner',(280,220,1480,890)),
                     ('event_story_bottom',(450,360,1670,1000))]:
        ref=_reference(name)
        if ref is None:return None
        x0,y0,x1,y1=box;region=image[y0:y1,x0:x1]
        _,score,_,(x,y)=cv2.minMaxLoc(cv2.matchTemplate(region,ref,cv2.TM_CCOEFF_NORMED))
        observed=region[y:y+ref.shape[0],x:x+ref.shape[1]]
        if score<.96 or observed.mean()<ref.mean()*.90:return None
        points.append((x0+x,y0+y))
    (a,b),(c,d)=points;c+=21;d+=28
    if not 370<c-a<750 or not 100<d-b<310:return None
    inner=image[b+30:d-28,a+25:c-25]
    hsv=cv2.cvtColor(inner,cv2.COLOR_BGR2HSV);gray=cv2.cvtColor(inner,cv2.COLOR_BGR2GRAY)
    if (cv2.inRange(hsv,(0,0,190),(180,45,255)).mean()/255<.55 or
        cv2.inRange(hsv,(30,90,120),(90,255,255)).mean()/255>.02 or (gray<100).mean()<.01):return None
    signature=hashlib.sha256(cv2.resize((gray<100).astype('uint8'),(220,70)).tobytes()).hexdigest()[:16]
    return {'point':(round((a+c)/2*frame.shape[1]/1853),round((b+d)/2*frame.shape[0]/1048)),
            'signature':signature}
