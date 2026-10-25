"""Conservative deployment envelope for fully visible, sparse starter villages.

The red outline follows individual footprints, so it need not form one diamond.
Enclose all observed outline pixels instead of fitting a large village perimeter.
This never turns a missing or moving outline into deployment permission.
"""
import cv2
import numpy as np
from coc_bot.attack.camera import compare_camera
from coc_bot.attack.mapping import boundary_mask
from coc_bot.attack.projection import Projection, input_area


def compact_projection(previous, frame):
    if previous.shape!=frame.shape:return None
    evidence=compare_camera(previous,frame)
    if not evidence.get('verified') or abs(evidence['scale']-1)>.003:return None
    matrix=np.asarray(evidence['transform'])
    if np.linalg.norm(matrix[:,2])>2:return None
    h,w=frame.shape[:2]
    mask=boundary_mask(frame)
    old=cv2.dilate(boundary_mask(previous),np.ones((3,3),np.uint8))
    # Keep thin outline components with actual spatial extent; isolated red
    # artwork/particles cannot establish the extent of a starter village.
    count,labels,stats,_=cv2.connectedComponentsWithStats(mask)
    clean=np.zeros_like(mask)
    for i in range(1,count):
        x,y,bw,bh,area=stats[i]
        if area>=30 and bw>=25 and bh>=20 and area/(bw*bh)<.20:
            clean[labels==i]=255
    yy,xx=np.nonzero(clean)
    if len(xx)<300 or (old[yy,xx]>0).mean()<.95:return None
    # Every observed component must sit clear of the crop/HUD limits. No
    # off-screen fragment can be completed by this compact path.
    if (xx.min()<w*.15+8 or xx.max()>w*.83-8 or
            yy.min()<h*.10+8 or yy.max()>h*.80-8):return None
    edges=cv2.HoughLinesP(clean,1,np.pi/360,25,minLineLength=round(w*.02),maxLineGap=4)
    if edges is None:return None
    slopes=[];positive=negative=0
    for x1,y1,x2,y2 in edges.reshape(-1,4):
        if x1==x2:continue
        slope=(y2-y1)/(x2-x1)
        if not .60<abs(slope)<.90:continue
        slopes.append(abs(slope));positive+=slope>0;negative+=slope<0
    if positive<3 or negative<3:return None
    slope=float(np.median(slopes))
    u=xx+yy/slope;v=-xx+yy/slope
    # Equalize outward, never inward, so the envelope contains every observed
    # forbidden footprint even when the village is stepped or asymmetric.
    cu,cv=(u.min()+u.max())/2,(v.min()+v.max())/2
    radius=max(np.ptp(u),np.ptp(v))/2+8
    def pixel(a,b):return ((a-b)/2,slope*(a+b)/2)
    corners=tuple(pixel(a,b) for a,b in ((cu-radius,cv-radius),(cu+radius,cv-radius),
                                       (cu+radius,cv+radius),(cu-radius,cv+radius)))
    projection=Projection(corners,source='observed_starter_envelope')
    try:projection.validate()
    except ValueError:return None
    width=corners[1][0]-corners[3][0];height=corners[2][1]-corners[0][1]
    if not w*.15<width<w*.90 or not h*.20<height<h*.95:return None
    return projection if deployment_line(projection,w,h) is not None else None


def deployment_line(projection, width, height):
    """Use only the visible clear portion outside the measured envelope."""
    from coc_bot.attack.plans import MapPoint
    runs=[];current=[]
    for y in np.linspace(.12,.88,77):
        point=MapPoint(.055,float(y));x,pixel_y=projection.pixel(point)
        if input_area(x,pixel_y,width,height):
            current.append(point)
        elif current:
            runs.append(current);current=[]
    if current:runs.append(current)
    if not runs:return None
    best=max(runs,key=len)
    return (best[2],best[-3]) if len(best)>=15 else None
