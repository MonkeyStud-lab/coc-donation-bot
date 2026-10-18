"""Bounded opponent survey, registering every view before combining evidence."""
import time
import uuid
import json
import cv2
import numpy as np

from coc_bot.attack.army import check_stop
from coc_bot.attack.camera import compare_camera
from coc_bot.attack.mapping import observe_boundary
from coc_bot.attack.projection import fit_projection
from coc_bot.attack.battle_gate import BattleFrameGate
from loguru import logger


def reveal_boundary(session, frame):
    """Confirm the outline before toggling a card; retry only card selection."""
    from coc_bot.attack.army import card_boxes
    stop=session.client.stop_check
    check_stop(stop)
    current=session.capture.screenshot()
    observation=observe_boundary(current,frame,battle_confirmed=True,stop_check=stop)
    if observation.stable and len(observation.segments)>=2:
        logger.debug('Survey: deployment outline already visible; keeping selection')
        return current
    for attempt in range(2):
        check_stop(stop)
        boxes=card_boxes(current,'battle')
        if not boxes:raise ValueError('No visible army card to reveal the boundary')
        x,y,bw,bh=boxes[0]
        session.input.tap(x+bw//2,y+bh//2,jitter=0)
        for _ in range(2):
            session._sleep(.2)
            previous=current;current=session.capture.screenshot()
            observation=observe_boundary(current,previous,battle_confirmed=True,stop_check=stop)
            if observation.stable and len(observation.segments)>=2:
                logger.debug('Survey: deployment outline confirmed after card selection {}',attempt+1)
                return current
    logger.debug('Survey: outline not confirmed after two card selections; continuing bounded observation')
    return current


def survey_pan(evidence, transform, width, height):
    """Bring an unobserved candidate-side gap into view, never into deployment."""
    for side in evidence.get('weak_sides',[]):
        point=cv2.perspectiveTransform(np.float32([[side['target']]]),transform)[0,0]
        delta=np.array([width*.50,height*.45])-point
        delta=np.clip(delta,[-width*.22,-height*.20],[width*.22,height*.20])
        if np.linalg.norm(delta)>=50:return delta/np.array([width,height])
    return None


def affine(evidence):
    if not evidence.get('verified'):
        raise ValueError('Camera movement could not be measured; survey stopped')
    return np.vstack([np.array(evidence['transform']),[0,0,1]])


def registered_segments(observation, to_reference, width, height):
    result=[]
    for segment in observation.segments:
        points=np.asarray(segment['points'])*[width,height]
        points=cv2.perspectiveTransform(np.float32([points]),to_reference)[0]
        result.append(segment|{'points':(points/[width,height]).tolist()})
    return result


def survey(session, *, zoom=True, full_map=False):
    """Caller owns the lease. Select no map points; at most twelve camera pans.

    The gesture can retain zoom in the game. The legacy engine is never resumed
    automatically by this tool. Every frame and transform is returned as evidence.
    """
    stop=session.client.stop_check
    battle_gate=BattleFrameGate(session.attack_nav.battlefield_ready)
    frame=session.capture.screenshot()
    if not battle_gate.accept(frame):
        raise ValueError('Find an opponent before mapping its village')
    h,w=frame.shape[:2]
    if session.client.wm_size()!=(w,h):
        raise ValueError('Input and screenshot sizes differ')
    before=frame.copy()
    if zoom:
        from coc_bot.adb.multitouch import Multitouch
        with Multitouch(session.client,(w,h)) as touch:
            for _ in range(3):
                check_stop(stop)
                touch.pinch()
                session._sleep(.5)
                frame=session.capture.screenshot()
                measured=compare_camera(before,frame)
                affine(measured)
                # Keep a measured recovery hint: home retains the battle zoom.
                # It can guide one correction, but never certify restoration.
                pending=session.config.data_dir/'attack-planner'/'camera-pending.json'
                if pending.is_file():
                    state=json.loads(pending.read_text(encoding='utf-8'))
                    state['measured_scale']=state.get('measured_scale',1.)*measured['scale']
                    temporary=pending.with_suffix('.tmp')
                    temporary.write_text(json.dumps(state),encoding='utf-8');temporary.replace(pending)
                if abs(measured['scale']-1)<.01: break
                before=frame
    # The game can retain an active selection. Don't toggle a visible outline
    # off, and don't assume one click took effect while the card was moving.
    reference=reveal_boundary(session,frame)
    evidence_dir=session.config.data_dir/'debug'/'attack-surveys'/uuid.uuid4().hex
    evidence_dir.mkdir(parents=True,exist_ok=True)
    cv2.imwrite(str(evidence_dir/'reference.png'),reference)
    transform=np.eye(3);segments=[];views=[];projection=None
    # Move the village up/down, then across, returning through overlapping views.
    gestures=[(0,-.20),(0,.20),(0,.20),(0,-.20),(.16,0),(-.16,0),(-.16,0),(.16,0),
              # A tall village can keep its top edge under the timer after one
              # short pan. Extend only when the first pass has no complete fit;
              # keep overlap and measure every move instead of guessing a side.
              (0,.20),(0,.20),(0,-.20),(0,-.20)]
    for index in range(len(gestures)+1):
        check_stop(stop)
        previous=session.capture.screenshot();session._sleep(.15)
        current=session.capture.screenshot()
        if not battle_gate.accept(current):
            session._sleep(.2)
            previous=current;current=session.capture.screenshot()
            if not battle_gate.accept(current):
                raise ValueError('Battle controls disappeared during mapping')
        for settle in range(4):
            stationary=compare_camera(previous,current)
            motion=affine(stationary)
            if abs(stationary['scale']-1)<=.003 and np.linalg.norm(motion[:2,2])<=3:
                break
            if settle==3:
                raise ValueError('Wait for the camera to settle before mapping')
            session._sleep(.35)
            previous=current;current=session.capture.screenshot()
            if not battle_gate.accept(current):
                raise ValueError('Battle controls disappeared while settling')
        registration=compare_camera(reference,current)
        if registration.get('verified'):
            transform=affine(registration)
        elif views:
            # Overlapping small pans keep a measured path to the reference even
            # when opposite edges no longer share enough visible buildings.
            delta=affine(compare_camera(views[-1]['frame'],current))
            if abs(np.hypot(delta[0,0],delta[1,0])-1)>.005:
                raise ValueError('Zoom changed during the camera survey')
            transform=delta@np.asarray(views[-1]['transform'])
        else:
            transform=affine(registration)
        observation=observe_boundary(current,previous,battle_confirmed=True,stop_check=stop)
        cv2.imwrite(str(evidence_dir/f'view-{index}.png'),current)
        (evidence_dir/f'view-{index}.json').write_text(json.dumps({'transform':transform.tolist(),
                                      'observation':observation.to_dict()}),encoding='utf-8')
        if observation.stable:
            segments.extend(registered_segments(observation,np.linalg.inv(transform),w,h))
        views.append({'frame':current,'transform':transform.tolist(),'segments':len(observation.segments)})
        evidence={}
        projection=fit_projection(segments,w,h,survey_evidence=evidence)
        if (projection and (not full_map or index>=7)) or index==len(gestures): break
        dx,dy=gestures[index]
        if index>=8 and projection is None:
            targeted=survey_pan(evidence,transform,w,h)
            if targeted is not None:
                dx,dy=targeted
                logger.debug('Survey: panning to gather missing boundary evidence')
        check_stop(stop)
        session.input.swipe(round(w*.48),round(h*.46),round(w*(.48+dx)),round(h*(.46+dy)),350)
        session._sleep(.3)
        frame=current
    # A mosaic allows reviewing corners outside the original view. Never use HUD
    # pixels in the mosaic; the original reference remains the coordinate anchor.
    canvas=np.zeros((h*2,w*2,3),np.uint8);offset=np.array([[1,0,w*.5],[0,1,h*.5],[0,0,1.]])
    for view in views:
        source=view['frame'];mask=np.zeros((h,w),np.uint8)
        mask[round(h*.10):round(h*.80),round(w*.15):round(w*.83)]=255
        mask[:round(h*.29),:round(w*.28)]=0
        mask[:round(h*.23),round(w*.76):]=0
        mask[round(h*.70):,:round(w*.50)]=0  # End Battle and army boost chips.
        matrix=offset@np.linalg.inv(np.array(view['transform']))
        image=cv2.warpPerspective(source,matrix,(w*2,h*2))
        valid=cv2.warpPerspective(mask,matrix,(w*2,h*2))>0
        canvas[valid]=image[valid]
    bounds=cv2.boundingRect(cv2.cvtColor(canvas,cv2.COLOR_BGR2GRAY))
    return {'reference':reference,'previous':previous,'current':views[-1]['frame'],'mosaic':canvas,
            'projection':projection,'segments':segments,'views':len(views),
            'captured_at':time.time(),'mosaic_offset':[w*.5,h*.5],'mosaic_bounds':bounds}
