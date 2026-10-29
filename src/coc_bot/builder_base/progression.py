"""Complete-list Builder progression; new buildings precede ordinary upgrades."""
import hashlib
import json
import re
import time
from types import SimpleNamespace
from functools import lru_cache
from pathlib import Path
from coc_bot.builder_base.vision import BuilderReader
from coc_bot.builder_base.upgrades import BuilderUpgradeRunner,BUILDINGS,eligibility
from coc_bot.progression.reader import ProgressionReader,row_key
from coc_bot.progression.runner import ProgressionRunner
from coc_bot.upgrades.vision import Candidate,compact,crop,text,resource_amount
from coc_bot.upgrades.runner import write_json

CONSTRUCTIBLE=BUILDINGS|{'armycamp','wall'}


@lru_cache(maxsize=1)
def wall_digits():
    import numpy as np
    with np.load(Path(__file__).with_name('assets')/'wall_digits.npz',allow_pickle=False) as archive:
        return {key:archive[key] for key in archive.files}


class BuilderProgressionReader(BuilderReader,ProgressionReader):
    row_min_value=110
    row_close_pixels=3
    row_background_fraction=.40
    def wall_digit_templates(self):
        return wall_digits()
    def single_new_wall(self,frame,row):
        if not row.get('new'):return False
        h,w=frame.shape[:2];x,y,bw,bh=row['box']
        title=frame[y+3:min(y+bh,y+round(h*.035)),round(w*.775):round(w*.925)]
        import cv2
        hsv=cv2.cvtColor(title,cv2.COLOR_BGR2HSV)
        letters=cv2.inRange(hsv,(35,80,170),(90,255,255))|cv2.inRange(hsv,(0,0,205),(180,80,255))
        _,_,stats,_=cv2.connectedComponentsWithStats(letters)
        glyphs=[v for v in stats[1:] if v[3]>=title.shape[0]*.30 and v[4]>=8]
        return bool(len(glyphs)==4 and self.find(frame,'new_wall_title',
                    (.774,(y+3)/h,.925,min(y+bh,y+round(h*.035))/h),threshold=.97))
    def balances(self,frame):
        result=super().balances(frame)
        from coc_bot.upgrades.digits import read_digits
        from coc_bot.progression.reader import counter_digit_variants,red_digit_variants
        for resource,box in {'gold':(.525,.035,.679,.072),'elixir':(.525,.103,.679,.14)}.items():
            if result.get(resource) is not None:continue
            value=read_digits(crop(frame,box),extra_templates=counter_digit_variants()|red_digit_variants())
            if value and re.fullmatch(r'\d{1,9}',value):result[resource]=int(value)
        return result
    def rows(self,frame):
        rows=ProgressionReader.rows(self,frame)
        h,w=frame.shape[:2]
        for row in rows:
            if not row['name'] and self.single_new_wall(frame,row):
                row.update(name='Wall',quantity=1)
            row['name']={'archertowerr':'Archer Tower'}.get(compact(row['name']),row['name'])
            name=compact(row['name']);x,y,bw,bh=row['box']
            if name=='builderhall' or self.menu_kind(frame)=='research':
                row['target_level']=self.target_level(frame,row)
            if row['cost'] is None:
                detail=compact(text(frame[y+round(h*.035):min(y+bh,y+round(h*.065)),
                                          round(w*.775):round(w*.97)],stop=self.stop))
                if detail in ('fullyupgraded','maxlevel','maxed'):row['state']='maxed'
                elif detail.startswith(('upgradebuilderhalltolevel','upgradelaboratorytolevel','upgradebuilderbarrackstolevel')):
                    row['state']='future_locked'
                elif name=='wall' and row['new']:
                    label=compact(self.white_text(frame[y+round(h*.026):min(y+bh,y+round(h*.064)),
                                                   round(w*.935):round(w*.995)]))
                    if label=='free':row.update(cost=0,currency='free',target_level=1)
        return rows


def hall_blockers(inventory):
    result=[]
    if not inventory or not inventory.get('complete') or not inventory.get('unfiltered'):
        result.append('Complete unfiltered Builder inventory is required')
    if not inventory or inventory.get('unknown'):result.append('Some Builder rows remain unreadable')
    if not inventory or inventory.get('hall_verified') is not True:result.append('Builder Hall level is unverified')
    if not inventory or inventory.get('busy') is not False:result.append('Construction must finish before advancing Builder Hall')
    for row in (inventory or {}).get('rows',[]):
        name=compact(row['name'])
        if name=='builderhall' or row.get('state') in ('maxed','future_locked') or row.get('currency')=='gems':continue
        result.append(('Build ' if row.get('new') else 'Upgrade ')+row['name'])
    return result


class BuilderProgressionRunner(BuilderUpgradeRunner):
    inventory_directory='builder_base'
    hall_identity='builderhall'
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.reader=BuilderProgressionReader(self.stop)
        self.inventory=None;self.target=None;self.capacities={}

    filter_resource=ProgressionRunner.filter_resource

    def clear_filters(self,frame):
        # Research only has Cost Min/Max sorting. It must not be sent through
        # the Home/Builder building Resource/Type filtering state machine.
        sorting=self.reader.research_sorting(frame)
        if not sorting and self.reader.menu_kind(frame)!='research':
            return ProgressionRunner.clear_filters(self,frame)
        if self.stopped():return None
        if not sorting:
            if self.reader.menu_kind(self.capture.screenshot())!='research':
                raise ValueError('Builder research menu changed before sorting inspection')
            h,w=frame.shape[:2];self.input.tap(round(w*.758),round(h*.032),jitter=0)
            if self.wait():return None
            frame=self.capture.screenshot()
        if (not self.reader.research_sorting(frame) or self.stopped()
            or not self.reader.research_sorting(self.capture.screenshot())):
            raise ValueError('Builder research sorting controls are unverified')
        if self.stopped():return None
        self.input.tap(round(frame.shape[1]*.40),round(frame.shape[0]*.60),jitter=0)
        if self.wait():return None
        frame=self.capture.screenshot()
        if (self.reader.menu_kind(frame)!='research' or self.stopped()
            or self.reader.menu_kind(self.capture.screenshot())!='research'):
            raise ValueError('Builder research menu did not return after sorting inspection')
        return self.research_top(frame)

    def research_top(self,frame):
        """Sorting never proves the list started at its first row."""
        import cv2
        import numpy as np
        stable=0;h,w=frame.shape[:2]
        for _ in range(20):
            if self.stopped():return None
            if self.reader.menu_kind(frame)!='research':raise ValueError('Builder research list changed')
            before=cv2.resize(crop(frame,(.735,.11,1,.89)),(180,400))
            self.input.swipe(round(w*.87),round(h*.35),round(w*.87),round(h*.82),duration_ms=300)
            if self.wait(.4):return None
            frame=self.capture.screenshot()
            if self.reader.menu_kind(frame)!='research':raise ValueError('Builder research list changed')
            after=cv2.resize(crop(frame,(.735,.11,1,.89)),(180,400))
            stable=stable+1 if np.abs(before.astype(float)-after).mean()<1.8 else 0
            if stable>=2:return frame
        raise ValueError('Builder research list top could not be verified')

    def construction_controls(self,frame):
        from coc_bot.progression.construction import controls
        if self.reader.home(frame) is not True:return None
        # The native Builder placement check is gray over an enabled green
        # face. Match its shape and X/check pairing only on Builder Village;
        # Home construction keeps its original bright-white threshold.
        normal=controls(frame)
        if normal and normal['confirm']:return normal
        for cancel in (None,'no_builder'):
            for threshold,check in ((205,None),(155,'yes_builder')):
                found=controls(frame,check_threshold=threshold,check_asset=check,cancel_asset=cancel)
                if found and found['confirm']:return found
                if found and not normal:normal=found
        return normal

    def close(self):
        # Cancelling a known unpaid placement is safe. An uncertain payment
        # belongs to its receipt reconciler and must never be dismissed here.
        if not self.stopped() and not self.state().get('pending'):
            frame=self.capture.screenshot();placement=self.construction_controls(frame)
            if placement and self.construction_controls(self.capture.screenshot())==placement:
                if self.stopped():return
                self.input.tap(*placement['cancel'],jitter=0)
                if self.wait():return
        return super().close()

    def inspect(self,kind,frame):
        if self.target is None:return super().inspect(kind,frame)
        return ProgressionRunner.inspect(self,kind,frame)

    def map_frame(self):
        from coc_bot.adb.client import AdbStopped
        if self.stopped():raise AdbStopped('Builder progression stopped')
        frame=self.capture.screenshot()
        if self.stopped():raise AdbStopped('Builder progression stopped')
        return frame

    def map_tap(self,point):
        from coc_bot.adb.client import AdbStopped
        if self.stopped():raise AdbStopped('Builder progression stopped')
        self.input.tap(*point,jitter=0)

    def menu_gems(self,frame):
        if self.reader.menu_kind(frame) not in ('buildings','research'):return None
        import cv2
        icon=crop(frame,(.684,.16,.719,.222))
        if cv2.inRange(cv2.cvtColor(icon,cv2.COLOR_BGR2HSV),(35,90,180),(90,255,255)).mean()/255<.23:return None
        return resource_amount(crop(frame,(.61,.174,.679,.208)),self.stop)

    def payment_receipt(self,kind,candidate,confirmation,report,frame):
        if kind!='research' or type(confirmation.get('target_level')) is not int:return {}
        # The confirmation hides HUD counters, so preserve their immediately
        # preceding menu proof separately from the modal's price/resource proof.
        return {'target_level':confirmation['target_level'],
                'balances_before':report['balances'],'gems_before':getattr(self,'research_gems',None)}

    def _verify_pending(self,state,kind,frame):
        if super()._verify_pending(state,kind,frame):return True
        p=state.get('pending',{});level=p.get('target_level');before=p.get('balances_before',{})
        if (kind!='research' or p.get('kind')!=kind or type(level) is not int
            or type(before.get('elixir')) is not int or type(p.get('gems_before')) is not int):return False
        def advanced(image):
            rows=[v for v in self.reader.rows(image) if compact(v['name'])==compact(p['name'])]
            return (self.reader.availability(image,'research')==(1,1) and len(rows)==1
                and rows[0].get('target_level')==level+1
                and self.reader.balances(image).get('elixir')==before['elixir']-p['cost']
                and self.menu_gems(image)==p['gems_before'])
        if not advanced(frame) or self.stopped() or not advanced(self.capture.screenshot()):return False
        state['last_completed']=state.pop('pending')|{'phase':'confirmed','level_after':level,
            'receipt':'advanced_level_and_resource_deduction'};write_json(self.path,state)
        return True

    def find_row(self,wanted,kind='buildings'):
        if wanted.get('currency')!='free':return ProgressionRunner.find_row(self,wanted,kind)
        current=self.capture.screenshot()
        if self.reader.menu_kind(current):
            if self.stopped():return None
            self.input.tap(round(current.shape[1]*.984),round(current.shape[0]*.032),jitter=0)
            if self.wait():return None
        frame=self.open_menu(kind)
        if frame is None:return None
        frame=self.clear_filters(frame)
        for _ in range(20):
            if self.stopped() or self.reader.menu_kind(frame)!=kind:return None
            matches=[r for r in self.reader.rows(frame) if row_key(r)==row_key(wanted)]
            if matches:return matches[0],frame
            h,w=frame.shape[:2]
            self.input.swipe(round(w*.87),round(h*.82),round(w*.87),round(h*.40),duration_ms=350)
            if self.wait():return None
            frame=self.capture.screenshot()
        return None

    def scan(self,frame,kind='buildings'):
        inventory=ProgressionRunner.scan(self,frame,kind)
        # Hall badges are verified by the shared scan while their row is still
        # visible. Checking again at the bottom of a long list would reject a
        # correctly read Hall solely because it has scrolled off-screen.
        # The shared scan treats locked/maxed rows as unreadable prices. These
        # explicit native labels do not block an otherwise complete inventory.
        inventory['unknown']=any(r.get('state') not in ('maxed','future_locked')
            and r.get('currency') not in ('gems','free')
            and (not r.get('name') or type(r.get('cost')) is not int or not r.get('currency'))
            for r in inventory['rows'])
        self.inventory=inventory
        write_json(self.config.data_dir/('builder_base/'+kind+'-inventory.json'),inventory|{'at':time.time()})
        return inventory

    def eligibility(self,kind,candidate,balances,availability):
        if kind=='research':
            name=compact(candidate.name)
            if name not in ('ragedbarbarian','sneakyarcher','nightwitch'):
                return 'Builder farming troop identity is not supported'
            if name in {compact(v) for v in self.config.upgrade_excluded_names.split(',')}:
                return 'Excluded in settings'
            if candidate.currency!='elixir':return 'Research requires Builder Elixir'
            if availability!=(1,1):return 'No verified free Star Laboratory'
            balance=balances.get('elixir')
            if type(candidate.cost) is not int or candidate.cost<=0 or type(balance) is not int:
                return 'Research price or balance is unverified'
            if not 0<=balance<=20_000_000 or balance-candidate.cost<self.config.builder_base_elixir_reserve:
                return 'Would fall below the Builder Elixir reserve'
            return None
        if kind!='buildings':return super().eligibility(kind,candidate,balances,availability)
        name=compact(candidate.name)
        if name=='builderhall':
            blockers=hall_blockers(self.inventory)
            if blockers:return '; '.join(blockers)
        if name in ('builderhall','armycamp','wall'):
            check=Candidate('Gold Storage',candidate.cost,candidate.currency,candidate.point)
            if (name=='wall' and self.target and self.target.get('new') and candidate.cost==0
                and candidate.currency=='free'):
                if type(self.target.get('quantity')) is not int or self.target['quantity']<1:return 'Free-wall quantity is unverified'
                if (availability is None or any(type(v) is not int for v in availability)
                    or not 0<=availability[0]<=availability[1]<=3 or not availability[1]
                    or availability[0]<=self.config.builder_base_builders_reserved):return 'No verified spare builder'
                return None
            return eligibility(self.config,check,balances,availability)
        return super().eligibility(kind,candidate,balances,availability)

    def run(self,kind,*,execute=False,expected=None):
        self.target=None
        pending=self.state().get('pending')
        if pending:
            if pending.get('kind')=='construction':
                try:return BuilderConstruction(self).reconcile()
                finally:
                    if not self.stopped():self.close()
            if pending.get('kind')=='wall':
                return {'status':'needs_review','message':'An interrupted Builder payment must be reconciled before another purchase'}
            return super().run(kind,execute=execute,expected=expected)
        if kind=='research':
            frame=self.open_menu(kind)
            if frame is None:return {'status':'stopped'}
            first=self.menu_gems(frame);second=self.menu_gems(self.capture.screenshot())
            self.research_gems=first if type(first) is int and first==second else None
            return super().run(kind,execute=execute,expected=expected)
        try:
            current=self.capture.screenshot()
            if self.reader.home(current):
                bridge=SimpleNamespace(frame=self.map_frame,tap=self.map_tap,wait=self.wait)
                self.capacities=self.reader.storage_capacities(bridge)
            frame=self.open_menu(kind)
            if frame is None:return {'status':'stopped'}
            available=self.reader.availability(frame,kind)
            if available is None or available[0]<=self.config.builder_base_builders_reserved:
                return {'status':'nothing_eligible','message':'No verified spare Builder Base builder'}
            inventory=self.scan(frame)
            inventory['capacities']=self.capacities
            if not inventory['complete']:
                return {'status':'blocked','message':'Builder inventory did not reach the end'}
            rows=[r for r in inventory['rows'] if r.get('state') not in ('maxed','future_locked')
                  and r.get('currency') in ('gold','elixir','free') and type(r.get('cost')) is int]
            new=[r for r in rows if r.get('new') and compact(r['name']) in CONSTRUCTIBLE]
            needs_storage={r['currency'] for r in new if r['currency'] in self.capacities
                and r['cost']>self.capacities[r['currency']]}
            # Resource buildings may be a prerequisite for unaffordable new
            # camps/defenses. Never deadlock all construction behind an amount
            # that cannot fit the game's independently read storage capacity.
            rows=[r for r in rows if not new or r.get('new') or compact(r['name'])=='starlaboratory'
                  or compact(r['name']) in {v+'storage' for v in needs_storage}]
            order={'starlaboratory':0,'armycamp':1,'builderbarracks':2,'goldstorage':3,'elixirstorage':3,'wall':8,'builderhall':9}
            rows.sort(key=lambda r:(0 if compact(r['name'])=='starlaboratory' else 1 if r.get('new') else 2,
                                    order.get(compact(r['name']),5),r['cost']))
            selected=None
            for row in rows:
                self.target=row
                if not self.eligibility(kind,Candidate(row['name'],row['cost'],row['currency'],row['point']),inventory['balances'],available):
                    selected=row;break
            self.target=selected
            if selected is None:return {'status':'nothing_eligible','message':'Waiting for Builder resources, construction or verified progression targets',
                                       'town_hall_blockers':hall_blockers(inventory)}
            token=hashlib.sha256(json.dumps([kind,row_key(selected)]).encode()).hexdigest()
            report={'kind':kind,'status':'ready','selected':selected,'token':token,'balances':inventory['balances'],
                    'availability':available,'inventory':inventory}
            if expected is not None and expected!=token:return report|{'status':'changed'}
            if not execute:return report
            if selected.get('new'):
                return BuilderConstruction(self).start(selected,inventory)
            if compact(selected['name'])=='wall':
                from coc_bot.progression.walls import WallUpgrade
                return WallUpgrade(self).run(selected)
            if self.find_row(selected) is None:return {'status':'changed'}
            # Shared transaction obtains fresh name/resource/price/slot reads.
            return super().run(kind,execute=True)
        finally:
            if not self.stopped():self.close()


class BuilderConstruction:
    def __init__(self,runner):self.r=runner

    def start(self,row,before):
        from coc_bot.progression.construction import Construction,controls
        from coc_bot.builder_base.resources import ResourceReader
        r=self.r;located=r.find_row(row)
        if located is None:return {'status':'changed'}
        fresh,frame=located
        available=r.reader.availability(frame,'buildings');balances=r.reader.balances(frame)
        if balances!=before['balances'] or r.eligibility('buildings',Candidate(row['name'],row['cost'],row['currency'],fresh['point']),balances,available):
            return {'status':'changed'}
        if r.stopped():return {'status':'stopped'}
        r.input.tap(*fresh['point'],jitter=0)
        if r.wait():return {'status':'stopped'}
        # A fixed evidence name bounds storage while keeping unfamiliar
        # native placement appearances available for regression fixtures.
        import cv2
        evidence=r.config.data_dir/'builder_base/placement-before.png'
        evidence.parent.mkdir(parents=True,exist_ok=True)
        cv2.imwrite(str(evidence),r.capture.screenshot())
        placement=Construction(r).locate_space()
        if placement is None:return {'status':'blocked','message':'Builder construction needs a verified legal placement'}
        screen=r.capture.screenshot()
        reader=ResourceReader(r.reader)
        observed=reader.balances(screen)
        resource=row['currency'];cost=row['cost']
        if (r.construction_controls(screen)!=placement
            or any(type(observed.get(k)) is not int for k in ('gold','elixir','gems'))
            or any(observed.get(k)!=balances.get(k) for k in ('gold','elixir'))):
            if not r.stopped():r.input.tap(*placement['cancel'],jitter=0)
            return {'status':'changed','message':'Builder resources or placement changed'}
        state=r.state()
        if state.get('pending'):return {'status':'needs_review'}
        state['pending']={'kind':'construction','phase':'confirming','row':row,'before':observed,
                          'free_before':available,'at':time.time()};write_json(r.path,state)
        if r.stopped():return {'status':'needs_review'}
        r.input.tap(*placement['confirm'],jitter=0)
        if r.wait(.8):return {'status':'needs_review'}
        return self.reconcile()

    def reconcile(self):
        """Read a persisted receipt; never resend its confirmation input."""
        from coc_bot.progression.construction import controls
        from coc_bot.builder_base.resources import ResourceReader
        r=self.r;state=r.state();pending=state.get('pending',{})
        if pending.get('kind')!='construction':return {'status':'needs_review'}
        row=pending.get('row',{});observed=pending.get('before',{})
        resource=row.get('currency');cost=row.get('cost')
        if (resource not in ('gold','elixir','free') or type(cost) is not int
            or type(observed.get('gems')) is not int
            or any(type(observed.get(k)) is not int for k in ('gold','elixir'))):
            return {'status':'needs_review','message':'Builder construction journal is incomplete'}
        reader=ResourceReader(r.reader);expected=dict(observed)
        if resource in ('gold','elixir'):expected[resource]-=cost
        confirmed=False
        for _ in range(6):
            if r.stopped():return {'status':'needs_review'}
            frame=r.capture.screenshot();after=reader.balances(frame)
            placement=r.construction_controls(frame)
            if resource=='free' and placement:
                # Free-wall placement opens another preview from the stack.
                # Cancel the next preview instead of buying/placing again.
                fresh=r.capture.screenshot()
                if r.construction_controls(fresh)!=placement:return {'status':'needs_review'}
                r.input.tap(*placement['cancel'],jitter=0)
                if r.wait():return {'status':'needs_review'}
                continue
            if after==expected and placement is None:
                fresh=r.capture.screenshot()
                if r.construction_controls(fresh) is None and reader.balances(fresh)==expected:
                    confirmed=True;break
            if r.wait(.5):return {'status':'needs_review'}
        if not confirmed:
            return {'status':'needs_review','message':'Builder construction payment outcome is uncertain; repeat purchases blocked'}
        # Free walls need an independent inventory decrement because no payment
        # or lasting occupied builder can prove that a wall was constructed.
        if resource=='free':
            opened=r.open_menu('buildings');inventory=r.scan(opened)
            matches=[v for v in inventory['rows'] if compact(v['name'])=='wall' and v.get('new')]
            left=sum(v.get('quantity') or 0 for v in matches)
            unknown_new=any(v.get('new') and (not compact(v.get('name','')) or
                              compact(v['name'])=='wall' and type(v.get('quantity')) is not int)
                            for v in inventory['rows'])
            # A positively identified remaining stack is independent evidence.
            # An unrelated unreadable New building must not invalidate it. A
            # disappearing final stack still requires every New row readable.
            invalid_stack=any(type(v.get('quantity')) is not int or v.get('currency')!='free'
                              or v.get('cost')!=0 for v in matches)
            if (not inventory['complete'] or invalid_stack or len(matches)>1
                or not matches and unknown_new or left!=(row.get('quantity') or 0)-1):
                return {'status':'needs_review','message':'Free-wall quantity did not independently verify'}
            if matches:
                observed=r.find_row(matches[0])
                if observed is None:return {'status':'needs_review'}
                second=[v for v in r.reader.rows(r.capture.screenshot())
                        if compact(v['name'])=='wall' and v.get('new')]
                if (len(matches)!=1 or len(second)!=1
                    or second[0].get('quantity')!=left or second[0].get('currency')!='free'
                    or second[0].get('cost')!=0):
                    return {'status':'needs_review','message':'Free-wall quantity changed during receipt verification'}
        state['last_completed']=state.pop('pending')|{'phase':'confirmed','after':expected}
        state.pop('deferred_receipt',None)
        write_json(r.path,state)
        from coc_bot.runtime.verification import resolve_receipt
        resolve_receipt(r.config,pending)
        return {'status':'started','message':row['name']+' construction confirmed','spent':cost,'currency':resource}
