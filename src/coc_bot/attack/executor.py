"""One measured action at a time. An uncertain map tap is never replayed."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import time
import uuid

import cv2
import numpy as np
from loguru import logger

from coc_bot.attack.army import check_stop, resolve_live_card, resolve_just_depleted
from coc_bot.attack.camera import compare_camera
from coc_bot.attack.projection import input_area, step_points, validate_geometry
from coc_bot.attack.survey import affine
from coc_bot.attack.battle_gate import BattleFrameGate
from coc_bot.adb.client import AdbStopped
from coc_bot.vision.battle_menu import active_battle_ready


@dataclass
class ExecutionResult:
    success: bool
    reason: str
    verified_taps: int = 0
    first_deploy_at: float | None = None
    uncertain_tap: bool = False
    first_attempt_at: float | None = None


def selected_card(frame, card):
    """Selection is a bright, low-saturation outline on all four card edges."""
    x,y,w,h=card.box
    crop=frame[y:y+h,x:x+w]
    if not crop.size: return False
    white=cv2.inRange(cv2.cvtColor(crop,cv2.COLOR_BGR2HSV),(0,0,195),(180,65,255))>0
    pad=max(3,round(w*.06))
    return (white[pad:-pad,:pad].any(axis=1).mean()>.75 and
            white[pad:-pad,-pad:].any(axis=1).mean()>.75 and
            # Equipment chips can join the card contour above its top edge.
            # Require a continuous horizontal border within that header band,
            # plus both long side borders and the bottom (never portrait alone).
            white[:max(pad,round(h*.25)),pad:-pad].mean(axis=1).max()>.75 and
            # The dark contour can include the card's lower drop shadow.
            white[-max(pad,round(h*.12)):,pad:-pad].any(axis=0).mean()>.75)


def hero_health_visible(frame, card, *, allow_low=False):
    x,y,w,h=card.box
    # A newly deployed card can rise a few pixels above its portrait contour.
    # Include that small header margin, but require the bar's dark enclosure.
    crop=frame[max(0,y-round(h*.04)):y+round(h*.30),x:x+w]
    hsv=cv2.cvtColor(crop,cv2.COLOR_BGR2HSV)
    mask=cv2.inRange(hsv,(35,90,90),(75,255,255))
    if allow_low:
        # A verified deployed hero can be wounded by the time its ability runs.
        # Red/yellow health still counts, but only inside the narrow header
        # widget, with the same dark enclosure as a full green health bar.
        mask |= cv2.inRange(hsv,(0,100,100),(35,255,255))
        mask |= cv2.inRange(hsv,(170,100,100),(180,255,255))
        mask=cv2.morphologyEx(mask,cv2.MORPH_OPEN,np.ones((3,3),np.uint8))
    contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    # A cyan selection-edge highlight is not a health bar. Require a filled
    # green strip with meaningful height, not a one-pixel antialiasing line.
    for contour in contours:
        bx,by,bw,bh=cv2.boundingRect(contour)
        width_ok=(bw>w*.50 and bw/bh>=5) or (allow_low and
                  bw>w*.12 and bw/bh>=1.5 and bx<w*.20 and by<h*.12)
        if (width_ok and h*.025<=bh<h*.15 and
                bx>=w*.03 and bx+bw<=w*.97 and by>=max(2,h*.01) and
                cv2.contourArea(contour)/(bw*bh)>.70):
            rim=max(2,round(h*.02))
            dark=hsv[:,:,2]<110
            above=dark[max(0,by-rim):by,bx:bx+bw]
            below=dark[by+bh:by+bh+rim,bx:bx+bw]
            if above.size and below.size and above.mean()>.35 and below.mean()>.35:
                return True
    return False


class VerifiedExecutor:
    def __init__(self, session, plan, projection, reference, catalog, *, journal_dir=None):
        validate_geometry(plan,projection)
        self.session,self.plan,self.projection=session,plan,projection
        self.reference,self.catalog=reference,catalog
        self.stop=session.client.stop_check
        self.matrix=np.eye(3)
        self.last_frame=None
        self.battle_gate=BattleFrameGate(session.attack_nav.battlefield_ready,
            lambda frame, **evidence: active_battle_ready(frame,stop_check=self.stop,**evidence))
        self.result=ExecutionResult(False,'not started')
        self.deployed_heroes=set();self.abilities=set();self.skipped_abilities=set()
        self.path=Path(journal_dir or session.config.data_dir/'debug'/'attack-executions')/(uuid.uuid4().hex+'.jsonl')
        self.path.parent.mkdir(parents=True,exist_ok=True)

    def note(self, event, **fields):
        # Write intent before sending input. Interrupted runs cannot be resumed.
        with self.path.open('a',encoding='utf-8') as handle:
            handle.write(json.dumps({'at':time.time(),'event':event,**fields})+'\n')
            handle.flush()
            if event in ('map_tap_intent','map_batch_intent','ability_intent','finished'):
                os.fsync(handle.fileno())
        if event=='step':
            logger.info('Attack step {}/{}: {} {}',fields['number']+1,len(self.plan.steps),
                        fields['action'].replace('_',' '),fields.get('unit_id','').replace('_',' '))
        elif event=='deployment_verified':
            logger.info('Deployment confirmed: {} (remaining {})',fields['unit_id'],fields['quantity_after'])
        elif event=='waiting_for_battle_controls':
            logger.info('Attack paused — waiting for clear battle controls')
        elif event=='battle_controls_restored':
            logger.info('Battle controls restored — checking camera before continuing')
        elif event=='finished':
            logger.info('Attack executor: {} ({} verified deployments)',fields['reason'],fields['verified_taps'])
        elif event=='ability_skipped':
            logger.info('Hero ability skipped: {} — no usable health bar; continuing remaining steps',fields['unit_id'])

    def frame(self):
        check_stop(self.stop)
        frame=self.session.capture.screenshot()
        self.last_frame=frame
        ready=frame.shape==self.reference.shape and self.battle_gate.accept(frame)
        if not ready:
            # Timed event rewards can cover a still-running battle. Never tap
            # through them. Resume only after fresh battle controls reappear.
            self.note('waiting_for_battle_controls')
            deadline=time.monotonic()+20
            for _ in range(10):
                check_stop(self.stop)
                if time.monotonic()>=deadline: break
                self.session._sleep(min(1.,deadline-time.monotonic()))
                check_stop(self.stop)
                frame=self.session.capture.screenshot()
                self.last_frame=frame
                ready=frame.shape==self.reference.shape and self.battle_gate.accept(frame)
                if ready:
                    self.note('battle_controls_restored')
                    break
        if not ready:
            cv2.imwrite(str(self.path.with_suffix('.blocked.png')),frame)
            raise ValueError('Battle controls changed; deployment paused')
        self.matrix=affine(compare_camera(self.reference,frame))
        scale=np.hypot(self.matrix[0,0],self.matrix[1,0])
        if abs(scale-1)>.01: raise ValueError('Battle zoom changed; map must be rebuilt')
        return frame

    def resolve(self, frame, unit_id):
        return resolve_live_card(frame,self.catalog,unit_id,stop_check=self.stop)

    def find(self, frame, unit_id):
        """Search only inside the army bar, with bounded overlap and fresh slots."""
        for direction in (0,-1,-1,1,1,1,1):
            check_stop(self.stop)
            if direction:
                h,w=frame.shape[:2]
                a,b=(.75,.30) if direction<0 else (.30,.75)
                self.session.input.swipe(round(w*a),round(h*.91),round(w*b),round(h*.91),350)
                self.session._sleep(.15);frame=self.frame()
            try:return frame,self.resolve(frame,unit_id)
            except ValueError as exc:
                if 'hidden or ambiguous' not in str(exc): raise
        raise ValueError('Unit not found after a bounded army-bar search: '+unit_id)

    def target(self, point):
        x,y=self.projection.pixel(point)
        p=self.matrix@np.array([x,y,1.])
        return p[:2]/p[2]

    def position(self, point):
        """Re-measure every pan; there are no remembered swipe counts."""
        for attempt in range(5):
            frame=self.frame();h,w=frame.shape[:2]
            x,y=self.target(point)
            if input_area(x,y,w,h): return frame,(round(x),round(y))
            dx=float(np.clip(w*.48-x,-w*.22,w*.22))
            dy=float(np.clip(h*.46-y,-h*.20,h*.20))
            self.note('pan',dx=dx,dy=dy)
            self.session.input.swipe(round(w*.48),round(h*.46),round(w*.48+dx),round(h*.46+dy),350)
            self.session._sleep(.2)
        raise ValueError('Deployment point could not be brought clear of the controls')

    def select(self, frame, unit_id):
        frame,card=self.find(frame,unit_id)
        # Cards rise/reflow after selection and deployment. Observe twice before
        # deciding the click missed, then permit one fresh, identified CARD tap.
        # Map taps and already-deployed hero abilities must never be retried here.
        for attempt in range(2):
            check_stop(self.stop)
            if card.quantity is None or card.quantity<=0:
                raise ValueError('Unit count or availability is unverified: '+unit_id)
            if selected_card(frame,card):return frame,card
            if card.kind in ('hero','siege') and hero_health_visible(frame,card):
                raise ValueError('Unit is already deployed: '+unit_id)
            x,y,w,h=card.box
            self.note('selection_intent',unit_id=unit_id,attempt=attempt+1,box=list(card.box))
            self.session.input.tap(x+w//2,y+h//2,jitter=0)
            for observation in range(2):
                self.session._sleep(.2)
                frame=self.frame()
                try:card=self.resolve(frame,unit_id)
                except ValueError:
                    if observation==0:continue
                    raise
                confirmed=bool(selected_card(frame,card))
                self.note('selection_observation',unit_id=unit_id,confirmed=confirmed,box=list(card.box))
                if card.quantity is None or card.quantity<=0:
                    raise ValueError('Unit count or availability is unverified: '+unit_id)
                if confirmed:return frame,card
        cv2.imwrite(str(self.path.with_suffix('.selection.png')),frame)
        raise ValueError('Unit selection was not confirmed: '+unit_id)

    def deploy(self, unit_id, point):
        frame,target=self.position(point)
        frame,card=self.select(frame,unit_id)
        # Selection cannot grant permission to use stale coordinates.
        h,w=frame.shape[:2];target=tuple(round(n) for n in self.target(point))
        if not input_area(*target,w,h): raise ValueError('Target moved under game controls')
        before=card.quantity
        if card.kind in ('hero','siege') and hero_health_visible(frame,card):
            raise ValueError('Unit is already deployed: '+unit_id)
        self.note('map_tap_intent',unit_id=unit_id,quantity_before=before,target=target)
        check_stop(self.stop)
        sent_at=time.time()
        from coc_bot.attack.recovery import AttackCheckpoint
        checkpoint=AttackCheckpoint(self.session.config)
        if checkpoint.load() is None:
            checkpoint.begin('deploying')
        checkpoint.update('deploying',deployment_possible=True,first_attempt_at=
                          checkpoint.load().get('first_attempt_at',sent_at),journal=self.path.name)
        self.result.first_attempt_at=self.result.first_attempt_at or sent_at
        self.result.uncertain_tap=True
        cv2.imwrite(str(self.path.with_suffix('.before.png')),frame)
        self.session.input.tap(*target,jitter=0)
        # No retry of a map tap, including when capture/OCR fails after it.
        for attempt in range(2):
            self.session._sleep(.2)
            after_frame=self.frame()
            cv2.imwrite(str(self.path.with_suffix('.after.png')),after_frame)
            try:
                after=self.resolve(after_frame,unit_id)
            except ValueError:
                try:
                    after=resolve_just_depleted(after_frame,self.catalog,card,stop_check=self.stop)
                except ValueError:
                    # A rising card can be between layouts during deployment.
                    # Retry observation only; never send another map tap.
                    if attempt==0: continue
                    raise
            self.note('deployment_observation',unit_id=unit_id,quantity=after.quantity)
            good=(after.quantity==before-1 if card.kind not in ('hero','siege') else
                  hero_health_visible(after_frame,after) or card.kind=='siege' and after.quantity==0)
            if good:
                self.result.uncertain_tap=False
                self.result.verified_taps+=1
                self.result.first_deploy_at=self.result.first_deploy_at or sent_at
                if card.kind=='hero': self.deployed_heroes.add(unit_id)
                self.note('deployment_verified',unit_id=unit_id,quantity_after=after.quantity)
                return
        raise ValueError('No verified deployment change for '+unit_id+'; remaining taps stopped')

    def ability(self, unit_id):
        if unit_id not in self.deployed_heroes or unit_id in self.abilities or unit_id in self.skipped_abilities:
            raise ValueError('Hero ability has no verified deployment')
        frame,card=self.find(self.frame(),unit_id)
        if not hero_health_visible(frame,card,allow_low=True):
            # Already deployed and freshly identified, but dead/auto-triggered
            # or too uncertain to tap. Other heroes can still have abilities.
            self.skipped_abilities.add(unit_id)
            self.note('ability_skipped',unit_id=unit_id)
            return
        x,y,w,h=card.box
        self.note('ability_intent',unit_id=unit_id)
        self.session.input.tap(x+w//2,y+h//2,jitter=0)
        self.abilities.add(unit_id)
        self.note('ability_sent',unit_id=unit_id)

    def deploy_batch(self, unit_id, points):
        """A fresh troop selection, <=5 clear targets, one exact count delta."""
        if unit_id not in ('barbarian','archer','giant','wall_breaker','wizard'):
            raise ValueError('Only supported ground troops can use deployment batches')
        if not 1<=len(points)<=5:raise ValueError('Invalid ground deployment batch')
        if len(points)==1:return self.deploy(unit_id,points[0])
        check_stop(self.stop)
        frame,_=self.position(points[0]);frame,card=self.select(frame,unit_id)
        if card.kind!='troop' or card.quantity is None or card.quantity<len(points):
            raise ValueError('Ground batch troop availability is unverified')
        h,w=frame.shape[:2]
        targets=[tuple(round(v) for v in self.target(point)) for point in points]
        if not all(input_area(*target,w,h) for target in targets):
            # Nothing has been sent. Reposition and verify individual targets
            # when this camera cannot safely show a whole batch.
            for point in points:self.deploy(unit_id,point)
            return
        self.note('map_batch_intent',unit_id=unit_id,quantity_before=card.quantity,targets=targets)
        check_stop(self.stop);sent_at=time.time()
        from coc_bot.attack.recovery import AttackCheckpoint
        checkpoint=AttackCheckpoint(self.session.config)
        if checkpoint.load() is None:checkpoint.begin('deploying')
        checkpoint.update('deploying',deployment_possible=True,first_attempt_at=
                          checkpoint.load().get('first_attempt_at',sent_at),journal=self.path.name)
        self.result.first_attempt_at=self.result.first_attempt_at or sent_at
        self.result.uncertain_tap=True
        cv2.imwrite(str(self.path.with_suffix('.before.png')),frame)
        self.session.input.tap_many(targets)
        for attempt in range(2):
            self.session._sleep(.2);after_frame=self.frame()
            cv2.imwrite(str(self.path.with_suffix('.after.png')),after_frame)
            try:
                after=self.resolve(after_frame,unit_id)
            except ValueError:
                try:after=resolve_just_depleted(after_frame,self.catalog,card,stop_check=self.stop,spent=len(points))
                except ValueError:
                    if attempt==0:continue
                    raise
            self.note('deployment_batch_observation',unit_id=unit_id,quantity=after.quantity)
            if after.quantity==card.quantity-len(points):
                self.result.uncertain_tap=False;self.result.verified_taps+=len(points)
                self.result.first_deploy_at=self.result.first_deploy_at or sent_at
                self.note('deployment_verified',unit_id=unit_id,quantity_after=after.quantity,batch_size=len(points))
                return
        raise ValueError('Ground batch count change was not confirmed; no taps will be replayed')

    def run(self):
        self.note('started',plan=self.plan.to_dict())
        try:
            frame=self.frame()
            # Re-read every used unit before the first map tap. An unavailable or
            # hidden hero blocks here, not halfway through a dragon deployment.
            for entry in self.plan.army:
                if any(step.unit_id==entry.unit_id for step in self.plan.steps):
                    frame,card=self.find(frame,entry.unit_id)
                    if card.kind!=entry.kind or card.quantity is None or card.quantity<entry.quantity:
                        raise ValueError('Live army differs from the reviewed plan: '+entry.unit_id)
                    if card.kind in ('hero','siege') and hero_health_visible(frame,card):
                        raise ValueError('Unit is already deployed: '+entry.unit_id)
            for number,step in enumerate(self.plan.steps):
                check_stop(self.stop);self.note('step',number=number,action=step.action,unit_id=step.unit_id)
                if step.action=='wait': self.session._sleep(step.seconds)
                elif step.action=='ability': self.ability(step.unit_id)
                else:
                    points=step_points(step)
                    if (getattr(self.session.config,'progression_enabled',False) is True and
                            self.plan.strategy=='farming_ground' and step.action=='deploy_line'):
                        for start in range(0,len(points),5):self.deploy_batch(step.unit_id,points[start:start+5])
                    else:
                        for point in points:self.deploy(step.unit_id,point)
            self.result.success,self.result.reason=True,'All planned deployments verified'
            if self.skipped_abilities:
                self.result.reason+='; unavailable abilities skipped: '+', '.join(sorted(self.skipped_abilities))
        except ValueError as exc:
            self.result.reason=str(exc)
            if self.last_frame is not None:
                cv2.imwrite(str(self.path.with_suffix('.failed.png')),self.last_frame)
        except AdbStopped:
            self.result.reason='Stopped'
            raise
        except Exception as exc:
            self.result.reason=f'{type(exc).__name__}: {exc}'
            raise
        finally:
            self.note('finished',**vars(self.result))
        return self.result
