"""Scenery-independent observations of the visible red no-deploy boundary.

No grass/color heuristic or inferred hidden corner authorizes a deployment.
"""
from dataclasses import asdict, dataclass
import hashlib
import math
import time

import cv2
import numpy as np

from coc_bot.attack.army import check_stop
from coc_bot.attack.camera import compare_camera


def boundary_mask(frame):
    h,w = frame.shape[:2]
    hsv = cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
    # The thin red outline is blended with the ground: green scenery can shift
    # its observed hue toward orange. Keep the shape/temporal tests as well.
    red = ((hsv[:,:,0]<=18)|(hsv[:,:,0]>=174))&(hsv[:,:,1]>=110)&(hsv[:,:,2]>=65)&(hsv[:,:,2]<=230)
    b,g,r=cv2.split(frame.astype(np.float32))
    # Gold wall trim is also thin, diagonal, and orange in HSV. Require red
    # dominance, not just hue, before considering any of those pixels.
    red &= (r>g*1.7)&(r>b*1.7)
    mask = red.astype(np.uint8)*255
    # Exclude all fixed combat controls. This intentionally leaves hidden
    # perimeter unobserved rather than completing a diamond through the HUD.
    allowed = np.zeros((h,w),np.uint8)
    allowed[round(h*.10):round(h*.80),round(w*.15):round(w*.83)] = 255
    allowed[:round(h*.29),:round(w*.28)] = 0
    allowed[:round(h*.23),round(w*.76):] = 0
    mask = cv2.bitwise_and(mask,allowed)
    thick=(cv2.distanceTransform(mask,cv2.DIST_L2,3)>2).astype(np.uint8)*255
    return cv2.subtract(mask,cv2.dilate(thick,np.ones((7,7),np.uint8)))


@dataclass
class OpponentMap:
    width: int
    height: int
    captured_at: float
    frame_digest: str
    segments: list
    stable: bool
    coverage: str = 'partial'
    deployment_ready: bool = False
    reason: str = 'Visible boundary candidates only; hidden corners and legal deployment zones are unverified'

    def to_dict(self):
        return asdict(self)


def observe_boundary(frame, previous=None, *, battle_confirmed=False, stop_check=None):
    check_stop(stop_check)
    h,w = frame.shape[:2]
    result = OpponentMap(w,h,time.time(),hashlib.sha256(frame.tobytes()).hexdigest(),[],False)
    if battle_confirmed is not True:
        result.coverage,result.reason = 'none','Battlefield not positively confirmed'
        return result
    mask = boundary_mask(frame)
    lines = cv2.HoughLinesP(mask,1,np.pi/360,threshold=max(20,round(w*.018)),
                            minLineLength=round(w*.04),maxLineGap=round(w*.007))
    if lines is None:
        result.coverage,result.reason = 'none','Select a troop to show the red no-deploy outline; no supported boundary lines found'
        return result
    segments = []
    # Hough endpoints and raster sampling round differently on a one-pixel
    # diagonal. Permit one pixel of distance, without broadening the color mask
    # used to find candidates or allowing unsupported gaps.
    supported=cv2.dilate(mask,np.ones((3,3),np.uint8))
    for x1,y1,x2,y2 in lines.reshape(-1,4):
        check_stop(stop_check)
        if x2 < x1:
            x1,x2,y1,y2=x2,x1,y2,y1
        dx,dy = int(x2-x1),int(y2-y1)
        if not dx or not .40 <= abs(dy/dx) <= 1.05:
            continue
        n = max(2,round(math.hypot(dx,dy)))
        xs = np.rint(np.linspace(x1,x2,n)).astype(int)
        ys = np.rint(np.linspace(y1,y2,n)).astype(int)
        support = float((supported[ys,xs]>0).mean())
        if support < .55:
            continue
        normalized = [[round(float(x1)/w,6),round(float(y1)/h,6)],
                      [round(float(x2)/w,6),round(float(y2)/h,6)]]
        if not any(max(abs(np.array(normalized).ravel()-np.array(s['points']).ravel()))<.008 for s in segments):
            segments.append({'points':normalized,'support':round(support,3)})
    # Interior walls have the same diagonal directions. Keep only the outside
    # envelope of the observed red candidates, never an inferred hidden edge.
    outside=[]
    for sign in (-1,1):
        family=[s for s in segments if np.sign(s['points'][1][1]-s['points'][0][1])==sign]
        if not family:
            continue
        slopes=[(s['points'][1][1]-s['points'][0][1])*h/
                ((s['points'][1][0]-s['points'][0][0])*w) for s in family]
        slope=float(np.median(slopes))
        offsets=[np.mean(np.array(s['points'])*[w,h],axis=0) for s in family]
        offsets=[float(p[1]-slope*p[0]) for p in offsets]
        low,high=min(offsets),max(offsets)
        outside.extend(s for s,offset in zip(family,offsets) if min(offset-low,high-offset)<h*.035)
    result.segments = outside[:60]
    positive = sum(s['points'][1][1]>s['points'][0][1] for s in result.segments)
    if len(result.segments)<4 or positive<2 or len(result.segments)-positive<2:
        result.coverage,result.reason = 'none','Not enough supported edges in both map directions'
        # A single view may only expose one side. Temporal verification still
        # applies to those fragments so a registered multi-view survey can use
        # them without declaring this individual view a complete map.
    if previous is not None and previous.shape == frame.shape:
        motion = compare_camera(previous,frame)
        if motion['verified'] and abs(motion['scale']-1)<.003:
            transform = np.array(motion['transform'])
            stationary = abs(transform[0,2])<2 and abs(transform[1,2])<2
            old = cv2.dilate(boundary_mask(previous),np.ones((5,5),np.uint8))
            hits = []
            for segment in result.segments:
                a,b = np.array(segment['points'])*np.array([w,h])
                points = np.rint(np.linspace(a,b,80)).astype(int)
                hits.extend((old[points[:,1],points[:,0]]>0).tolist())
            result.stable = bool(stationary and hits and np.mean(hits)>.80)
    if not result.stable:
        result.reason = 'Boundary fragments found, but repeated frames do not confirm a stationary camera'
    return result


def map_is_current(observation, reference, frame, *, now=None, max_age=30):
    """Invalidate screen geometry after movement, expiry or display resize."""
    if (frame.shape[1],frame.shape[0]) != (observation.width,observation.height):
        return False
    if hashlib.sha256(reference.tobytes()).hexdigest() != observation.frame_digest:
        return False
    age = (time.time() if now is None else now)-observation.captured_at
    if not 0 <= age <= max_age or not observation.stable:
        return False
    evidence = compare_camera(reference,frame)
    if not evidence['verified'] or abs(evidence['scale']-1)>.003:
        return False
    transform = np.array(evidence['transform'])
    return bool(abs(transform[0,2])<2 and abs(transform[1,2])<2)


def draw_observation(frame, observation, cards=()):
    image = frame.copy()
    h,w = frame.shape[:2]
    for segment in observation.segments if observation else []:
        a,b = np.rint(np.array(segment['points'])*[w,h]).astype(int)
        cv2.line(image,tuple(a),tuple(b),(0,220,220),2)
    for card in cards:
        x,y,bw,bh = card.box
        cv2.rectangle(image,(x,y),(x+bw,y+bh),(0,220,120) if card.stable else (0,150,255),2)
        label = card.slot.removeprefix('card-')
        cv2.circle(image,(x+16,y+18),14,(30,30,30),-1)
        cv2.putText(image,str(int(label)+1),(x+9,y+24),cv2.FONT_HERSHEY_SIMPLEX,.5,(255,255,255),1)
    return image
