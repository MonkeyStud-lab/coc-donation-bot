"""Bounded upgrade operation, sharing the bot's single device owner and Stop."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import tempfile

from loguru import logger
from coc_bot.stop import interrupted_sleep
from coc_bot.upgrades.policy import reason
from coc_bot.upgrades.vision import UpgradeReader, compact


def write_json(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,temporary=tempfile.mkstemp(dir=path.parent,suffix='.tmp')
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(value,stream,indent=2)
            stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class UpgradeRunner:
    def __init__(self, config, capture, input_ctrl, navigator, stop=None):
        self.config,self.capture,self.input,self.nav=config,capture,input_ctrl,navigator
        self.stop=stop
        self.reader=UpgradeReader(stop)
        self.path=config.data_dir/'upgrades/state.json'

    def stopped(self):
        return bool(self.stop and self.stop())

    def wait(self, seconds=.6):
        return interrupted_sleep(seconds,self.stop)

    def state(self):
        if not self.path.exists(): return {}
        try:
            value=json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(value,dict): raise ValueError()
            return value
        except (ValueError,OSError):
            # Never silently lose a possible in-flight spending operation.
            return {'pending':{'phase':'unknown','error':'Upgrade journal is unreadable'}}

    def close(self):
        if self.stopped(): return
        # Only verified menu/detail controls are tapped; never press Android BACK.
        for _ in range(3):
            frame=self.capture.screenshot()
            if self.stopped(): return
            if self.reader.menu_kind(frame):
                self.input.tap(round(frame.shape[1]*.984),round(frame.shape[0]*.032),jitter=0)
                if self.wait(): return
            else:
                break
        self.nav.ensure_clan_chat()

    def open_menu(self, kind):
        frame=self.capture.screenshot()
        current=self.reader.menu_kind(frame)
        close=self.reader.detail_close(frame) if current is None else None
        if close is not None:
            if self.stopped(): return None
            self.input.tap(*close,jitter=0)
            if self.wait(): return None
            frame=self.capture.screenshot()
            current=self.reader.menu_kind(frame)
        if current is None:
            if not self.nav.ensure_clan_chat():
                raise ValueError('Could not establish home village and clan chat')
            frame=self.capture.screenshot()
            if self.stopped(): return None
            if not self.nav.classifier._clan_chat_anchor_visible(frame):
                raise ValueError('Clan-chat anchor is missing; upgrade navigation blocked')
            self.nav.close_clan_chat(frame)
            if self.wait(): return None
            frame=self.capture.screenshot()
            from coc_bot.vision.battle_menu import home_build_control_visible
            if not home_build_control_visible(frame):
                raise ValueError('Home Build control is not verified')
            if self.stopped(): return None
            self.input.tap(round(frame.shape[1]*.931),round(frame.shape[0]*.896),jitter=0)
            if self.wait(): return None
            frame=self.capture.screenshot()
            current=self.reader.menu_kind(frame)
            if current is None:
                raise ValueError('Build menu did not open; no upgrades attempted')
        if current != kind:
            if self.stopped(): return None
            self.input.tap(round(frame.shape[1]*(.761 if kind=='buildings' else .829)),
                           round(frame.shape[0]*.932),jitter=0)
            if self.wait(): return None
            frame=self.capture.screenshot()
        if self.reader.menu_kind(frame) != kind:
            raise ValueError('Wrong Build tab; upgrade blocked')
        return frame

    def inspect(self, kind, frame):
        availability=self.reader.availability(frame,kind)
        balances=self.reader.balances(frame)
        rows,end=self.reader.candidates(frame)
        choices=[candidate.public()|{'skip':reason(self.config,kind,candidate,balances,availability)}
                 for candidate in rows]
        return {'kind':kind,'availability':availability,'balances':balances,
                'recommendations':choices,'section_complete':end}

    def _verify_pending(self, state, kind, frame):
        pending=state.get('pending')
        if not pending: return True
        if pending.get('kind') != kind: return False
        active=self.reader.active_names(frame)
        available=self.reader.availability(frame,kind)
        # Research uniquely owns one slot. Duplicate building names are ambiguous:
        # require a decrease from the saved availability as well as the active name.
        busy=available is not None and available[0] < pending.get('free_before',0)
        count=sum(name==compact(pending.get('name','')) for name in active)
        new_timer=count>pending.get('active_before',0)
        if new_timer and busy:
            pending['phase']='confirmed'
            state['last_completed']=pending
            state.pop('pending',None)
            write_json(self.path,state)
            logger.info('Upgrade confirmed running: {}',pending['name'])
            return True
        return False

    def run(self, kind, *, execute=False, expected=None):
        if kind not in ('buildings','research'): raise ValueError('Unknown upgrade category')
        if self.stopped(): return {'status':'stopped'}
        state=self.state()
        recovery_kind=kind
        if 'pending' in state:
            pending=state['pending']
            if not isinstance(pending,dict) or pending.get('kind') not in ('buildings','research'):
                return {'status':'needs_review','message':'Previous upgrade category is unknown; manual review is required',
                        'pending':pending}
            recovery_kind=pending['kind']
        report={'kind':kind,'status':'skipped'}
        detail_open=False
        try:
            # Reconcile on the pending operation's tab before considering any
            # new spending, even if that category's automation is now disabled.
            frame=self.open_menu(recovery_kind)
            if frame is None: return {'status':'stopped'}
            if not self._verify_pending(state,recovery_kind,frame):
                return {'status':'needs_review','message':'Previous upgrade outcome is uncertain; no retry will be sent',
                        'pending':state.get('pending')}
            if recovery_kind != kind:
                if self.stopped(): return {'status':'stopped'}
                frame=self.open_menu(kind)
                if frame is None: return {'status':'stopped'}
            report=self.inspect(kind,frame)
            # Bounded list exploration. Only a verified Suggested section qualifies.
            seen=set();all_choices=[]
            for page in range(5):
                for item in report['recommendations']:
                    identity=(compact(item['name']),item['cost'],item['currency'])
                    if identity not in seen:
                        seen.add(identity);all_choices.append(item)
                eligible=next((item for item in report['recommendations'] if not item['skip']),None)
                if eligible or report['section_complete']: break
                # No builders/research slot: never scroll the whole menu needlessly.
                a=report['availability']
                if a is None or a[0] <= (self.config.upgrade_builders_reserved if kind=='buildings' else 0): break
                if self.stopped(): return {'status':'stopped'}
                h,w=frame.shape[:2]
                self.input.swipe(round(w*.87),round(h*.82),round(w*.87),round(h*.34),duration_ms=300)
                if self.wait(): return {'status':'stopped'}
                frame=self.capture.screenshot()
                if self.reader.menu_kind(frame)!=kind: raise ValueError('Build menu changed while scrolling')
                report=self.inspect(kind,frame)
            report['recommendations']=all_choices
            report['selected']=eligible
            report['status']='ready' if eligible else 'nothing_eligible'
            if eligible is None:
                report['message']='No eligible Suggested upgrade; reserves, availability and exclusions were applied'
                return report
            fingerprint=hashlib.sha256(json.dumps([kind,compact(eligible['name']),eligible['cost'],eligible['currency']]).encode()).hexdigest()
            report['token']=fingerprint
            if not execute: return report
            if expected is not None and expected != fingerprint:
                return report|{'status':'changed','message':'Recommendation changed; check the new preview before starting'}
            # Re-read balances and availability on a separate fresh frame immediately
            # before selecting the card. A mismatch cannot authorize spending.
            fresh=self.capture.screenshot()
            if self.reader.menu_kind(fresh)!=kind: raise ValueError('Build menu changed before selection')
            second=self.inspect(kind,fresh)
            stable=next((item for item in second['recommendations'] if compact(item['name'])==compact(eligible['name'])
                         and item['cost']==eligible['cost'] and item['currency']==eligible['currency'] and not item['skip']),None)
            if stable is None or second['balances']!=report['balances'] or second['availability']!=report['availability']:
                return report|{'status':'changed','message':'Availability, price or resources changed; nothing was spent'}
            if self.stopped(): return {'status':'stopped'}
            from coc_bot.upgrades.vision import Candidate
            candidate=Candidate(eligible['name'],eligible['cost'],eligible['currency'],tuple(stable['point']))
            active_before=sum(name==compact(candidate.name) for name in self.reader.active_names(fresh))
            self.input.tap(*candidate.point,jitter=0)
            detail_open=True
            if self.wait(): return {'status':'stopped'}
            frame=self.capture.screenshot()
            confirmation=self.reader.confirmation(frame,candidate)
            if not confirmation:
                return report|{'status':'blocked','message':'Upgrade confirmation name, price or resource could not be verified'}
            # A second independent screenshot must agree on the spending target.
            check=self.reader.confirmation(self.capture.screenshot(),candidate)
            if check != confirmation:
                return report|{'status':'blocked','message':'Confirmation changed; nothing was spent'}
            pending={'kind':kind,'name':candidate.name,'cost':candidate.cost,'currency':candidate.currency,
                     'free_before':report['availability'][0],'phase':'confirming',
                     'active_before':active_before,
                     'at':datetime.now(timezone.utc).isoformat()}
            state['pending']=pending
            write_json(self.path,state) # durable intent BEFORE the spending tap
            if self.stopped():
                state.pop('pending');write_json(self.path,state)
                return {'status':'stopped'}
            logger.info('Starting recommended {} upgrade: {} for {} {}',kind,candidate.name,candidate.cost,candidate.currency)
            self.input.tap(*confirmation['point'],jitter=0)
            if self.wait(1.0): return {'status':'needs_review','pending':pending}
            frame=self.capture.screenshot()
            if self.reader.running_detail(frame,candidate):
                # Starting research leaves a details dialog open. Only close its
                # verified X; Finish Now buttons must never receive another tap.
                if self.stopped(): return {'status':'needs_review','pending':pending}
                self.input.tap(*self.reader.detail_close(frame),jitter=0)
                if self.wait(): return {'status':'needs_review','pending':pending}
                frame=self.capture.screenshot()
            if self.reader.menu_kind(frame) != kind:
                # Do not confirm another popup, spend gems or consume a magic item.
                pending['phase']='uncertain';write_json(self.path,state)
                return report|{'status':'needs_review','message':'Upgrade tap sent; result is unverified. Automatic retries blocked'}
            detail_open=False
            for _ in range(3):
                if self._verify_pending(state,kind,frame):
                    return report|{'status':'started','message':f'{candidate.name} upgrade is running',
                                   'availability':self.reader.availability(frame,kind)}
                if self.wait(1.0): break
                frame=self.capture.screenshot()
            return report|{'status':'needs_review','message':'Could not confirm the upgrade timer; no retry will be sent'}
        finally:
            if not self.stopped():
                if detail_open:
                    # Close only a still-verified upgrade details dialog, never an
                    # unknown gem/shortfall dialog. Home recovery must not guess.
                    frame=self.capture.screenshot()
                    close=self.reader.detail_close(frame)
                    if close is not None:
                        self.input.tap(*close,jitter=0)
                        self.wait()
                        detail_open=False
                if not detail_open:
                    self.close()
