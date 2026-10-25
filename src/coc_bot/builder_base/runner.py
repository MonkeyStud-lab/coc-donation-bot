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
    return bool(state(config).get('phase'))


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
            points.append(tuple(np.rint(np.array([x,y])+normal*w*.025).astype(int)))
    if len(points) < 2:
        points = [(round(w*x), round(h*y)) for x,y in ((.32,.46),(.33,.51),(.35,.56))]
    # Reject forests/water/HUD and busy artwork in the candidate patch. This
    # deliberately supports the observed default Builder Base arenas only.
    accepted = []
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    for x,y in points:
        if not w*.20 < x < w*.60 or not h*.25 < y < h*.64:
            continue
        patch = hsv[y-8:y+9,x-8:x+9]
        tiles = cv2.inRange(patch,(65,20,35),(120,170,180)).mean()/255
        if tiles > .75 and gray[y-8:y+9,x-8:x+9].std() < 22:
            accepted.append((x,y))
    return accepted


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

    def boat(self, *, returning):
        frame = self.frame()
        verify = self.reader.home if returning else self.home_village
        if not verify(frame):
            frame = self.settle_village(verify)
        for attempt in range(6):
            if not verify(frame):
                frame = self.settle_village(verify)
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
        for _ in range(8):
            frame = self.frame()
            button = self.reader.reward_button(frame)
            if button:
                second = self.frame()
                button = self.reader.reward_button(second)
                if button:
                    logger.info('Builder Base: acknowledging verified Star Bonus')
                    self.tap(button)
            elif verify(frame):
                return frame
            self.wait(1)
        raise ValueError('Village controls not verified after waiting for transitions/rewards')

    def enter(self):
        frame = self.frame()
        if self.reader.home(frame):
            self.phase('builder_home')
            return
        if not self.nav.ensure_clan_chat():
            raise ValueError('Cannot establish Home Village before Builder Base visit')
        frame = self.frame()
        if not self.nav.classifier._clan_chat_anchor_visible(frame):
            raise ValueError('Clan chat was not verified')
        self.nav.close_clan_chat(frame)
        self.wait()
        self.phase('travelling_to_builder_base')
        self.boat(returning=False)
        self.phase('builder_home')

    def finish(self):
        frame = self.frame()
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
        if not self.reader.supported_army(frame):
            self.evidence(frame, 'unsupported-army')
            self.tap((round(frame.shape[1]*.853),round(frame.shape[0]*.182)))
            self.wait()
            self.phase('builder_home')
            logger.warning('Builder Base attack skipped: equip six Night Witches and Battle Machine')
            return {'status':'unsupported_army'}
        self.phase('matchmaking')
        self.tap(self.reader.find(frame,'find_now',(.65,.60,.84,.72)))
        for _ in range(30):
            self.wait(1)
            frame = self.frame()
            if self.reader.battle(frame):
                self.phase('battle')
                return self.watch_battle(deploy=True)
        raise ValueError('Builder Base matchmaking timed out; checkpoint retained')

    def watch_battle(self, *, deploy=False):
        deadline = time.monotonic()+480
        attempts = {}; abilities = {}; zoomed = False
        fighting = False
        stage = 1
        count = 0
        placement_frame = None
        placement_targets = []
        while time.monotonic() < deadline:
            frame = self.frame()
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
        if not self.record.get('phase'):
            return
        if self.record['phase'] == 'collection_needs_review':
            raise ValueError('Builder Base gem balance changed during collection; review the saved evidence and visit journal before resuming')
        logger.info('Recovering interrupted Builder Base visit without new deployments')
        frame = self.frame()
        from coc_bot.builder_base.resources import ResourceCollector
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

    def run(self):
        if self.config.dry_run:
            return {'status':'practice_skipped'}
        if self.record.get('phase'):
            self.recover()
            return {'status':'recovered'}
        self.enter()
        report = {}
        if getattr(self.config, 'builder_base_collect_resources', False):
            from coc_bot.builder_base.resources import ResourceCollector
            report['collection'] = ResourceCollector(self).run()
        def upgrade():
            self.phase('checking_upgrades')
            runner = BuilderUpgradeRunner(self.config,self.capture,self.input,self.nav,self.stop)
            choices=[]
            if getattr(self.config,'builder_base_research_enabled',False): choices.append('research')
            if self.config.builder_base_upgrades_enabled: choices.append('buildings')
            result={'status':'disabled'}
            for kind in choices:
                result=runner.run(kind,execute=True)
                logger.info('Builder Base {} upgrade: {}',kind,result.get('status'))
                # An uncertain transaction must block all subsequent spending.
                if result.get('status') not in ('nothing_eligible','skipped'):
                    break
            return result
        upgrades=(self.config.builder_base_upgrades_enabled or
                  getattr(self.config,'builder_base_research_enabled',False))
        if upgrades:
            report['upgrade']=upgrade()
        if self.config.builder_base_attacks_enabled:
            report['attack'] = self.attack()
            if getattr(self.config, 'builder_base_collect_resources', False):
                report['collection_after_attack'] = ResourceCollector(self).run()
            if upgrades and report['upgrade'].get('status')=='nothing_eligible':
                report['upgrade']=upgrade()
        self.finish()
        return report
