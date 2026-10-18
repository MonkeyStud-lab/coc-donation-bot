"""Measured battlefield coordinates. No screen percentage is a deployment zone.

The inner square [.1,.9]^2 is the observed village perimeter; its surrounding
band is the deployment area. Corners are top, right, bottom, left in the image.
"""
from dataclasses import asdict, dataclass
import math
import cv2
import numpy as np

from coc_bot.attack.plans import MapPoint


@dataclass(frozen=True)
class Projection:
    corners: tuple
    source: str = 'measured'
    reviewed: bool = False

    def validate(self):
        p = np.asarray(self.corners, dtype=float)
        if p.shape != (4, 2) or not np.isfinite(p).all() or np.abs(p).max()>100_000:
            raise ValueError('Mark four village corners: top, right, bottom, left')
        a, b, c, d = p
        sides=np.linalg.norm(np.roll(p,-1,axis=0)-p,axis=1)
        if (np.linalg.norm(a+c-b-d) > np.linalg.norm(c-a)*.08 or
                sides.min()<sides.max()*.90 or
                abs(a[0]-c[0])>np.linalg.norm(b-d)*.06 or
                abs(b[1]-d[1])>np.linalg.norm(c-a)*.06 or
                not cv2.isContourConvex(p.astype(np.float32)) or
                abs(cv2.contourArea(p.astype(np.float32))) < 1000 or
                not a[1] < b[1] < c[1] or not a[1] < d[1] < c[1] or
                not d[0] < a[0] < b[0] or not d[0] < c[0] < b[0]):
            raise ValueError('Village corners must form a complete, ordered diamond')
        return self

    def matrix(self):
        self.validate()
        return cv2.getPerspectiveTransform(np.float32([[.1,.1],[.9,.1],[.9,.9],[.1,.9]]),
                                           np.float32(self.corners))

    def pixel(self, point):
        p = cv2.perspectiveTransform(np.float32([[[point.x, point.y]]]), self.matrix())[0,0]
        return float(p[0]), float(p[1])

    def world(self, x, y):
        p = cv2.perspectiveTransform(np.float32([[[x,y]]]), np.linalg.inv(self.matrix()))[0,0]
        return MapPoint(float(p[0]), float(p[1]))

    def to_dict(self):
        self.validate()
        return asdict(self)


def deployable(point):
    """Stay inside the surveyed outer ring and clearly outside the red boundary."""
    x,y = point.x,point.y
    return (all(math.isfinite(v) for v in (x,y)) and .025 <= x <= .975 and .025 <= y <= .975
            and (x <= .075 or x >= .925 or y <= .075 or y >= .925))


def map_target_allowed(point, kind):
    return deployable(point) if kind != 'spell' else .1 <= point.x <= .9 and .1 <= point.y <= .9


def input_area(x, y, width, height):
    # All targets and camera drags avoid battle controls, loot labels and the bar.
    u,v=x/width,y/height
    return (.15<u<.82 and .12<v<.80 and not (u<.28 and v<.29)
            and not (u>.76 and v<.23) and not (u<.48 and v>.70))


def fit_projection(segments, width, height):
    """Fit four independently observed sides; never fill in a missing side.

    Segments may be registered from multiple views into the reference image.
    Each side needs measured support, with stronger support across the whole
    outline. Broken, stepped boundaries need not supply one long straight edge.
    The caller additionally checks repeat-frame camera stability.
    """
    families = {-1: [], 1: []}
    for segment in segments:
        a,b = np.asarray(segment['points'],float)*[width,height]
        if b[0] < a[0]: a,b = b,a
        dx,dy = b-a
        if dx <= 0 or not .40 <= abs(dy/dx) <= 1.05: continue
        families[1 if dy > 0 else -1].append((a,b))
    lines = []
    supports = []
    for sign in (1,-1):
        family = families[sign]
        if len(family) < 2: return None
        slope = float(np.median([(b[1]-a[1])/(b[0]-a[0]) for a,b in family]))
        offsets = np.array([(a[1]+b[1]-slope*(a[0]+b[0]))/2 for a,b in family])
        if np.ptp(offsets) < height*.18: return None
        for extreme in (min(offsets), max(offsets)):
            members = [pair for pair,offset in zip(family,offsets) if abs(offset-extreme)<height*.012]
            pts = np.concatenate(members)
            # Median offset resists isolated fragments. Length coverage is checked below.
            offset = float(np.median(pts[:,1]-slope*pts[:,0]))
            lines.append((slope,offset))
            supports.append(members)
    def cross(i,j):
        m,b=lines[i];n,c=lines[j]
        x=(c-b)/(m-n)
        return (x,m*x+b)
    points=[cross(0,2),cross(0,3),cross(1,3),cross(1,2)]
    points=sorted(points,key=lambda p:p[1])
    top,bottom=points[0],points[-1]
    left,right=sorted(points[1:3],key=lambda p:p[0])
    projection=Projection(tuple(map(tuple,(top,right,bottom,left))))
    try: projection.validate()
    except ValueError: return None
    if not .35 < (right[0]-left[0])/width < 2.5 or not .35 < (bottom[1]-top[1])/height < 2.5:
        return None
    # Union of measured intervals rather than summed overlapping Hough detections.
    coverage=[]
    for (slope,offset),members in zip(lines,supports):
        corners=[p for p in projection.corners if abs(p[1]-slope*p[0]-offset)<height*.02]
        if len(corners)!=2: return None
        length=abs(corners[1][0]-corners[0][0])
        intervals=sorted((a[0],b[0]) for a,b in members)
        merged=[]
        for start,end in intervals:
            if merged and start <= merged[-1][1]: merged[-1][1]=max(end,merged[-1][1])
            else: merged.append([start,end])
        fraction=sum(b-a for a,b in merged)/length
        if fraction < .10: return None
        coverage.append(fraction)
    if np.mean(coverage)<.30: return None
    # One side can be mostly hidden behind the army bar or buildings. A short
    # measured side is usable only when the other three are well supported;
    # missing sides and two weak sides remain blocked.
    if min(coverage)<.15 and (sum(c<.15 for c in coverage)>1 or
                            sum(coverage)-min(coverage)<1.5):
        return None
    return projection


def step_points(step):
    if step.action=='deploy_line':
        a,b=step.points
        return [MapPoint(a.x+(b.x-a.x)*t,a.y+(b.y-a.y)*t)
                for t in np.linspace(0,1,step.quantity)]
    if step.action=='deploy_point': return list(step.points)*step.quantity
    return list(step.points)


def validate_geometry(plan, projection):
    projection.validate();plan.validate()
    kinds={unit.unit_id:unit.kind for unit in plan.army}
    for step in plan.steps:
        for point in step_points(step):
            if not map_target_allowed(point,kinds[step.unit_id]):
                raise ValueError('Troops must be outside the red perimeter; spells must be inside the village')
