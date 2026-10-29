"""Learn the native My Clan tag; names and cached guesses never route donations."""
import csv
import io
import re
import tempfile
import time
from pathlib import Path
import cv2
from coc_bot.accounts.store import read, write, TAG
from coc_bot.accounts.navigation import AccountNavigator, find, read_tag
from coc_bot.upgrades.vision import crop, text, compact
from coc_bot.runtime.processes import run_process


def words(frame, stop):
    canvas=cv2.resize(frame,(1853,1048))
    with tempfile.TemporaryDirectory(prefix='coc-clan-') as folder:
        path=Path(folder)/'clan.png';cv2.imwrite(str(path),canvas)
        result=run_process(['tesseract',str(path),'stdout','--psm','11','-l','eng','tsv'],
                           text=True,timeout=6,stop_check=stop)
    return [w for w in csv.DictReader(io.StringIO(result.stdout or ''),delimiter='\t')
            if w.get('text','').strip()]


def clan_tab(frame, stop):
    if not find(frame,'menu_close',(.84,.02,.91,.14)):return None
    native=find(frame,'my_clan',(.23,.02,.36,.13)) or find(frame,'my_clan_active',(.23,.02,.36,.13))
    if native:return native
    rows=words(frame,stop)
    for a,b in zip(rows,rows[1:]):
        if compact(a['text'])=='my' and compact(b['text'])=='clan':
            x,y=int(a['left']),int(a['top']);right=int(b['left'])+int(b['width'])
            if .20*1853<x<.55*1853 and 0<y<.13*1048:
                return round((x+right)/2*frame.shape[1]/1853),round((y+int(a['height'])/2)*frame.shape[0]/1048)
    return None


def native_clan_tag(frame, stop):
    if not find(frame,'menu_close',(.84,.02,.91,.14)):return None
    # Own membership has the native Leave button; a searched clan has Join.
    # The current UI prints level on its badge, not as a "Clan Level" label.
    if not (find(frame,'clan_location',(.53,.32,.69,.40))
            and find(frame,'clan_leave',(.73,.64,.90,.72))):
        return None
    fixed=read_tag(frame,(.212,.296,.305,.329),stop)
    if fixed:return fixed
    rows=words(frame,stop)
    candidates=[]
    for word in rows:
        raw=word['text'].strip()
        if not TAG.fullmatch(raw):continue
        x,y,w,h=(int(word[k]) for k in ('left','top','width','height'))
        if not .12*1853<x<.65*1853 or not .12*1048<y<.48*1048:continue
        box=((x-5)/1853,(y-4)/1048,(x+w+5)/1853,(y+h+4)/1048)
        for cyan in (False,True):
            value=read_tag(frame,box,stop,cyan=cyan)
            if value==raw:candidates.append(value)
    return candidates[0] if len(set(candidates))==1 else None


class ClanIdentity:
    def __init__(self, store, session, stop):
        self.store,self.session,self.stop=store,session,stop

    def learn(self, account):
        nav=AccountNavigator(self.session,self.stop)
        path=self.store.profile(account)/'data/clan/state.json'
        # Invalidate the previous membership BEFORE navigating. A crash cannot
        # leave an old clan advertised as fresh verification.
        write(path,{'account':account['tag'],'tag':None,'checked_at':time.time()})
        try:
            nav.menu()
            first=clan_tab(nav.frame(),self.stop)
            if first is None or clan_tab(nav.frame(),self.stop)!=first:return None
            nav.tap(first)
            a=native_clan_tag(nav.frame(),self.stop)
            b=native_clan_tag(nav.frame(),self.stop)
            if not a or a!=b:return None
            write(path,{'account':account['tag'],'tag':a,'checked_at':time.time()})
            return a
        except (ValueError,OSError):
            # Optional clan grouping can be unavailable at early Halls. Only
            # successful Home recovery below permits other visit work to run.
            return None
        finally:
            if not self.stop():
                frame=nav.frame()
                close=find(frame,'menu_close',(.84,.02,.91,.14))
                if close and find(nav.frame(),'menu_close',(.84,.02,.91,.14))==close:nav.tap(close)
                if not self.session.navigator.ensure_clan_chat():
                    raise ValueError('Home could not be verified after reading clan membership')


def membership(store, account, now):
    value=read(store.profile(account)/'data/clan/state.json',{})
    observed=value.get('checked_at')
    if (value.get('account')!=account['tag'] or not isinstance(value.get('tag'),str) or not TAG.fullmatch(value['tag'])
        or type(observed) not in (int,float) or not 0<=now-observed<=86400):return None
    return value['tag']


def donors_for(store, source, now):
    clan=membership(store,source,now)
    if not clan:return []
    return [a for a in store.load()['accounts'] if 'donating' in a['roles']
            and membership(store,a,now)==clan]
