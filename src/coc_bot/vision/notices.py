"""Known non-purchase notices, independent of scenery and account identity."""
from functools import lru_cache
from pathlib import Path
import cv2
import numpy as np
import hashlib


@lru_cache(maxsize=64)
def _reference(name):
    return cv2.imread(str(Path(__file__).with_name('assets')/(name+'.png')))


def reward_reveal_visible(frame):
    """Wait through known chest/reward animations without unrelated OCR/input."""
    if not isinstance(frame,np.ndarray) or not 1.6<frame.shape[1]/frame.shape[0]<1.95:return False
    image=cv2.resize(frame,(1853,1048))
    for pairs in ((('free_chest_left',(230,260,365,690)),('free_chest_right',(1325,260,1480,680))),
                  (('free_reward_floor',(15,795,365,1048)),('free_reward_column',(1570,185,1710,650)))):
        verified=True
        for name,box in pairs:
            ref=_reference(name)
            if ref is None:verified=False;break
            x0,y0,x1,y1=box;region=image[y0:y1,x0:x1]
            _,score,_,(x,y)=cv2.minMaxLoc(cv2.matchTemplate(region,ref,cv2.TM_CCOEFF_NORMED))
            observed=region[y:y+ref.shape[0],x:x+ref.shape[1]]
            if score<.98 or observed.mean()<ref.mean()*.85:verified=False;break
        if verified:return True
    return False


def free_reward_skip_confirm_button(frame):
    """Confirm only the notice explicitly saying rewards will still be received."""
    if not isinstance(frame,np.ndarray) or not 1.6<frame.shape[1]/frame.shape[0]<1.95:return None
    image=cv2.resize(frame,(1853,1048));point=None
    for name,box in [('free_skip_confirm_title',(610,270,1240,385)),
                     ('free_skip_confirm_message',(530,405,1330,540)),
                     ('free_skip_confirm_yes',(925,570,1330,785))]:
        ref=_reference(name)
        if ref is None:return None
        x0,y0,x1,y1=box;region=image[y0:y1,x0:x1]
        _,score,_,(x,y)=cv2.minMaxLoc(cv2.matchTemplate(region,ref,cv2.TM_CCOEFF_NORMED))
        observed=region[y:y+ref.shape[0],x:x+ref.shape[1]]
        if score<.97 or observed.mean()<ref.mean()*.90:return None
        if name=='free_skip_confirm_yes':
            point=(round((x0+x+ref.shape[1]/2)*frame.shape[1]/1853),
                   round((y0+y+ref.shape[0]/2)*frame.shape[0]/1048))
    return point


def free_reward_skip_button(frame):
    """Skip an already-delivered reward reveal, requiring Continue and Skip."""
    if not isinstance(frame,np.ndarray) or not 1.6<frame.shape[1]/frame.shape[0]<1.95:return None
    image=cv2.resize(frame,(1853,1048));point=None
    for name,box in [('free_reward_continue',(785,875,1100,1010)),
                     ('free_reward_skip',(1590,890,1853,1010)),
                     ('free_reward_floor',(15,795,365,1048))]:
        ref=_reference(name)
        if ref is None:return None
        x0,y0,x1,y1=box;region=image[y0:y1,x0:x1]
        _,score,_,(x,y)=cv2.minMaxLoc(cv2.matchTemplate(region,ref,cv2.TM_CCOEFF_NORMED))
        observed=region[y:y+ref.shape[0],x:x+ref.shape[1]]
        threshold=.96 if name=='free_reward_continue' else .97
        if score<threshold or observed.mean()<ref.mean()*.90:return None
        if name=='free_reward_skip':
            point=(round((x0+x+ref.shape[1]/2)*frame.shape[1]/1853),
                   round((y0+y+ref.shape[0]/2)*frame.shape[0]/1048))
    return point


def free_chest_tap_point(frame,stop=None):
    """Already-open reward chest: native hall plus unused hammer and rarity."""
    if not isinstance(frame,np.ndarray) or not 1.6<frame.shape[1]/frame.shape[0]<1.95:return None
    image=cv2.resize(frame,(1853,1048))
    for name,box in [('free_chest_left',(230,260,365,690)),
                     ('free_chest_right',(1325,260,1480,680))]:
        ref=_reference(name)
        if ref is None:return None
        x0,y0,x1,y1=box;region=image[y0:y1,x0:x1]
        _,score,_,(x,y)=cv2.minMaxLoc(cv2.matchTemplate(region,ref,cv2.TM_CCOEFF_NORMED))
        observed=region[y:y+ref.shape[0],x:x+ref.shape[1]]
        if score<.98 or observed.mean()<ref.mean()*.85:return None
    ref=_reference('free_chest_hammer');region=image[825:930,730:1100]
    if ref is None:return None
    _,score,_,(x,y)=cv2.minMaxLoc(cv2.matchTemplate(region,ref,cv2.TM_CCOEFF_NORMED))
    if score<.94 or region[y:y+ref.shape[0],x:x+ref.shape[1]].mean()<ref.mean()*.85:return None
    # The Tap caption disappears after the first strike. The remaining native
    # bright hammers and rarity label still prove this exact free reveal stage.
    ref=_reference('free_chest_tap');region=image[210:315,820:1020]
    prompted=ref is not None and cv2.matchTemplate(region,ref,cv2.TM_CCOEFF_NORMED).max()>=.94
    if not prompted:
        from coc_bot.upgrades.vision import compact,text,crop
        try:rarity=compact(text(crop(image,(.42,.705,.59,.765)),stop=stop))
        except (OSError,RuntimeError,TimeoutError):return None
        if rarity not in ('common','rare','epic','legendary'):return None
    return round(frame.shape[1]*.50),round(frame.shape[0]*.54)


def free_chest_skip_button(frame,stop=None):
    """Skip free chest animations; the next modal must prove rewards are kept."""
    if free_chest_tap_point(frame,stop) is None:return None
    image=cv2.resize(frame,(1853,1048));ref=_reference('free_reward_skip')
    if ref is None:return None
    region=image[890:1010,1590:1853]
    _,score,_,(x,y)=cv2.minMaxLoc(cv2.matchTemplate(region,ref,cv2.TM_CCOEFF_NORMED))
    observed=region[y:y+ref.shape[0],x:x+ref.shape[1]]
    if score<.97 or observed.mean()<ref.mean()*.90:return None
    return (round((1590+x+ref.shape[1]/2)*frame.shape[1]/1853),
            round((890+y+ref.shape[0]/2)*frame.shape[0]/1048))


def stalled_season_bank_visible(frame):
    """The inspected control-free season payout scene, not a purchase/reveal."""
    if not isinstance(frame,np.ndarray) or not 1.6<frame.shape[1]/frame.shape[0]<1.95:return False
    image=cv2.resize(frame,(1853,1048))
    for name,box in [('season_bank_shield',(725,20,1100,360)),
                     ('season_bank_plinth',(615,715,1220,1005)),
                     ('season_bank_wall',(180,550,360,720))]:
        ref=_reference(name)
        if ref is None:return False
        x0,y0,x1,y1=box;region=image[y0:y1,x0:x1]
        _,score,_,(x,y)=cv2.minMaxLoc(cv2.matchTemplate(region,ref,cv2.TM_CCOEFF_NORMED))
        observed=region[y:y+ref.shape[0],x:x+ref.shape[1]]
        if score<.96 or observed.mean()<ref.mean()*.85:return False
    return True


def _announcement_close(frame, anchors):
    if not isinstance(frame,np.ndarray) or not 1.6<frame.shape[1]/frame.shape[0]<1.95:return None
    image=cv2.resize(frame,(1853,1048));point=None
    for name,box in anchors:
        ref=_reference(name)
        if ref is None:return None
        x0,y0,x1,y1=box;region=image[y0:y1,x0:x1]
        _,score,_,(x,y)=cv2.minMaxLoc(cv2.matchTemplate(region,ref,cv2.TM_CCOEFF_NORMED))
        observed=region[y:y+ref.shape[0],x:x+ref.shape[1]]
        if score<.97 or observed.mean()<ref.mean()*.90:return None
        if name.endswith('_close'):
            point=(round((x0+x+ref.shape[1]/2)*frame.shape[1]/1853),
                   round((y0+y+ref.shape[0]/2)*frame.shape[0]/1048))
    return point


def hammer_jam_close_button(frame):
    """Close the inspected free announcement, never its Watch action."""
    return _announcement_close(frame, [('hammer_jam_title',(480,645,1380,760)),
                                      ('hammer_jam_message',(415,740,1440,855)),
                                      ('hammer_jam_close',(1520,50,1650,175))])


def mass_mommas_close_button(frame):
    """Recognize the event announcement and locate its close control."""
    return _announcement_close(frame, [
        ('mass_mommas_title', (550, 645, 1300, 765)),
        ('mass_mommas_go', (720, 825, 1130, 980)),
        ('mass_mommas_close', (1520, 50, 1670, 175)),
    ])


def town_hall_19_close_button(frame):
    """Dismiss the Town Hall 19 announcement using its own close control."""
    return _announcement_close(frame, [
        ('th19_title', (480, 650, 1390, 770)),
        ('th19_watch', (750, 840, 1080, 960)),
        ('th19_close', (1530, 55, 1650, 170)),
    ])


def gold_pass_offer_close_button(frame):
    """Dismiss the native pass advertisement, never its purchase action."""
    return (_announcement_close(frame, [('gold_pass_offer_heading',(730,610,1150,710)),
                                        ('gold_pass_offer_message',(700,680,1170,755)),
                                        ('gold_pass_offer_close',(1565,65,1680,175))])
            or _announcement_close(frame, [('gold_pass_discount_title',(600,645,1250,760)),
                                          ('gold_pass_discount_message',(390,740,1440,825)),
                                          ('hammer_jam_close',(1520,50,1650,175))]))


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
