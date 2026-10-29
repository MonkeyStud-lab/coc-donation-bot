"""Compare the native active preview with the actual Home building arrangement.

Permanent terrain removes camera/zoom differences. Coarse structure/edge maps
avoid treating collector bubbles, wandering villagers or a native green badge
alone as evidence that the copied layout reached Home.
"""
import cv2
import numpy as np
from coc_bot.layouts.grid import camera,pixels


def active_preview(frame,slot):
    if type(slot) is not int or not 0<=slot<3:return None
    h,w=frame.shape[:2];top=round(h*.30);bottom=round(h*.77)
    region=frame[top:bottom]
    green=cv2.inRange(cv2.cvtColor(region,cv2.COLOR_BGR2HSV),(30,70,190),(90,255,255))
    contours,_=cv2.findContours(green,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    found=[]
    for contour in contours:
        x,y,bw,bh=cv2.boundingRect(contour)
        if (w*.27<bw<w*.34 and h*.30<bh<h*.43
            and abs(x+bw/2-w*(.185,.498,.811)[slot])<w*.04
            and cv2.contourArea(contour)/(bw*bh)>.92):
            margin=round(w*12/1853)
            found.append(frame[top+y+margin:top+y+bh-margin,x+margin:x+bw-margin])
    return found[0] if len(found)==1 else None


def signature(frame,stop=lambda:False,*,home=False):
    mapping=camera(frame,stop)
    if not mapping['registered'] or stop():return None
    size=352
    source=pixels(mapping,[(0,0),(44,0),(0,44)]).astype(np.float32)
    target=np.float32([[0,0],[size,0],[0,size]])
    image=cv2.warpAffine(frame,cv2.getAffineTransform(source,target),(size,size))
    hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
    grass=cv2.inRange(hsv,(23,35,70),(49,255,255))
    edge=cv2.Canny(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),50,120)
    features=np.stack([cv2.resize(a,(22,22),interpolation=cv2.INTER_AREA)/255
                       for a in (255-grass,edge)],axis=-1)
    centers=[(2*u+1,2*v+1) for v in range(22) for u in range(22)]
    points=pixels(mapping,centers).reshape(22,22,2);h,w=frame.shape[:2]
    x,y=points[:,:,0],points[:,:,1]
    visible=((x>w*.14)&(x<w*.86)&(y>h*.10)&(y<h*.79)) if home else ((x>0)&(x<w)&(y>0)&(y<h))
    return {'features':features.tolist(),'visible':visible.tolist()}


def compare(expected,actual):
    try:
        a=np.asarray(expected['features'],float);b=np.asarray(actual['features'],float)
        visible=np.asarray(expected['visible'],bool)&np.asarray(actual['visible'],bool)
        if a.shape!=(22,22,2) or b.shape!=a.shape or visible.shape!=(22,22):raise ValueError()
        if not np.isfinite(a).all() or not np.isfinite(b).all():raise ValueError()
        mask=np.zeros((22,22),bool);mask[4:18,4:18]=True;mask&=visible
        count=int(mask.sum())
        if count<128 or a[:,:,0][mask].std()<.08:
            return {'verified':False,'reason':'Insufficient visible building structure','cells':count}
        x,y=a[mask].ravel(),b[mask].ravel()
        correlation=float(np.corrcoef(x,y)[0,1]) if y.std()>.001 else 0.
        difference=float(np.abs(x-y).mean())
        return {'verified':correlation>=.90 and difference<=.09,'correlation':correlation,
                'difference':difference,'cells':count}
    except (ValueError,TypeError,KeyError,IndexError):
        return {'verified':False,'reason':'Layout structure evidence is unavailable'}
