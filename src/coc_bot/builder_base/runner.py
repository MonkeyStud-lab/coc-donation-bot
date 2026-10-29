"""One bounded Builder Base visit under the bot's existing device lease.

The journal is written before leaving Home Village. Interrupted visits recover
without redeploying troops or repeating spending and never enter home recovery.
"""
from pathlib import Path
import json
import time
import uuid

import cv2
import numpy as np
from loguru import logger

from coc_bot.adb.client import AdbStopped
from coc_bot.adb.multitouch import Multitouch
from coc_bot.attack.camera import compare_camera
from coc_bot.attack.mapping import boundary_mask
from coc_bot.stop import interrupted_sleep
from coc_bot.upgrades.runner import write_json
from coc_bot.accounts.store import read
from coc_bot.builder_base.vision import BuilderReader
from coc_bot.builder_base.upgrades import BuilderUpgradeRunner


def state_path(config):
    return config.data_dir/'builder_base/visit.json'


def state(config):
    path = state_path(config)
    if not path.exists():
        return {}
    try:
        result = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(result, dict):
            raise ValueError('Expected an object')
        return result
    except (OSError, ValueError) as exc:
        raise RuntimeError('Builder Base journal is unreadable; review it before restarting') from exc


def pending(config):
    return bool(state(config).get('phase') or read(config.data_dir/'builder_base/upgrades.json',{}).get('pending'))


def deployment_points(frame):
    """Use the left boundary where visible; otherwise test clear arena tiles.

    These are bounded placement attempts, not a claim of legal-zone detection.
    A card's deployed state must change before moving on. No pan coordinates
    are reused across stages, and no tap is allowed outside the battlefield.
    """
    h, w = frame.shape[:2]
    mask = boundary_mask(frame)
    points = []
    lines = cv2.HoughLinesP(mask,1,np.pi/360,threshold=35,
                            minLineLength=round(w*.045),maxLineGap=4)
    if lines is not None:
        for x1,y1,x2,y2 in sorted(lines.reshape(-1,4),key=lambda v:-np.hypot(v[2]-v[0],v[3]-v[1])):
            dx,dy = float(x2-x1),float(y2-y1)
            x,y = (x1+x2)/2,(y1+y2)/2
            if not dx or not .4 < abs(dy/dx) < 1.05 or not w*.25 < x < w*.48:
                continue
            normal = np.array([-dy,dx])/np.hypot(dx,dy)
            if normal[0] > 0:
                normal = -normal
            # Try several positions along an observed edge. One midpoint can
            # coincide with an obstacle even when the rest of that edge is clear.
            for fraction in (.5,.25,.75):
                for offset in (.025,.04):
                    location=np.array([x1+dx*fraction,y1+dy*fraction])+normal*w*offset
                    points.append(tuple(np.rint(location).astype(int)))
    # A line midpoint can land on a rock/building. Count accepted terrain,
    # rather than raw Hough candidates, before excluding bounded fallbacks.
    points += [(round(w*x), round(h*y)) for x,y in ((.32,.46),(.33,.51),(.35,.56))]
    # Reject forests/water/HUD and busy artwork in the candidate patch. This
    # deliberately supports the observed default Builder Base arenas only.
    accepted = []
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    for x,y in points:
        if not w*.20 < x < w*.60 or not h*.25 < y < h*.64:
            continue
        patch = hsv[y-8:y+9,x-8:x+9]
        # Inspected default and winter Builder tile palettes. This is only a
        # bounded placement attempt; the army count receipt proves acceptance.
        normal_tiles=cv2.inRange(patch,(65,20,35),(120,170,180))
        winter_tiles=cv2.inRange(patch,(108,25,80),(140,150,225))
        tiles = cv2.bitwise_or(normal_tiles,winter_tiles).mean()/255
        if tiles > .75 and gray[y-8:y+9,x-8:x+9].std() < 22 and (x,y) not in accepted:
            accepted.append((x,y))
    return accepted[:18]


class BuilderBaseRunner:
    def __init__(self, config, capture, input_ctrl, navigator, client, stop=None):
        self.config, self.capture, self.input = config, capture, input_ctrl
        self.nav, self.client, self.stop = navigator, client, stop
        self.reader = BuilderReader(stop)
        self.record = state(config)
        self.folder = config.data_dir/'debug/builder-base'/uuid.uuid4().hex
        self.sequence = 0

    def check(self):
        if self.stop and self.stop():
            raise AdbStopped('Builder Base stopped')

    def wait(self, seconds=.6):
        if interrupted_sleep(seconds, self.stop):
            self.check()

    def phase(self, phase):
        self.record['phase'] = phase
        self.record['updated_at'] = time.time()
        write_json(state_path(self.config), self.record)
        logger.info('Activity: Builder Base — {}', phase.replace('_',' '))

    def frame(self):
        self.check()
        frame = self.capture.screenshot()
        self.check()
        return frame

    def evidence(self, frame, name):
        if self.sequence >= 32:
            return
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            self.sequence += 1
            cv2.imwrite(str(self.folder/f'{self.sequence:03}-{name}.png'), frame)
        except OSError as exc:
            logger.warning('Builder Base evidence could not be saved: {}', exc)

    def tap(self, point):
        self.check()
        if self.config.dry_run:
            raise ValueError('Builder Base actions are disabled in practice mode')
        self.input.tap(*point, jitter=0)

    def zoom(self, frame):
        self.check()
        if self.client.wm_size() != (frame.shape[1], frame.shape[0]):
            raise ValueError('Builder Base input dimensions differ from screenshot')
        with Multitouch(self.client, (frame.shape[1], frame.shape[0])) as touch:
            touch.pinch()
        self.wait()
        return self.frame()

    def home_village(self, frame):
        from coc_bot.vision.battle_menu import home_build_control_visible
        return (not self.reader.home(frame) and not self.reader.battle(frame)
                and not self.reader.result_button(frame)
                and home_build_control_visible(frame)
                and self.nav.classifier._open_chat_icon_visible(frame))

    def boat(self, *, returning, allow_setup=True):
        frame = self.frame()
        verify = self.reader.home if returning else self.home_village
        if not verify(frame):
            frame = self.settle_village(verify)
        for attempt in range(6):
            if not verify(frame):
                frame = self.settle_village(verify)
            if not returning and allow_setup:
                from coc_bot.builder_base.onboarding import BuilderOnboarding
                flow=BuilderOnboarding(self)
                if flow.select_setup_boat(frame):
                    flow.drive()
                    return self.frame()
            point = self.reader.find(frame, 'boat_return' if returning else 'boat', (.14,.12,.90,.80), threshold=.86)
            if point:
                second = self.frame()
                again = self.reader.find(second, 'boat_return' if returning else 'boat', (.14,.12,.90,.80), threshold=.86)
                # The boat's bubble bobs by several pixels while the camera is
                # stationary. Reacquire its center; tolerate only movement well
                # inside that verified bubble, never a reused map coordinate.
                if not verify(second) or again is None or np.linalg.norm(np.array(point)-again)>max(5,second.shape[1]*.008):
                    raise ValueError('Boat moved; navigation stopped')
                self.tap(again)
                for _ in range(10):
                    self.wait(1)
                    frame = self.frame()
                    from coc_bot.builder_base.onboarding import BuilderOnboarding
                    flow=BuilderOnboarding(self)
                    if allow_setup and flow.dialog(frame) and flow.advance_dialog():continue
                    if (self.home_village(frame) if returning else self.reader.home(frame)):
                        return frame
                raise ValueError('Boat tap did not confirm the destination village')
            if attempt == 5:
                break
            if attempt == 0:
                frame = self.zoom(frame)
                continue
            h,w = frame.shape[:2]
            gesture = (.62,.36,.40,.66) if returning else (.40,.62,.62,.38)
            if attempt % 2 == 0:
                gesture = (.65,.62,.38,.62) if returning else (.38,.45,.65,.45)
            self.check()
            self.input.swipe(round(w*gesture[0]),round(h*gesture[1]),round(w*gesture[2]),round(h*gesture[3]),duration_ms=300)
            self.wait()
            frame = self.frame()
        self.evidence(frame,'boat-not-found')
        raise ValueError('Boat not found after bounded camera search')

    def settle_village(self, verify):
        from coc_bot.progression.home import recover_home_overlay
        from coc_bot.builder_base.onboarding import BuilderOnboarding
        for _ in range(8):
            frame = self.frame()
            from coc_bot.builder_base.tutorials import recover
            if recover(self,frame):continue
            button = self.reader.reward_button(frame)
            if button:
                second = self.frame()
                button = self.reader.reward_button(second)
                if button:
                    logger.info('Builder Base: acknowledging verified Star Bonus')
                    self.tap(button)
            elif BuilderOnboarding(self).dialog(frame) and BuilderOnboarding(self).advance_dialog():
                pass
            elif recover_home_overlay(self.nav,frame):
                pass
            elif verify(frame):
                return frame
            self.wait(1)
        raise ValueError('Village controls not verified after waiting for transitions/rewards')

    def enter(self):
        from coc_bot.builder_base.onboarding import BuilderOnboarding
        flow=BuilderOnboarding(self)
        frame = self.frame()
        if self.reader.home(frame):
            if flow.state().get('phase') not in (None,'complete'):flow.drive()
            self.phase('builder_home')
            return
        setup=flow.state()
        if (setup.get('account')==self.config.account_tag
            and setup.get('phase') in ('selecting_boat','first_sail_requested')
            and self.home_village(frame)):
            # Account verification can deselect the boat. Reacquire that owned
            # navigation target instead of assuming its action tiles stayed open.
            self.phase('travelling_to_builder_base')
            if self.reader.selected_boat_rebuild(frame) or flow.dialog(frame) or flow.prepare():flow.drive()
            else:self.boat(returning=False)
            self.phase('builder_home')
            return
        if not self.nav.ensure_clan_chat():
            raise ValueError('Cannot establish Home Village before Builder Base visit')
        frame = self.frame()
        if getattr(self.config,'donation_enabled',True):
            if not self.nav.classifier._clan_chat_anchor_visible(frame):
                raise ValueError('Clan chat was not verified')
            self.nav.close_clan_chat(frame)
        elif not self.home_village(frame):
            raise ValueError('Home Village was not verified')
        self.wait()
        self.phase('travelling_to_builder_base')
        if flow.prepare():flow.drive()
        else:self.boat(returning=False)
        self.phase('builder_home')

    def finish(self):
        frame = self.frame()
        if self.reader.daily_reward_close(frame):
            from coc_bot.builder_base.tutorials import recover
            if recover(self,frame):frame=self.frame()
        if self.reader.reward_button(frame):
            frame = self.settle_village(self.reader.home)
        if self.reader.home(frame):
            self.phase('returning_to_home_village')
            self.boat(returning=True)
        frame = self.frame()
        if not (self.home_village(frame) or self.nav.classifier._clan_chat_anchor_visible(frame)):
            raise ValueError('Home Village not verified; donation recovery blocked')
        if not self.nav.ensure_clan_chat():
            raise ValueError('Could not confirm clan chat after Builder Base visit')
        self.record.pop('phase', None)
        self.record['last_finished_at'] = time.time()
        self.record['next_visit_at'] = time.time()+self.config.builder_base_interval_seconds
        write_json(state_path(self.config), self.record)
        from coc_bot.runtime.screenshot_retention import prune_attack_diagnostics
        prune_attack_diagnostics(self.config.data_dir)

    def attack(self):
        frame = self.frame()
        if not self.reader.home(frame):
            raise ValueError('Builder Base home is required to start an attack')
        self.phase('opening_attack')
        self.tap((round(frame.shape[1]*.065),round(frame.shape[0]*.89)))
        self.wait()
        frame = self.frame()
        if not self.reader.attack_menu(frame):
            raise ValueError('Builder Base Start Attack dialog not verified')
        from coc_bot.builder_base.starter import army as starter_army
        starter=starter_army(self.reader,frame)
        supported=self.reader.supported_army(frame)
        if not supported and starter is None:
            from coc_bot.builder_base.army import empty_attack,repair
            if empty_attack(self.reader,frame) and repair(self):
                frame=self.frame();starter=starter_army(self.reader,frame)
                if self.reader.home(frame) and self.reader.home(self.frame()):
                    # Choose Army replaces the preflight modal and closes to
                    # the village. Reopen it before interpreting any army card.
                    self.tap((round(frame.shape[1]*.065),round(frame.shape[0]*.89)))
                    self.wait();frame=self.frame();starter=starter_army(self.reader,frame)
                supported=self.reader.supported_army(frame)
        second=self.frame()
        if (not supported and starter is None or not self.reader.attack_menu(second)
            or supported and not self.reader.supported_army(second)
            or starter is not None and starter_army(self.reader,second)!=starter):
            self.evidence(frame, 'unsupported-army')
            closing=self.frame()
            if self.reader.attack_menu(closing) and self.reader.attack_menu(self.frame()):
                self.tap((round(closing.shape[1]*.853),round(closing.shape[0]*.182)))
                self.wait()
            elif not (self.reader.home(closing) and self.reader.home(self.frame())):
                raise ValueError('Unsupported Builder army left an unknown menu; no close tap sent')
            self.phase('builder_home')
            logger.warning('Builder Base attack skipped: army is not a verified supported composition')
            return {'status':'unsupported_army'}
        for key in ('starter_army','starter_sent','starter_confirmed'):self.record.pop(key,None)
        if starter is not None:self.record['starter_army']=starter
        self.phase('matchmaking')
        self.tap(self.reader.find(second,'find_now',(.65,.60,.84,.72)))
        for _ in range(30):
            self.wait(1)
            frame = self.frame()
            if self.reader.battle(frame):
                self.phase('battle')
                return self.watch_battle(deploy=True)
        raise ValueError('Builder Base matchmaking timed out; checkpoint retained')

    def watch_battle(self, *, deploy=False):
        if self.record.get('starter_army'):
            from coc_bot.builder_base.starter import watch
            return watch(self,deploy=deploy)
        deadline = time.monotonic()+480
        attempts = {}; abilities = {}; zoomed = False
        fighting = False
        stage = 1
        count = 0
        placement_frame = None
        placement_targets = []
        while time.monotonic() < deadline:
            frame = self.frame()
            from coc_bot.builder_base.tutorials import recover
            if recover(self,frame):continue
            point = self.reader.result_button(frame)
            if point:
                self.evidence(frame,'battle-results')
                second = self.frame()
                point = self.reader.result_button(second)
                if point:
                    self.phase('leaving_results')
                    self.tap(point)
                    self.wait(2)
                continue
            if self.reader.home(frame):
                self.phase('builder_home')
                return {'status':'returned' if count or not deploy else 'no_verified_deployment',
                        'verified_deployments':count}
            if not self.reader.battle(frame):
                self.wait(1)
                continue
            if not deploy:
                self.wait(3)
                continue
            scouting = bool(self.reader.find(frame, 'battle_starts', (.43,.012,.57,.055)))
            if scouting and fighting:
                stage += 1
                if stage > 2:
                    raise ValueError('Unexpected additional Builder Base stage')
                logger.info('Builder Base: second stage — rebuilding deployment targets')
                zoomed = False
                placement_frame = None
                placement_targets = []
                attempts.clear()
                abilities.clear()
                fighting = False
            elif not scouting:
                fighting = True
            cards = self.reader.cards(frame)
            ready = sorted([c for c in cards if not c['deployed'] and attempts.get((c['slot'],c['unit']),0)<6],
                           key=lambda c: (c['slot']==0, c['slot']))
            if ready:
                if not zoomed:
                    frame = self.zoom(frame)
                    if not self.reader.battle(frame):
                        continue
                    zoomed = True
                    placement_frame = None
                    placement_targets = []
                    self.evidence(frame, 'stage-view')
                card = ready[0]
                second = self.frame()
                same = next((c for c in self.reader.cards(second) if c['slot']==card['slot']
                             and c['unit']==card['unit'] and not c['deployed']),None)
                if same:
                    self.tap(same['point'])
                    self.wait(.15)
                    before = self.frame()
                    after = self.frame()
                    motion = compare_camera(before, after)
                    if not self.reader.battle(after) or not motion['verified'] or abs(motion['scale']-1)>.003:
                        self.wait(1)
                        continue
                    transform = np.array(motion['transform'])
                    if max(abs(transform[0,2]),abs(transform[1,2]))>3:
                        continue
                    # The red boundary disappears after the first unit lands.
                    # Retain its targets only while artwork verifies the same
                    # camera and map; discard them on every stage transition.
                    if placement_frame is None:
                        placement_targets = deployment_points(after)
                        placement_frame = after.copy() if placement_targets else None
                    points = placement_targets
                    if placement_frame is not None:
                        alignment = compare_camera(placement_frame, after)
                        if (not alignment['verified'] or abs(alignment['scale']-1)>.003
                            or max(abs(np.array(alignment['transform'])[:2,2]))>3):
                            self.wait(.3)
                            continue
                    key = (card['slot'],card['unit'])
                    attempt = attempts.get(key,0)
                    attempts[key] = attempt+1
                    if points:
                        self.tap(points[attempt % len(points)])
                        self.wait(.4)
                        check = self.frame()
                        if attempt < 2:
                            self.evidence(check, f'slot-{card["slot"]}-attempt-{attempt}')
                        updated = next((c for c in self.reader.cards(check) if c['slot']==card['slot']
                                        and c['unit']==card['unit']),None)
                        if updated and updated['deployed']:
                            count += 1
                            logger.info('Builder Base: deployment confirmed for {} slot {}',card['unit'],card['slot'])
                            self.evidence(check,'deployment-confirmed')
                            abilities.pop(key,None)
                    else:
                        logger.warning('Builder Base: no clear placement tile; waiting for a supported view')
            else:
                for card in cards:
                    key = (card['slot'],card['unit'])
                    cooldown = 15 if card['unit'] != 'night_witch' else 480
                    if not card['deployed'] or time.monotonic()-abilities.get(key,-1000)<cooldown:
                        continue
                    fresh = self.frame()
                    valid = next((c for c in self.reader.cards(fresh) if c['slot']==card['slot']
                                  and c['unit']==card['unit'] and c['deployed']),None)
                    if valid:
                        self.tap(valid['point'])
                        abilities[key] = time.monotonic()
                self.wait(2)
        raise ValueError('Builder Base battle did not reach verified results/home within eight minutes')

    def recover(self):
        payment=read(self.config.data_dir/'builder_base/upgrades.json',{}).get('pending')
        if not self.record.get('phase') and not payment:
            return
        if self.record.get('phase') == 'collection_needs_review':
            raise ValueError('Builder Base gem balance changed during collection; review the saved evidence and visit journal before resuming')
        logger.info('Recovering interrupted Builder Base visit without new deployments')
        if payment:
            if self.record.get('phase') in ('battle','matchmaking','leaving_results'):
                raise ValueError('Builder payment and battle checkpoints disagree; no recovery input sent')
            if not self.record.get('phase'):self.phase('checking_upgrades')
            frame=self.frame()
            if not self.reader.home(frame):
                if not (self.home_village(frame) or self.nav.classifier._clan_chat_anchor_visible(frame)):
                    raise ValueError('Builder payment recovery needs a verified village before travel')
                from types import SimpleNamespace
                from coc_bot.accounts.navigation import verify_session
                verify_session(SimpleNamespace(config=self.config,capture=self.capture,input=self.input,
                               nav_input=self.input,navigator=self.nav),self.stop or (lambda:False))
                if not self.nav.ensure_clan_chat():raise ValueError('Home village did not verify before receipt recovery')
                if getattr(self.config,'donation_enabled',True):self.nav.close_clan_chat(self.frame())
                self.wait();self.phase('travelling_to_builder_base')
                self.boat(returning=False,allow_setup=False)
                self.phase('checking_upgrades')
            from coc_bot.builder_base.progression import BuilderProgressionRunner
            receipt=BuilderProgressionRunner(self.config,self.capture,self.input,self.nav,self.stop)
            kind=payment.get('kind')
            if kind not in ('construction','wall','buildings','research'):
                raise ValueError('Unknown Builder payment category; no recovery input sent')
            receipt.run('research' if kind=='research' else 'buildings',execute=False)
            if receipt.state().get('pending'):
                raise ValueError('Builder payment needs receipt verification before leaving this account')
        from coc_bot.builder_base.onboarding import BuilderOnboarding
        flow=BuilderOnboarding(self)
        if flow.state().get('phase') not in (None,'complete'):
            flow.drive()
            self.finish()
            return
        frame = self.frame()
        # A reconnect can leave the free welcome notice over either village.
        # Dismiss only known non-purchase overlays before inspecting recovery.
        from coc_bot.progression.home import recover_home_overlay
        for _ in range(4):
            if not recover_home_overlay(self.nav,frame):break
            if self.wait(.5):return
            frame=self.frame()
        if self.record.get('phase')=='editing_army':
            from coc_bot.builder_base.army import close as close_army,editor_close
            if editor_close(self.reader,frame) is not None:
                if not close_army(self):raise ValueError('Builder army editor could not be recovered')
                frame=self.frame()
        if (self.record['phase']=='checking_upgrades' and
            getattr(self.config,'builder_base_progression_enabled',False)):
            from coc_bot.builder_base.progression import BuilderProgressionRunner
            BuilderProgressionRunner(self.config,self.capture,self.input,self.nav,self.stop).close()
            frame=self.frame()
        if self.reader.research_sorting(frame) is True:
            BuilderUpgradeRunner(self.config,self.capture,self.input,self.nav,self.stop).close()
            frame=self.frame()
            if self.reader.research_sorting(frame) is True:
                raise ValueError('Builder research sorting did not close during recovery')
        from coc_bot.builder_base.resources import ResourceCollector
        from coc_bot.builder_base.tutorials import recover as recover_tutorial
        for _ in range(16):
            if not recover_tutorial(self,frame):break
            frame=self.frame()
        collector = ResourceCollector(self)
        if collector.reader.cart(frame):
            # Recovery closes the cart without claiming/spending anything.
            collector.close_cart()
            frame = self.frame()
        if self.reader.battle(frame) or self.reader.result_button(frame) or self.record['phase']=='matchmaking':
            self.watch_battle(deploy=False)
        else:
            close = self.reader.detail_close(frame)
            if close:
                self.tap(close); self.wait(); frame = self.frame()
            if self.reader.menu_kind(frame):
                self.tap((round(frame.shape[1]*.984),round(frame.shape[0]*.032)))
                self.wait()
            elif self.reader.attack_menu(frame):
                self.tap((round(frame.shape[1]*.853),round(frame.shape[0]*.182)))
                self.wait()
        self.finish()

    def run(self, *, refill=False):
        if self.config.dry_run:
            return {'status':'practice_skipped'}
        if self.record.get('phase') or pending(self.config):
            self.recover()
            return {'status':'recovered'}
        self.enter()
        report = {}
        if getattr(self.config, 'builder_base_collect_resources', False):
            from coc_bot.builder_base.resources import ResourceCollector
            report['collection'] = ResourceCollector(self).run()
        if refill and self.config.builder_base_attacks_enabled:
            report=self.refill_resources(report)
            if report.get('visit_repeat'):
                self.finish()
                return report
        def upgrade():
            self.phase('checking_upgrades')
            progression=getattr(self.config,'builder_base_progression_enabled',False)
            if progression:
                from coc_bot.builder_base.progression import BuilderProgressionRunner
                runner=BuilderProgressionRunner(self.config,self.capture,self.input,self.nav,self.stop)
            else:runner = BuilderUpgradeRunner(self.config,self.capture,self.input,self.nav,self.stop)
            choices=[]
            if progression and self.config.builder_base_upgrades_enabled:choices.append('buildings')
            if getattr(self.config,'builder_base_research_enabled',False): choices.append('research')
            if self.config.builder_base_upgrades_enabled: choices.extend(['buildings']*(2 if progression else 3))
            result={'status':'disabled'}
            completed=[]
            paused=[]
            for kind in choices:
                result=runner.run(kind,execute=True)
                logger.info('Builder Base {} upgrade: {}',kind,result.get('status'))
                if result.get('status') in ('started','built','recovered'):
                    completed.append(result)
                    continue  # The previous transaction is already confirmed.
                if (result.get('status') in ('blocked','changed')
                    and not runner.state().get('pending')):
                    paused.append(result)
                    continue  # An unrecognized pre-payment dialog owns no funds.
                # A busy lab does not prevent using a free builder. Each later
                # purchase obtains fresh slot, balance and confirmation reads.
                if result.get('status') in ('nothing_eligible','skipped','busy','waiting'):
                    if kind=='buildings' and not progression:break
                    continue
                return result|{'completed_operations':completed,'paused_operations':paused}
            report=(completed[-1]|{'completed_operations':completed}) if completed else result
            return report|{'paused_operations':paused} if paused else report
        upgrades=(self.config.builder_base_upgrades_enabled or
                  getattr(self.config,'builder_base_research_enabled',False))
        if upgrades:
            report['upgrade']=upgrade()
            if refill and report['upgrade'].get('paused_operations'):
                report.update(retry_at=time.time()+900,message='Some Builder upgrade checks need another observation')
        if self.config.builder_base_attacks_enabled and not refill:
            if upgrades and report['upgrade'].get('status') in ('needs_review','changed','blocked','stopped'):
                report['attack']={'status':'blocked','message':'Upgrade outcome must be resolved before farming'}
                self.finish()
                return report
            from coc_bot.builder_base.demand import farming_demand
            observation = self.resource_demand()
            demand = farming_demand(observation,
                buildings=self.config.builder_base_upgrades_enabled,
                research=getattr(self.config,'builder_base_research_enabled',False),
                reserved=self.config.builder_base_builders_reserved,
                reserves={'gold':self.config.builder_base_gold_reserve,
                          'elixir':self.config.builder_base_elixir_reserve})
            self.record['resource_demand']=observation|{'attack':demand.attack,'reason':demand.reason}
            self.phase('builder_home')
            logger.info('Builder Base farming: {}',demand.reason)
            report['attack'] = self.attack() if demand.attack else {'status':'not_needed','message':demand.reason}
            if demand.attack and report['attack'].get('status')!='unsupported_army' and getattr(self.config, 'builder_base_collect_resources', False):
                report['collection_after_attack'] = ResourceCollector(self).run()
            if demand.attack and upgrades and report['upgrade'].get('status')=='nothing_eligible':
                report['upgrade']=upgrade()
        self.finish()
        if refill and not report.get('retry_at') and report.get('upgrade',{}).get('completed_operations'):
            # Return Home between bounded upgrade batches so the coordinator
            # can check chat. The next pass rescans every slot/payment afresh.
            report['visit_repeat']=True
        return report

    def refill_resources(self, report):
        from coc_bot.accounts.store import write
        from coc_bot.runtime.resource_farming import decide,record_outcome
        from coc_bot.builder_base.resources import ResourceReader
        path=self.config.data_dir/'resources/builder.json'
        saved=read(path,{})
        if time.time()<saved.get('retry_at',0):
            return report|{'retry_at':saved['retry_at'],'message':saved.get('message','Builder farming paused')}
        saved.pop('retry_at',None)
        reader=ResourceReader(self.reader)
        first,second=reader.balances(self.frame()),reader.balances(self.frame())
        observation={'resources':['gold','elixir'],
                     'balances':{r:second.get(r) for r in ('gold','elixir') if first.get(r)==second.get(r)},
                     'capacities':self.reader.storage_capacities(self)}
        decision=decide(observation,saved,start=self.config.farm_resource_start_percent,
                        stop=self.config.farm_resource_target_percent)
        saved.update(observation=observation,observed_at=time.time(),message=decision.message,status=decision.status)
        if decision.status=='unverified' or decision.attack and saved.get('no_progress',0)>=3:
            saved.update(retry_at=time.time()+900,no_progress=0,
                         message='Builder resource readings or repeated attacks need another check')
            write(path,saved)
            return report|{'retry_at':saved['retry_at'],'message':saved['message']}
        write(path,saved)
        if decision.attack:
            report['attack']=self.attack()
            if report['attack'].get('status')=='unsupported_army':
                saved.update(retry_at=time.time()+900,message='Builder army is unsupported')
            else:
                if getattr(self.config,'builder_base_collect_resources',False):
                    from coc_bot.builder_base.resources import ResourceCollector
                    report['collection_after_attack']=ResourceCollector(self).run()
                after=reader.balances(self.frame())
                if any(type(after.get(r)) is not int for r in decision.resources):
                    saved.update(retry_at=time.time()+300,message='Post-battle Builder resources are unreadable')
                else:record_outcome(saved,observation['balances'],after,decision.resources)
            write(path,saved)
            return report|{'visit_repeat':not saved.get('retry_at'),
                           'retry_at':saved.get('retry_at'),'message':saved.get('message')}
        return report

    def resource_demand(self):
        """Two fresh upgrade-menu observations before any new attack."""
        from coc_bot.builder_base.upgrades import supported_building
        from coc_bot.upgrades.vision import Candidate
        from coc_bot.upgrades.vision import compact
        progression=getattr(self.config,'builder_base_progression_enabled',False)
        if progression:
            from coc_bot.builder_base.progression import BuilderProgressionRunner
            runner=BuilderProgressionRunner(self.config,self.capture,self.input,self.nav,self.stop)
        else:runner=BuilderUpgradeRunner(self.config,self.capture,self.input,self.nav,self.stop)
        report={'builders':None,'lab':None,'balances':{},'capacities':{},'targets':[]}
        try:
            for kind in ('buildings','research'):
                enabled=(self.config.builder_base_upgrades_enabled if kind=='buildings' else
                         getattr(self.config,'builder_base_research_enabled',False))
                if not enabled:continue
                first=runner.open_menu(kind)
                if first is None:break
                a=runner.inspect(kind,first)
                b=runner.inspect(kind,self.frame())
                if a['availability']!=b['availability'] or a['balances']!=b['balances']:continue
                report['builders' if kind=='buildings' else 'lab']=b['availability']
                report['balances']=b['balances']
                if progression:
                    from coc_bot.builder_base.progression import CONSTRUCTIBLE,hall_blockers
                    if b['availability'] is None or not b['availability'][0]:continue
                    inventory=runner.scan(self.frame(),kind)
                    if not inventory['complete']:continue
                    if kind=='buildings' and inventory.get('hall_verified') is True:
                        report.update(hall=inventory['hall'],hall_verified=True,
                                      inventory_at=time.time(),account=self.config.account_tag)
                    rows=[v for v in inventory['rows'] if type(v.get('cost')) is int and v['cost']>0
                          and v.get('currency') in ('gold','elixir') and v.get('state') not in ('maxed','future_locked')]
                    order={'starlaboratory':0,'armycamp':1,'goldstorage':2,'elixirstorage':2}
                    rows.sort(key=lambda v:order.get(compact(v['name']),3))
                    currencies=set()
                    for row in rows:
                        name=compact(row['name'])
                        resource=row['currency']
                        floor=getattr(self.config,'builder_base_'+resource+'_reserve')
                        balance=b['balances'].get(resource)
                        if resource in currencies or type(balance) is not int or balance>=row['cost']+floor:continue
                        supported=(name in CONSTRUCTIBLE or name=='builderhall' and not hall_blockers(inventory)) if kind=='buildings' else (
                            name=='nightwitch' or name=='sneakyarcher' and row.get('target_level')==2)
                        if not supported:continue
                        located=runner.find_row(row,kind)
                        if located is None:continue
                        # The complete inventory nominates a target; a fresh
                        # identical row must still exist before it can justify farming.
                        from coc_bot.progression.reader import row_key
                        fresh=runner.reader.rows(self.frame())
                        if not any(row_key(v)==row_key(row) for v in fresh):continue
                        excluded=name in {compact(n) for n in self.config.upgrade_excluded_names.split(',')}
                        report['targets'].append({k:row[k] for k in ('name','currency','cost')}|
                                                 {'kind':kind,'supported':not excluded})
                        currencies.add(resource)
                    continue
                previous={(compact(c['name']),c['currency'],c['cost']) for c in a['recommendations']}
                for c in b['recommendations']:
                    if (compact(c['name']),c['currency'],c['cost']) not in previous:continue
                    supported=(supported_building(Candidate(c['name'],c['cost'],c['currency'],(0,0))) if kind=='buildings'
                               else compact(c['name'])=='nightwitch' and c['currency']=='elixir')
                    excluded=compact(c['name']) in {compact(n) for n in self.config.upgrade_excluded_names.split(',')}
                    report['targets'].append({k:c[k] for k in ('name','currency','cost')}|
                                             {'kind':kind,'supported':supported and not excluded})
        finally:
            if not self.stop or not self.stop():runner.close()
        # Capacity is read from the game's resource details, never inferred from
        # a remembered hall level or a full-looking colored resource bar.
        report['capacities']=self.reader.storage_capacities(self)
        return report
