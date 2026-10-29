"""Account navigation with fresh anchors and independent player-tag reads.

Never logs OCR output or captures login screens to disk. Unknown layouts stop.
"""
from functools import lru_cache
from difflib import SequenceMatcher
from pathlib import Path
import re
import time
import tempfile
import hashlib
from collections import OrderedDict
from loguru import logger
import cv2
import numpy as np
from coc_bot.accounts.store import tag
from coc_bot.upgrades.vision import text, crop
from coc_bot.stop import interrupted_sleep


@lru_cache(maxsize=12)
def anchor(name):
    return cv2.imread(str(Path(__file__).with_name('assets')/(name+'.png')))


def find(frame, name, bounds=(0, 0, 1, 1)):
    if frame is None:
        return None
    # Artwork was inspected at 1853x1048. Scale the observation, not tap output.
    canvas = cv2.resize(frame, (1853, 1048))
    template = anchor(name)
    region = crop(canvas, bounds)
    if template is None or region.shape[0] < template.shape[0] or region.shape[1] < template.shape[1]:
        return None
    _, score, _, point = cv2.minMaxLoc(cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED))
    if score < .90:
        alternate = {'my_profile': 'my_profile_inactive', 'settings_tab': 'settings_tab_active'}.get(name)
        if alternate:
            return find(frame, alternate, bounds)
        return None
    x = point[0] + round(bounds[0]*1853) + template.shape[1]/2
    y = point[1] + round(bounds[1]*1048) + template.shape[0]/2
    return round(x*frame.shape[1]/1853), round(y*frame.shape[0]/1048)


@lru_cache(maxsize=1)
def _tag_font():
    with np.load(Path(__file__).with_name('assets')/'tag_glyphs.npz',allow_pickle=False) as archive:
        return {key:archive[key] for key in archive.files}


def _tag_parts(image, cyan):
    hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
    mask=cv2.inRange(hsv,(92,60,220),(108,255,255)) if cyan else cv2.inRange(hsv,(0,0,185),(180,100,255))
    _,_,stats,_=cv2.connectedComponentsWithStats(mask)
    boxes=sorted([(x,y,w,h) for x,y,w,h,area in stats[1:]
                  if h>=image.shape[0]*.35 and area>=7],key=lambda b:b[0])
    if not 6<=len(boxes)<=16:return None
    # A tag is one distinct glyph row, not merged background or overlapping text.
    if any(w>h*1.2 or w<h*.20 for x,y,w,h in boxes):return None
    if any(a[0]+a[2]>=b[0] for a,b in zip(boxes,boxes[1:])):return None
    if max(y+h for x,y,w,h in boxes)-min(y+h for x,y,w,h in boxes)>image.shape[0]*.18:return None
    return mask,boxes


def _font_character(glyph):
    h,w=glyph.shape;shape=cv2.resize(glyph,(24,32),interpolation=cv2.INTER_AREA)/255
    scores={}
    for key,packed in _tag_font().items():
        label=key.split('_')[0];label='#' if label=='hash' else label
        reference=packed[:-1].reshape(32,24)
        overlap=float(np.minimum(shape,reference).sum())/max(1,float(np.maximum(shape,reference).sum()))
        score=overlap-min(.3,abs(w/h-float(packed[-1]))*.25)
        scores[label]=max(scores.get(label,0),score)
    ranked=sorted(scores.items(),key=lambda v:v[1],reverse=True)
    return ranked[0][0] if len(ranked)>1 and ranked[0][1]>=.94 and ranked[0][1]-ranked[1][1]>=.06 else None


def read_tag(frame, box, stop=None, *, cyan=False):
    from coc_bot.runtime.processes import run_process
    image = crop(frame, box)
    parts=_tag_parts(image,cyan)
    if parts is None or stop and stop():return None
    mask,boxes=parts
    if cyan:
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        gray = cv2.bitwise_not(cv2.inRange(hsv, (92,80,200), (108,220,255)))
    else:
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        gray = cv2.bitwise_not(cv2.inRange(hsv, (0,0,200), (180,80,255)))
    gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    gray = cv2.copyMakeBorder(gray,15,15,15,15,cv2.BORDER_CONSTANT,value=255)
    with tempfile.TemporaryDirectory(prefix='coc-tag-') as folder:
        path = Path(folder)/'tag.png'
        cv2.imwrite(str(path), gray)
        result = run_process(['tesseract',str(path),'stdout','--psm','7','-c',
                              'tessedit_char_whitelist=#0289PYLQGRJCUV'],
                             text=True, timeout=4, stop_check=stop)
        raw = (result.stdout or '').strip().replace(' ', '')
        # Deleted characters cannot pass simply because the shortened tag is valid.
        match = re.fullmatch(r'#?([0289PYLQGRJCUV]{5,15})', raw)
        if match and len(match[1])+1==len(boxes):return tag('#'+match[1])
        characters=[]
        for x,y,w,h in boxes:
            if stop and stop():return None
            glyph=mask[y:y+h,x:x+w];label=_font_character(glyph)
            if label is None:
                isolated=cv2.copyMakeBorder(255-cv2.resize(glyph,None,fx=4,fy=4,interpolation=cv2.INTER_CUBIC),
                                           24,24,24,24,cv2.BORDER_CONSTANT,value=255)
                cv2.imwrite(str(path),isolated)
                result=run_process(['tesseract',str(path),'stdout','--psm','10','-c',
                                    'tessedit_char_whitelist=#0289PYLQGRJCUV'],text=True,timeout=4,stop_check=stop)
                label=(result.stdout or '').strip()
            if not re.fullmatch(r'[#0289PYLQGRJCUV]',label or ''):return None
            characters.append(label)
        raw=''.join(characters)
    # No O/0, B/8 or I/1 substitution. Every visible character must be accounted for.
    return tag(raw) if re.fullmatch(r'#[0289PYLQGRJCUV]{5,15}',raw) else None


def read_name(image, stop=None):
    """Names nominate a chooser card; only the independently read tag verifies it."""
    value=text(image,stop=stop).strip()
    if value or stop and stop():return value
    mask=cv2.inRange(cv2.cvtColor(image,cv2.COLOR_BGR2HSV),(0,0,190),(180,80,255))
    points=cv2.findNonZero(mask)
    if points is None:return ''
    x,y,w,h=cv2.boundingRect(points)
    tight=cv2.resize(255-mask[y:y+h,x:x+w],None,fx=3,fy=3,interpolation=cv2.INTER_CUBIC)
    tight=cv2.copyMakeBorder(tight,20,20,20,20,cv2.BORDER_CONSTANT,value=255)
    from coc_bot.runtime.processes import run_process
    with tempfile.TemporaryDirectory(prefix='coc-name-') as folder:
        path=Path(folder)/'name.png';cv2.imwrite(str(path),tight)
        result=run_process(['tesseract',str(path),'stdout','--psm','8','-l','eng'],
                           text=True,timeout=4,stop_check=stop)
    return (result.stdout or '').strip() if result.returncode==0 else ''


def profile_scroll_point(frame):
    """Start on a native flat panel, outside the embedded 3-D hero viewer."""
    canvas=cv2.resize(frame,(1853,1048));hsv=cv2.cvtColor(canvas,cv2.COLOR_BGR2HSV)
    cream=cv2.inRange(hsv,(10,0,190),(50,50,255))
    blue=cv2.inRange(hsv,(105,20,105),(120,100,215))
    for mask in (cream,blue):
        choices=[]
        for left,right in ((850,1200),(300,550),(1450,1620)):
            allowed=(mask[250:900,left:right]>0).mean(1)>.94
            uniform=canvas[250:900,left:right].std(axis=1).max(axis=1)<6
            allowed &= uniform
            start=None
            for y in range(len(allowed)+1):
                if y<len(allowed) and allowed[y]:
                    if start is None:start=y
                elif start is not None:
                    if y-start>=12:
                        center=250+(start+y)//2
                        if center<=880:choices.append((y-start,(left+right)//2,center))
                    start=None
        if choices:
            _,x,y=max(choices)
            return round(x*frame.shape[1]/1853),round(y*frame.shape[0]/1048)
    return None


def profile_strip_still_visible(frame,point):
    if point is None:return False
    x=round(point[0]*1853/frame.shape[1]);y=round(point[1]*1048/frame.shape[0])
    canvas=cv2.resize(frame,(1853,1048));area=canvas[y-4:y+5,x-65:x+66]
    if area.shape!=(9,131,3):return False
    hsv=cv2.cvtColor(area,cv2.COLOR_BGR2HSV)
    cream=cv2.inRange(hsv,(10,0,190),(50,50,255))
    blue=cv2.inRange(hsv,(105,20,105),(120,100,215))
    return bool(((cream|blue)>0).mean()>.97 and area.std(axis=1).max()<6)


def profile_uncovered(frame):
    """Bright native Profile text/X reject dimmed controls below a popup."""
    canvas=cv2.resize(frame,(1853,1048))
    def white(image):return cv2.inRange(cv2.cvtColor(image,cv2.COLOR_BGR2HSV),(0,0,245),(180,50,255))
    for name,box in (('my_profile',(.1,.02,.24,.13)),('menu_close',(.84,.02,.91,.14))):
        point=find(canvas,name,box);reference=anchor(name)
        if point is None or reference is None:return False
        h,w=reference.shape[:2];x,y=point
        region=canvas[y-h//2:y-h//2+h,x-w//2:x-w//2+w]
        if region.shape!=reference.shape or (white(region)>0).sum()<max(25,(white(reference)>0).sum()*.8):return False
    return True


def picker_rows(frame, stop=None, *, include_game_name=True):
    """Return visible Supercell ID names only; never parse login/email fields."""
    if not find(frame, 'switch_heading', (.71, .30, 1, .48)):
        raise ValueError('Saved-account chooser is not visible')
    canvas = cv2.resize(frame, (1853, 1048))
    # White account cards below the chooser heading. Login has no town-hall line.
    gray = cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY)
    mask = cv2.inRange(gray[490:1040, 1340:1833], 248, 255)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    result = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w < 440 or not 75 < h < 150:
            continue
        top = y+490
        detail = text(canvas[top+65:top+94, 1445:1770], stop=stop)
        if 'town hall' not in detail.lower():
            continue
        name = text(canvas[top+17:top+46, 1445:1745], stop=stop).strip()
        game_name = text(canvas[top+45:top+68, 1480:1770], stop=stop).strip() if include_game_name else ''
        if name and len(name) <= 60:
            hall = re.fullmatch(r'town hall\s*:\s*(\d{1,2})', detail.strip(), re.IGNORECASE)
            result.append({'name': name, 'game_name': game_name,
                           'hall': int(hall[1]) if hall else None, 'point': (round(1570*frame.shape[1]/1853),
                                                   round((top+h/2)*frame.shape[0]/1048))})
    return sorted(result, key=lambda r: r['point'][1])


class AccountNavigator:
    def __init__(self, session, stop=lambda: False):
        self.session, self.stop = session, stop
        self.capture = session.capture
        # Practice mode still navigates; only donation/deployment inputs are dry-run.
        self.input = getattr(session, 'nav_input', None) or session.input
        self._picker_cache=OrderedDict()
        self._chooser_observation=None
        self._names_only=False
        self.metrics={'captures':0,'chooser_reads':0,'chooser_cache_hits':0}

    def check(self):
        if self.stop():
            raise ValueError('Account operation stopped; verify the loaded account before starting')

    def frame(self):
        self.check()
        frame = self.capture.screenshot()
        if 'metrics' in self.__dict__:self.metrics['captures']+=1
        self.check()
        return frame

    def tap(self, point):
        self.check()
        self._chooser_observation=None
        self.input.tap(*point, jitter=0)
        if interrupted_sleep(.5, self.stop):
            self.check()

    def button(self, name, bounds=(0, 0, 1, 1), *, frame=None):
        point = find(self.frame() if frame is None else frame, name, bounds)
        if not point:
            raise ValueError('Account controls changed or are covered; open your home village and retry')
        self.tap(point)

    def menu(self):
        frame = self.frame()
        nav = self.session.navigator
        # These dialogs can leave menu anchors visible underneath them. Recover
        # them before any anchor can authorize a tab or identity read.
        from coc_bot.progression.home import recover_home_overlay
        from coc_bot.vision.battle_menu import home_build_control_visible
        from coc_bot.progression.preparation import army_editor_close_button,picker_editor_visible
        from coc_bot.vision.battle_menu import direct_match_button
        from coc_bot.upgrades.vision import UpgradeReader
        from coc_bot.progression.troop_info import read_info
        sidebar_reader=UpgradeReader(self.stop)
        sidebar_closed=info_closed=picker_closed=False
        for _ in range(20):
            if recover_home_overlay(nav,frame):pass
            elif isinstance(frame,np.ndarray) and (info:=read_info(frame,self.stop)) is not None:
                if info_closed or read_info(self.frame(),self.stop)!=info:
                    raise ValueError('Troop Info did not settle before account recovery')
                self.tap(info['close']);info_closed=True
            elif picker_editor_visible(frame,self.stop):
                second=self.frame()
                if picker_closed or not picker_editor_visible(second,self.stop):
                    raise ValueError('Troop picker did not settle before account recovery')
                self.tap((round(frame.shape[1]*.50),round(frame.shape[0]*.17)))
                picker_closed=True
            elif isinstance(frame,np.ndarray) and (kind:=sidebar_reader.menu_kind(frame)):
                # Build/Research can remain open after an interrupted visit.
                # Recheck its exact heading and bright X before closing it;
                # never send the avatar tap through a purchase dialog.
                if sidebar_closed or sidebar_reader.menu_kind(self.frame())!=kind:
                    raise ValueError('Upgrade sidebar did not settle before account recovery')
                self.tap((round(frame.shape[1]*.984),round(frame.shape[0]*.032)))
                sidebar_closed=True
            elif ((find(frame,'my_profile',(.1,.02,.24,.13)) and find(frame,'menu_close',(.84,.02,.91,.14)))
                  or find(frame,'switch_heading',(.71,.30,1,.48)) or home_build_control_visible(frame)
                  or nav.classifier._clan_chat_anchor_visible(frame) or army_editor_close_button(frame,self.stop)
                  or direct_match_button(frame,stop_check=self.stop) is not None):break
            if interrupted_sleep(1,self.stop):self.check()
            frame=self.frame()
        else:raise ValueError('The game has not finished reloading. Return home in Live view and retry.')
        if find(frame, 'switch_heading', (.71, .30, 1, .48)):
            self.button('switch_close', (.94, 0, 1, .12))
            frame = self.frame()
        if find(frame, 'my_profile', (.1, .02, .24, .13)) and find(frame, 'menu_close', (.84, .02, .91, .14)):
            return frame
        # A rejected army read can leave My Army open. Close only its exact
        # heading and visible X, independent of uncertain troop/capacity reads.
        from coc_bot.progression.preparation import army_editor_close_button
        close=army_editor_close_button(frame,self.stop)
        if close:
            if army_editor_close_button(self.frame(),self.stop)!=close:
                raise ValueError('Army menu changed before account recovery')
            self.tap(close)
            frame=self.frame()
        from coc_bot.vision.battle_menu import direct_match_button
        if direct_match_button(frame,stop_check=self.stop) is not None:
            self.tap((round(frame.shape[1]*.80),round(frame.shape[0]*.60)))
            frame=self.frame()
        if nav.classifier._clan_chat_anchor_visible(frame):
            nav.close_clan_chat(frame)
            frame = self.frame()
        # Drawer closing animations and capture coordination can retain the
        # previous panel briefly. Wait for the same existing home anchors; do
        # not relax them or tap the avatar through an unverified transition.
        for _ in range(20):
            if home_build_control_visible(frame) and nav.classifier._open_chat_icon_visible(frame):break
            if interrupted_sleep(.3,self.stop):self.check()
            frame=self.frame()
        if not home_build_control_visible(frame) or not nav.classifier._open_chat_icon_visible(frame):
            raise ValueError('Return to your home village before changing accounts')
        self.tap((round(frame.shape[1]*100/1853), round(frame.shape[0]*112/1048)))
        frame = self.frame()
        if not find(frame, 'my_profile', (.1, .02, .24, .13)) or not find(frame, 'menu_close', (.84, .02, .91, .14)):
            raise ValueError('Could not open the account menu')
        return frame

    def identity(self):
        frame=self.menu()
        self.button('my_profile', (.1, .02, .24, .13),frame=frame)
        frame = self.frame()
        first = read_tag(frame, (315/1853, 309/1048, 650/1853, 345/1048), self.stop)
        if not first:
            # Fresh profiles can still be populating after the tab has appeared.
            # Let that transition settle before sending a scroll gesture.
            interrupted_sleep(1,self.stop)
            frame=self.frame()
            first=read_tag(frame,(315/1853,309/1048,650/1853,345/1048),self.stop)
        for _ in range(20):
            if first:
                break
            # Profile can retain its previous scroll position (including achievements).
            self.check()
            from coc_bot.progression.home import recover_home_overlay
            if not profile_uncovered(frame):
                if recover_home_overlay(self.session.navigator,frame):
                    raise ValueError('Game reloaded during identity verification; retry the saved account operation')
                raise ValueError('Profile is covered or closed; no scrolling input sent')
            if not (find(frame,'my_profile',(.1,.02,.24,.13)) and find(frame,'menu_close',(.84,.02,.91,.14))):
                raise ValueError('Profile closed while finding the player tag; no scrolling input sent')
            h,w = frame.shape[:2]
            # The 3-D viewer can cover most of the page. Locate a stationary
            # native background strip rather than repeatedly dragging it.
            point=profile_scroll_point(frame)
            fresh=self.frame()
            latest=read_tag(fresh,(315/1853,309/1048,650/1853,345/1048),self.stop)
            if latest:
                first=latest;frame=fresh;break
            if point is None or not profile_strip_still_visible(fresh,point):
                # Inertia can move the page between captures. Wait for an
                # observed native strip; never scroll through a moving viewer.
                interrupted_sleep(.35,self.stop);frame=self.frame()
                first=read_tag(frame,(315/1853,309/1048,650/1853,345/1048),self.stop)
                continue
            self.input.swipe(*point,point[0],round(h*970/1048),duration_ms=120)
            interrupted_sleep(.7, self.stop)
            frame = self.frame()
            first = read_tag(frame, (315/1853,309/1048,650/1853,345/1048), self.stop)
        if not first:
            raise ValueError('Own player tag could not be read')
        if read_tag(self.frame(),(315/1853,309/1048,650/1853,345/1048),self.stop)!=first:
            raise ValueError('Profile tag did not settle. Open the home village and try again.')
        name = read_name(crop(frame, (315/1853, 266/1048, 700/1853, 309/1048)), self.stop)
        self.button('settings_tab', (.45, .02, .85, .13))
        frame = self.frame()
        if not find(frame, 'id_heading', (.16, .13, .36, .24)) or not find(frame, 'id_switch', (.62, .13, .70, .25)):
            raise ValueError('Link this village to Supercell ID in the game before adding it')
        second = read_tag(frame, (844/1853, 201/1048, 1170/1853, 235/1048), self.stop, cyan=True)
        if first != second or read_tag(self.frame(),(844/1853,201/1048,1170/1853,235/1048),self.stop,cyan=True)!=first:
            raise ValueError('Could not verify the same player tag on Profile and Settings. Return to the home village and try again.')
        # Outlined white names can disappear against Settings' blue banner in
        # ordinary grayscale OCR. Do not discard a readable Profile name when
        # that independent Settings name is blank; neither name proves identity.
        region=crop(frame,(844/1853,155/1048,1170/1853,197/1048))
        settings_name=read_name(region,self.stop)
        return {'tag': first, 'name': settings_name or name.strip()}

    def chooser(self):
        self._chooser_observation=None
        frame = self.frame()
        if not find(frame, 'switch_heading', (.71,.30,1,.48)):
            menu=self.menu()
            self.button('settings_tab', (.45, .02, .85, .13),frame=menu)
            self.button('id_switch', (.62, .13, .70, .25))
            frame=None
        previous = None
        for _ in range(8):
            if frame is None:frame=self.frame()
            if find(frame, 'switch_heading', (.71, .30, 1, .48)):
                rows=self._read_cards(frame)
                if rows and previous is not None and self._same_cards(previous,rows):
                    self._chooser_observation=(frame,rows)
                    return frame
                previous = rows
            interrupted_sleep(.5, self.stop)
            frame=None
        raise ValueError('Saved-account chooser did not open')

    def learn(self):
        identity = self.identity()
        rows = self.saved_cards()
        normalize = lambda s: ''.join(c for c in s.casefold() if c.isalnum())
        matches = [r for r in rows if normalize(r['game_name']) == normalize(identity['name'])]
        if not matches:
            ranked = sorted(((SequenceMatcher(None,normalize(r['game_name']),normalize(identity['name'])).ratio(),i)
                             for i,r in enumerate(rows)), reverse=True)
            if ranked and ranked[0][0] >= .6 and (len(ranked)==1 or ranked[0][0]-ranked[1][0] > .2):
                matches = [rows[ranked[0][1]]]
        if len(matches) != 1 or sum(self.card_key(r)==self.card_key(matches[0]) for r in rows)!=1:
            raise ValueError('Current village is not uniquely named in the chooser. Give it a distinct game name and retry.')
        identity['selector'] = matches[0]['name']
        identity['hall'] = matches[0].get('hall')
        # Names only nominate a card. Reload it and prove the player tag before saving the link.
        self.switch(identity)
        identity['name']=matches[0]['game_name'] or identity['name']
        return identity

    def switch(self, account):
        started=time.monotonic()
        # Registration still inventories all IDs. Routine switching only needs
        # a stable visible candidate; its independently read player tag remains
        # mandatory after loading, regardless of the chooser's displayed name.
        self._names_only=True
        try:card=self.target_card({'name':account.get('selector','')})
        finally:self._names_only=False
        selected=time.monotonic()
        logger.info('Account switch timing: chooser selection {:.2f}s',selected-started)
        self.tap(card['point'])
        # A village can be under attack when its saved account is opened.
        # Allow that defense to finish and the independently recognized summary
        # to close; do not mistake a one-minute load deadline for failed login.
        # Stop remains checked on every frame, and identity is still mandatory.
        deadline = time.monotonic()+240
        while time.monotonic() < deadline:
            frame = self.frame()
            from coc_bot.progression.home import recover_home_overlay
            if recover_home_overlay(self.session.navigator,frame):
                if interrupted_sleep(.5,self.stop):self.check()
                continue
            from coc_bot.vision.battle_menu import home_build_control_visible
            home = home_build_control_visible(frame) and self.session.navigator.classifier._open_chat_icon_visible(frame)
            menu = find(frame,'my_profile',(.1,.02,.24,.13)) and not find(frame,'switch_heading',(.71,.30,1,.48))
            if home or menu:
                loaded=time.monotonic()
                logger.info('Account switch timing: account loading {:.2f}s',loaded-selected)
                identity = self.identity()
                if identity['tag'] != account['tag']:
                    raise ValueError('A different account loaded; automation remains paused')
                self.button('menu_close', (.84, .02, .91, .14))
                logger.info('Account switch timing: identity verification {:.2f}s; total {:.2f}s; {}',
                            time.monotonic()-loaded,time.monotonic()-started,getattr(self,'metrics',{}))
                return identity|{'hall':card.get('hall')}
            interrupted_sleep(1, self.stop)
        raise ValueError('Account did not finish loading. Return to its home village in Live view, release control, then retry in Accounts.')

    @staticmethod
    def card_key(row):
        # Supercell ID names are the chooser's selector. Smaller village-name
        # and hall text may OCR differently after scrolling; neither authorizes
        # identity, which is proved from the reloaded village's player tag.
        return ''.join(c for c in row['name'].casefold() if not c.isspace())

    def _read_cards(self,frame):
        """Reuse OCR for identical chooser pixels, never for player-tag proof.

        Fresh screenshots still establish visibility and scroll stability. This
        cache is local to one navigator and cannot authorize a post-input tap.
        """
        self.check()
        if not find(frame,'switch_heading',(.71,.30,1,.48)):
            raise ValueError('Saved-account chooser is not visible')
        cache=self.__dict__.setdefault('_picker_cache',OrderedDict())
        summary=self.__dict__.get('_names_only',False)
        canvas=cv2.resize(frame,(1853,1048))
        key=(frame.shape,summary,hashlib.sha256(canvas[490:1040,1340:1833].tobytes()).digest())
        if key in cache:
            cache.move_to_end(key)
            if 'metrics' in self.__dict__:self.metrics['chooser_cache_hits']+=1
            return [dict(row) for row in cache[key]]
        rows=picker_rows(frame,self.stop,include_game_name=not summary)
        self.check()
        if 'metrics' in self.__dict__:self.metrics['chooser_reads']+=1
        cache[key]=[dict(row) for row in rows]
        while len(cache)>24:cache.popitem(last=False)
        return rows

    @classmethod
    def _same_cards(cls,first,second):
        return ([cls.card_key(r) for r in first]==[cls.card_key(r) for r in second]
                and all(abs(a['point'][0]-b['point'][0])<=4 and abs(a['point'][1]-b['point'][1])<=4
                        and a.get('hall')==b.get('hall') for a,b in zip(first,second)))

    def target_card(self,wanted):
        """Use one stable viewport when possible; reacquire after any scrolling."""
        if not wanted.get('name','').strip():raise ValueError('Saved account selector is empty')
        self.chooser()
        observation=self.__dict__.get('_chooser_observation')
        frame,rows=observation if observation is not None else self.stable_cards()
        matches=[r for r in rows if self.card_key(r)==self.card_key(wanted)]
        if len(matches)>1:raise ValueError('Saved account cards have duplicate names; no account was selected')
        if matches:return matches[0]
        self.chooser_top()
        previous=None
        for _ in range(16):
            _,rows=self.stable_cards()
            matches=[r for r in rows if self.card_key(r)==self.card_key(wanted)]
            if len(matches)>1:raise ValueError('Saved account cards have duplicate names; no account was selected')
            if matches:return matches[0]
            keys=[self.card_key(r) for r in rows]
            if keys==previous:break
            previous=keys;self.scroll_cards()
        raise ValueError('Saved account moved or disappeared; no account was selected')

    def stable_cards(self):
        frame = self.frame()
        first = self._read_cards(frame)
        fresh=self.frame()
        second = self._read_cards(fresh)
        if not first or frame.shape!=fresh.shape or not self._same_cards(first,second):
            raise ValueError('Saved-account cards have not settled; no account was selected')
        return fresh, second

    def scroll_cards(self, *, top=False):
        self._chooser_observation=None
        frame = self.frame()
        if not find(frame, 'switch_heading', (.71,.30,1,.48)):
            raise ValueError('Saved-account chooser closed; no scrolling input sent')
        self.check()
        h,w = frame.shape[:2]
        a,b = (.55,.90) if top else (.90,.55)
        self.input.swipe(round(w*.86),round(h*a),round(w*.86),round(h*b),duration_ms=400)
        if interrupted_sleep(.4,self.stop): self.check()

    def chooser_top(self):
        self.chooser()
        previous = None
        for _ in range(12):
            _, rows = self.stable_cards()
            keys = [self.card_key(r) for r in rows]
            if keys == previous: return
            previous = keys
            self.scroll_cards(top=True)
        raise ValueError('Too many saved IDs to verify the beginning of the account list')

    def saved_cards(self):
        """Inspect the complete chooser; never assume four visible IDs are all IDs."""
        self.chooser_top()
        all_rows = []
        previous = None
        for _ in range(16):
            _, rows = self.stable_cards()
            keys = [self.card_key(r) for r in rows]
            if keys == previous:
                if len({self.card_key(r) for r in all_rows}) != len(all_rows):
                    raise ValueError('Saved IDs have duplicate names; give them distinct Supercell ID names')
                return [{k:v for k,v in r.items() if k!='point'} for r in all_rows]
            old = [self.card_key(r) for r in all_rows]
            overlap = next((n for n in range(min(len(old),len(keys)),0,-1) if old[-n:]==keys[:n]),0)
            if all_rows and not overlap:
                raise ValueError('Saved-account list changed while scrolling; retry without changing IDs')
            all_rows.extend(rows[overlap:])
            previous = keys
            self.scroll_cards()
        raise ValueError('Saved-account list did not finish; no identity link was saved')

    def card_point(self, wanted):
        self.chooser_top()
        previous = None
        for _ in range(16):
            _, rows = self.stable_cards()
            matches = [r for r in rows if self.card_key(r)==self.card_key(wanted)]
            if len(matches)==1: return matches[0]['point']
            keys = [self.card_key(r) for r in rows]
            if keys==previous: break
            previous=keys
            self.scroll_cards()
        raise ValueError('Saved account moved or disappeared; no account was selected')


def verify_session(session, stop=lambda: False):
    """Called inside the device lease, before any automatic actions or recording."""
    expected = session.config.account_tag
    if not expected:
        # A legacy CLI cannot bypass the web app's managed-account identity gate.
        if (session.config.data_dir/'accounts/registry.json').exists():
            raise ValueError('Managed accounts must be started from the web app')
        return
    from coc_bot.accounts.handoff import VerifiedHandoff
    proof=session.__dict__.pop('_verified_handoff',None)
    if isinstance(proof,VerifiedHandoff) and proof.consume(session.config):
        if stop():raise ValueError('Account operation stopped before handoff confirmation')
        frame=session.capture.screenshot()
        if stop():raise ValueError('Account operation stopped during handoff confirmation')
        from coc_bot.vision.battle_menu import home_build_control_visible
        if ((home_build_control_visible(frame) and session.navigator.classifier._open_chat_icon_visible(frame))
            or session.navigator.classifier._clan_chat_anchor_visible(frame)):
            logger.info('Account handoff: reusing fresh same-lease identity proof after a current village check')
            return
        logger.info('Account handoff screen changed; repeating full identity verification')
    nav = AccountNavigator(session, stop)
    if nav.identity()['tag'] != expected:
        raise ValueError('Loaded account differs from the selected profile. Open Accounts to finish adding or confirm the loaded account.')
    nav.button('menu_close', (.84, .02, .91, .14))
