"""Account navigation with fresh anchors and independent player-tag reads.

Never logs OCR output or captures login screens to disk. Unknown layouts stop.
"""
from functools import lru_cache
from difflib import SequenceMatcher
from pathlib import Path
import re
import time
import tempfile
import cv2
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


def read_tag(frame, box, stop=None, *, cyan=False):
    from coc_bot.runtime.processes import run_process
    image = crop(frame, box)
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
    # No O/0 or I/1 substitution: ambiguous identity must never be guessed.
    match = re.fullmatch(r'#?([0289PYLQGRJCUV]{5,15})', raw)
    return tag('#'+match[1]) if match else None


def picker_rows(frame, stop=None):
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
        game_name = text(canvas[top+45:top+68, 1480:1770], stop=stop).strip()
        if name and len(name) <= 60:
            result.append({'name': name, 'game_name': game_name, 'point': (round(1570*frame.shape[1]/1853),
                                                   round((top+h/2)*frame.shape[0]/1048))})
    return sorted(result, key=lambda r: r['point'][1])


class AccountNavigator:
    def __init__(self, session, stop=lambda: False):
        self.session, self.stop = session, stop
        self.capture = session.capture
        # Practice mode still navigates; only donation/deployment inputs are dry-run.
        self.input = getattr(session, 'nav_input', None) or session.input

    def check(self):
        if self.stop():
            raise ValueError('Account operation stopped; verify the loaded account before starting')

    def frame(self):
        self.check()
        frame = self.capture.screenshot()
        self.check()
        return frame

    def tap(self, point):
        self.check()
        self.input.tap(*point, jitter=0)
        if interrupted_sleep(.5, self.stop):
            self.check()

    def button(self, name, bounds=(0, 0, 1, 1)):
        point = find(self.frame(), name, bounds)
        if not point:
            raise ValueError('Account controls changed or are covered; open your home village and retry')
        self.tap(point)

    def menu(self):
        frame = self.frame()
        if find(frame, 'switch_heading', (.71, .30, 1, .48)):
            self.button('switch_close', (.94, 0, 1, .12))
            frame = self.frame()
        if find(frame, 'my_profile', (.1, .02, .24, .13)) and find(frame, 'menu_close', (.84, .02, .91, .14)):
            return
        nav = self.session.navigator
        # Reload/Welcome Back can appear before identity verification. Dismiss
        # only those known non-spending controls, then still prove both tags.
        from coc_bot.progression.home import recover_home_overlay
        for _ in range(12):
            if not recover_home_overlay(nav,frame):break
            if interrupted_sleep(1,self.stop):self.check()
            frame=self.frame()
        from coc_bot.vision.battle_menu import direct_match_button
        if direct_match_button(frame,stop_check=self.stop) is not None:
            self.tap((round(frame.shape[1]*.80),round(frame.shape[0]*.60)))
            frame=self.frame()
        if nav.classifier._clan_chat_anchor_visible(frame):
            nav.close_clan_chat(frame)
            frame = self.frame()
        from coc_bot.vision.battle_menu import home_build_control_visible
        if not home_build_control_visible(frame) or not nav.classifier._open_chat_icon_visible(frame):
            raise ValueError('Return to your home village before changing accounts')
        self.tap((round(frame.shape[1]*100/1853), round(frame.shape[0]*112/1048)))
        frame = self.frame()
        if not find(frame, 'my_profile', (.1, .02, .24, .13)) or not find(frame, 'menu_close', (.84, .02, .91, .14)):
            raise ValueError('Could not open the account menu')

    def identity(self):
        self.menu()
        self.button('my_profile', (.1, .02, .24, .13))
        frame = self.frame()
        first = read_tag(frame, (315/1853, 309/1048, 650/1853, 345/1048), self.stop)
        for _ in range(4):
            if first:
                break
            # Profile can retain its previous scroll position (including achievements).
            self.check()
            h,w = frame.shape[:2]
            self.input.swipe(round(w*440/1853),round(h*300/1048),round(w*440/1853),round(h*950/1048),duration_ms=350)
            interrupted_sleep(.4, self.stop)
            frame = self.frame()
            first = read_tag(frame, (315/1853,309/1048,650/1853,345/1048), self.stop)
        if not first:
            raise ValueError('Own player tag could not be read')
        name = text(crop(frame, (315/1853, 266/1048, 700/1853, 309/1048)), stop=self.stop)
        self.button('settings_tab', (.45, .02, .85, .13))
        frame = self.frame()
        if not find(frame, 'id_heading', (.16, .13, .36, .24)) or not find(frame, 'id_switch', (.62, .13, .70, .25)):
            raise ValueError('Link this village to Supercell ID in the game before adding it')
        second = read_tag(frame, (844/1853, 201/1048, 1170/1853, 235/1048), self.stop, cyan=True)
        if first is None or first != second:
            raise ValueError('Player-tag readings did not agree; no account was activated')
        name = text(crop(frame, (844/1853,155/1048,1170/1853,197/1048)), stop=self.stop)
        return {'tag': first, 'name': name.strip()}

    def chooser(self):
        frame = self.frame()
        if not find(frame, 'switch_heading', (.71,.30,1,.48)):
            self.menu()
            self.button('settings_tab', (.45, .02, .85, .13))
            self.button('id_switch', (.62, .13, .70, .25))
        previous = None
        for _ in range(8):
            frame = self.frame()
            if find(frame, 'switch_heading', (.71, .30, 1, .48)):
                names = [r['name'] for r in picker_rows(frame,self.stop)]
                if names and names == previous:
                    return frame
                previous = names
            interrupted_sleep(.5, self.stop)
        raise ValueError('Saved-account chooser did not open')

    def learn(self):
        identity = self.identity()
        rows = picker_rows(self.chooser(), self.stop)
        normalize = lambda s: ''.join(c for c in s.casefold() if c.isalnum())
        matches = [r for r in rows if normalize(r['game_name']) == normalize(identity['name'])]
        if not matches:
            ranked = sorted(((SequenceMatcher(None,normalize(r['game_name']),normalize(identity['name'])).ratio(),i)
                             for i,r in enumerate(rows)), reverse=True)
            if ranked and ranked[0][0] >= .6 and (len(ranked)==1 or ranked[0][0]-ranked[1][0] > .2):
                matches = [rows[ranked[0][1]]]
        if len(matches) != 1 or sum(r['name']==matches[0]['name'] for r in rows)!=1:
            raise ValueError('Current village is not uniquely named in the chooser. Give it a distinct game name and retry.')
        identity['selector'] = matches[0]['name']
        # Names only nominate a card. Reload it and prove the player tag before saving the link.
        self.switch(identity)
        return identity

    def switch(self, account):
        rows = picker_rows(self.chooser(), self.stop)
        matches = [r for r in rows if r['name'] == account.get('selector')]
        if len(matches) != 1:
            raise ValueError('Saved account is not uniquely visible. Use Live view to choose it, then Verify current account.')
        self.tap(matches[0]['point'])
        deadline = time.monotonic()+60
        while time.monotonic() < deadline:
            frame = self.frame()
            from coc_bot.vision.battle_menu import home_build_control_visible
            home = home_build_control_visible(frame) and self.session.navigator.classifier._open_chat_icon_visible(frame)
            menu = find(frame,'my_profile',(.1,.02,.24,.13)) and not find(frame,'switch_heading',(.71,.30,1,.48))
            if home or menu:
                identity = self.identity()
                if identity['tag'] != account['tag']:
                    raise ValueError('A different account loaded; automation remains paused')
                self.button('menu_close', (.84, .02, .91, .14))
                return identity
            interrupted_sleep(1, self.stop)
        raise ValueError('Account did not finish loading; complete it in Live view, then verify')


def verify_session(session, stop=lambda: False):
    """Called inside the device lease, before any automatic actions or recording."""
    expected = session.config.account_tag
    if not expected:
        # A legacy CLI cannot bypass the web app's managed-account identity gate.
        if (session.config.data_dir/'accounts/registry.json').exists():
            raise ValueError('Managed accounts must be started from the web app')
        return
    nav = AccountNavigator(session, stop)
    if nav.identity()['tag'] != expected:
        raise ValueError('Loaded account differs from the selected profile. Verify it in Accounts.')
    nav.button('menu_close', (.84, .02, .91, .14))
