"""Complete-list progression using the existing upgrade transaction checks."""
import time
import hashlib
import json
import cv2
import numpy as np
from coc_bot.upgrades.runner import UpgradeRunner, write_json
from coc_bot.upgrades.vision import Candidate, compact
from coc_bot.upgrades.policy import BUILDINGS, PROTECTED, reason
from coc_bot.progression.policy import EXTRA_BUILDINGS, HEROES, priority, town_hall_blockers
from coc_bot.progression.reader import ProgressionReader, row_key, same_row_observation


class ResearchUnavailable(ValueError):
    pass


class ProgressionRunner(UpgradeRunner):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.reader = ProgressionReader(self.stop)
        self.inventory = None

    def open_menu(self, kind):
        if kind != 'research':return super().open_menu(kind)
        frame=self.capture.screenshot()
        if self.stopped():return None
        if self.reader.menu_kind(frame) == 'research':return super().open_menu(kind)
        frame=super().open_menu('buildings')
        if frame is None or self.stopped():return None
        if self.reader.research_locked(frame):
            second=self.capture.screenshot()
            if self.stopped():return None
            if self.reader.research_locked(second):
                raise ResearchUnavailable('Laboratory is locked; checking buildings and farming instead')
            raise ValueError('Laboratory availability changed; no research input sent')
        return super().open_menu(kind)

    def clear_filters(self, frame):
        opened = self.reader.filters_open(frame)
        if not opened and self.reader.unfiltered_top(frame):
            return frame
        h,w = frame.shape[:2]
        if not opened:
            self.input.tap(round(w*.758),round(h*.032),jitter=0)
            if self.wait(): return None
        for _ in range(9):
            frame = self.capture.screenshot()
            if self.stopped(): return None
            point = self.reader.selected_filter(frame)
            if point is None:
                self.input.tap(round(w*.27),round(h*.60),jitter=0)
                if self.wait(): return None
                frame = self.capture.screenshot()
                if not self.reader.unfiltered_top(frame):
                    raise ValueError('The unfiltered building list could not be verified')
                return frame
            self.input.tap(*point,jitter=0)
            if self.wait(): return None
        raise ValueError('Build filters did not clear')

    def scan(self, frame, kind='buildings'):
        frame = self.clear_filters(frame)
        if frame is None: raise ValueError('Stopped')
        inventory = {'rows':[], 'complete':False, 'unfiltered':True, 'unknown':False,
                     'busy':None, 'balances':self.reader.balances(frame), 'hall':None,'hall_verified':False}
        availability = self.reader.availability(frame, kind)
        if availability:
            inventory['busy'] = availability[0] != availability[1]
        seen = set()
        evidence = self.config.data_dir/'progression/screens'
        evidence.mkdir(parents=True,exist_ok=True)
        for page in range(20):
            if self.stopped(): raise ValueError('Stopped')
            if self.reader.menu_kind(frame) != kind:
                raise ValueError('Building list changed during inventory')
            # Fixed names retain at most twenty current pages per tab.
            cv2.imwrite(str(evidence/(kind+'-'+str(page)+'.png')),frame)
            for row in self.reader.rows(frame):
                if compact(row['name'])=='townhall' and type(row.get('target_level')) is int and 3<=row['target_level']<=19:
                    second=self.capture.screenshot()
                    if self.stopped():raise ValueError('Stopped')
                    matching=next((r for r in self.reader.rows(second) if same_row_observation(row,r,second.shape)
                                   and r.get('target_level')==row['target_level']),None)
                    if matching:
                        inventory['hall']=row['target_level']-1;inventory['hall_verified']=True
                key = row_key(row)
                if key not in seen:
                    inventory['rows'].append(row); seen.add(key)
                if row['currency'] != 'gems' and (not row['name'] or not row['cost'] or not row['currency']):
                    inventory['unknown'] = True
            before = cv2.resize(frame[round(frame.shape[0]*.11):round(frame.shape[0]*.89),
                                     round(frame.shape[1]*.735):],(180,400))
            h,w = frame.shape[:2]
            self.input.swipe(round(w*.87),round(h*.82),round(w*.87),round(h*.40),duration_ms=350)
            if self.wait(): raise ValueError('Stopped')
            after = self.capture.screenshot()
            region = cv2.resize(after[round(h*.11):round(h*.89),round(w*.735):],(180,400))
            if np.abs(before.astype(float)-region).mean() < 1.8:
                inventory['complete'] = True
                break
            frame = after
        self.inventory = inventory
        write_json(self.config.data_dir/('progression/'+kind+'-inventory.json'), inventory | {'at':time.time()})
        return inventory

    def eligibility(self, kind, candidate, balances, availability):
        name = compact(candidate.name)
        if kind != 'buildings':
            return super().eligibility(kind, candidate, balances, availability)
        if name in {compact(n) for n in self.config.upgrade_excluded_names.split(',') if n.strip()}:
            return 'Excluded in upgrade settings'
        if name == 'townhall':
            blockers = town_hall_blockers(self.inventory or {})
            if blockers: return '; '.join(blockers)
        elif name in HEROES:
            return 'Heroes are not building progression'
        elif name not in BUILDINGS | EXTRA_BUILDINGS:
            return 'Building identity is not supported'
        # Shared resource/reserve/slot checks still apply to newly supported buildings.
        checked = candidate if name not in PROTECTED | EXTRA_BUILDINGS else Candidate(
            'Army Camp',candidate.cost,candidate.currency,candidate.point)
        return reason(self.config,'buildings',checked,balances,availability)

    def filter_resource(self, frame, resource):
        if resource not in ('gold','elixir'):
            raise ValueError('New construction requires a gold or elixir filter')
        frame=self.clear_filters(frame)
        if frame is None:return None
        h,w=frame.shape[:2]
        self.input.tap(round(w*.758),round(h*.032),jitter=0)
        if self.wait():return None
        opened=self.capture.screenshot()
        if not self.reader.filters_open(opened) or self.reader.selected_filter(opened) is not None:
            raise ValueError('Construction resource filter could not be established')
        x=.418 if resource=='gold' else .561
        point=(round(w*x),round(h*.24))
        self.input.tap(*point,jitter=0)
        if self.wait():return None
        chosen=self.reader.selected_filter(self.capture.screenshot())
        if chosen is None or max(abs(a-b) for a,b in zip(chosen,point))>5:
            raise ValueError('Construction resource filter did not select the intended currency')
        self.input.tap(round(w*.27),round(h*.60),jitter=0)
        if self.wait():return None
        frame=self.capture.screenshot()
        if self.reader.menu_kind(frame)!='buildings' or compact(self.reader.label(frame,(.79,.065,.97,.106)))!='filtered':
            raise ValueError('Filtered building list was not verified')
        return frame

    def find_row(self, wanted, kind='buildings'):
        # Reopen to reset scrolling; only an identical fresh row can be selected.
        frame = self.capture.screenshot()
        if self.reader.menu_kind(frame):
            self.input.tap(round(frame.shape[1]*.984),round(frame.shape[0]*.032),jitter=0)
            if self.wait(): return None
        frame = self.open_menu(kind)
        if frame is None: return None
        if wanted.get('new'):
            # Remove gem-only purchases from the list before selecting any
            # new-building row, including if recommendations reorder.
            frame=self.filter_resource(frame,wanted['currency'])
            if frame is None:return None
        for _ in range(20):
            if self.stopped(): return None
            matches = [r for r in self.reader.rows(frame) if row_key(r) == row_key(wanted)]
            if matches: return matches[0], frame
            h,w=frame.shape[:2]
            self.input.swipe(round(w*.87),round(h*.82),round(w*.87),round(h*.40),duration_ms=350)
            if self.wait(): return None
            frame=self.capture.screenshot()
            if self.reader.menu_kind(frame)!=kind:return None
        return None

    def inspect(self, kind, frame):
        if kind not in ('buildings','research') or not getattr(self,'target',None):
            return super().inspect(kind,frame)
        rows = self.reader.rows(frame)
        balances = self.reader.balances(frame)
        available = self.reader.availability(frame,kind)
        choices = []
        for row in rows:
            if row_key(row) != row_key(self.target):
                continue
            candidate = Candidate(row['name'],row['cost'],row['currency'],row['point'])
            choices.append(candidate.public() | {'skip':self.eligibility(kind,candidate,balances,available)})
        return {'kind':kind,'availability':available,'balances':balances,
                'recommendations':choices,'section_complete':True}

    def run(self, kind, *, execute=False, expected=None):
        self.target = None
        if kind not in ('buildings','research'):
            return super().run(kind,execute=execute,expected=expected)
        state = self.state()
        if state.get('pending'):
            if not isinstance(state['pending'],dict):
                return {'status':'needs_review','message':'Previous upgrade journal is malformed'}
            if state['pending'].get('kind') in ('construction','obstacle','wall'):
                return {'status':'needs_review','message':'Interrupted progression spending needs verification before any new payment'}
            # Reconciliation must not fall through to the legacy Suggested
            # selection and bypass the full new-building/Town Hall inventory.
            recovery=state['pending'].get('kind')
            if recovery not in ('buildings','research','pets'):
                return {'status':'needs_review','message':'Previous upgrade category is unknown'}
            try:
                frame=self.open_menu(recovery)
                if frame is None:return {'status':'stopped'}
                if not self._verify_pending(state,recovery,frame):
                    return {'status':'needs_review','message':'Previous upgrade outcome is uncertain; no retry will be sent'}
                return {'status':'recovered','message':'Previous upgrade confirmed; the next check will rescan progression priorities'}
            finally:
                if not self.stopped():self.close()
        try:
            previous = self.capture.screenshot()
            from coc_bot.progression.construction import controls
            placement=controls(previous)
            if placement and not self.stopped():
                # A stopped pre-purchase preview may survive the last run.
                # Cancel it; never confirm an old, unjournaled placement.
                self.input.tap(*placement['cancel'],jitter=0)
                if self.wait():return {'status':'stopped'}
                previous=self.capture.screenshot()
            if self.reader.filters_open(previous):
                previous = self.clear_filters(previous)
            if previous is not None and self.reader.menu_kind(previous):
                self.input.tap(round(previous.shape[1]*.984),round(previous.shape[0]*.032),jitter=0)
                if self.wait():return {'status':'stopped'}
            frame = self.open_menu(kind)
            if frame is None:return {'status':'stopped'}
            inventory = self.scan(frame,kind)
            if not inventory['complete']:
                return {'status':'blocked','message':'Complete building inventory could not be read; no progression spending'}
            ordinary = [r for r in inventory['rows'] if r['currency'] != 'gems'
                        and compact(r['name']) not in HEROES]
            new = [r for r in ordinary if r['new']] if kind=='buildings' else []
            if inventory['unknown'] and not new:
                return {'status':'blocked','message':'Some upgrade rows are unreadable; Town Hall and existing upgrades remain paused'}
            if kind == 'research':
                from coc_bot.progression.army import research_priority
                units = {'electrodragon':'electro_dragon','wallbreaker':'wall_breaker',
                         'barbarian':'barbarian','archer':'archer','giant':'giant','wizard':'wizard',
                         'dragon':'dragon','balloon':'balloon','rage':'rage','healingspell':'healing',
                         'healing':'healing','lightning':'lightning','freeze':'freeze','poison':'poison'}
                try:
                    used=json.loads((self.config.data_dir/'progression/army.json').read_text())['troops']
                    if not isinstance(used,dict):used={}
                except (OSError,ValueError,KeyError,TypeError):used={}
                candidates = sorted([r for r in ordinary if compact(r['name']) in units],
                                    key=lambda r:(units[compact(r['name'])] not in used,
                                                  research_priority(units[compact(r['name'])])))
            else:
                candidates = sorted(new or ordinary,key=priority)
            free = self.reader.availability(self.capture.screenshot(),kind)
            choices = []
            for row in candidates:
                if not row['cost'] or row['currency'] not in ('gold','elixir','dark_elixir'):
                    continue
                candidate = Candidate(row['name'],row['cost'],row['currency'],row['point'])
                if not self.eligibility(kind,candidate,inventory['balances'],free):choices.append(row)
            if not choices:
                return {'status':'waiting','message':'Build new structures first; waiting for resources or builders' if new
                        else 'No eligible farming-unit research; waiting for resources or a free Laboratory' if kind=='research'
                        else 'No eligible building; Town Hall remains gated by the full inventory',
                        'town_hall_blockers':town_hall_blockers(inventory) if kind=='buildings' else []}
            self.target = choices[0]
            token = hashlib.sha256(json.dumps([kind,compact(self.target['name']),self.target['cost'],
                                              self.target['currency']]).encode()).hexdigest()
            if expected is not None and expected != token:
                return {'status':'changed','message':'Progression priority changed; check again before starting'}
            if not execute:
                return {'kind':kind,'status':'ready','selected':self.target,'inventory':inventory,'token':token,
                        'availability':free,'balances':inventory['balances'],
                        'recommendations':[r|{'skip':None} for r in choices],
                        'town_hall_blockers':town_hall_blockers(inventory)}
            if self.target['new']:
                from coc_bot.progression.construction import Construction
                return Construction(self).start(self.target,inventory)
            if compact(self.target['name']) == 'wall':
                from coc_bot.progression.walls import WallUpgrade
                return WallUpgrade(self).run(self.target)
            if self.find_row(self.target,kind) is None:
                return {'status':'changed','message':'The selected upgrade is no longer visible'}
            return super().run(kind,execute=True,expected=expected)
        except ResearchUnavailable as exc:
            return {'status':'waiting','message':str(exc)}
        except ValueError as exc:
            return {'status':'stopped' if self.stopped() else 'blocked','message':str(exc)}
        finally:
            if not self.stopped():self.close()
