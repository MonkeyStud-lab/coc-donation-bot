"""Default Home Village tile geometry, registered to each fresh editor camera.

Terrain registration proves a camera, not the legality of a placement. Every
released inventory item additionally requires the native green floor outline.
Other sceneries fail registration instead of inheriting these coordinates.
"""
from pathlib import Path
import cv2
import numpy as np
from coc_bot.layouts.terrain import register, project

ORIGIN = np.array([284., 7.1])
BASIS = np.array([[5.6, -5.6], [4.2, 4.2]])
SIZE = 44


def camera(frame, stop=lambda: False):
    reference = cv2.imread(str(Path(__file__).with_name('assets')/'empty_terrain.png'))
    result=register(reference,frame,stop)
    # Crowded editor views can use the feature budget on building roofs. A
    # larger bounded retry retains the SAME geometric acceptance thresholds.
    if not result['registered'] and not stop():
        result=register(reference,frame,stop,feature_limit=12000)
    return result


def pixels(registration, tiles):
    points = np.asarray(tiles, dtype=float)
    if points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all():
        raise ValueError('Finite tile coordinates are required')
    return project(registration, points @ BASIS.T + ORIGIN)


def tiles(registration, points):
    matrix = np.asarray(registration.get('transform'), dtype=float)
    if registration.get('registered') is not True or matrix.shape != (2,3) or not np.isfinite(matrix).all():
        raise ValueError('Verified camera required')
    points = np.asarray(points,dtype=float)
    if points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all():
        raise ValueError('Finite points required')
    reference = (points-matrix[:,2]) @ np.linalg.inv(matrix[:,:2]).T
    return (reference-ORIGIN) @ np.linalg.inv(BASIS).T


def zone(registration, margin=1):
    """Conservative interior. Never include the outer decorative obstacle ring."""
    if not 0<=margin<=5:raise ValueError('Invalid build-zone margin')
    return pixels(registration, [(margin,margin),(SIZE-margin,margin),
                                 (SIZE-margin,SIZE-margin),(margin,SIZE-margin)])


def outline(frame, pointer, registration, *, wall=False):
    """Read the lower V of the floor. Lime movement arrows do not qualify.

    Buildings hide the upper two sides of their footprint. The exposed lower
    sides must agree in size, angle and colour with the registered tile grid.
    Red is an explicit rejection; unreadable is never accepted as green.
    """
    if registration.get('registered') is not True:return None
    m=np.asarray(registration['transform']);scale=float(np.hypot(m[0,0],m[1,0]))
    h,w=frame.shape[:2];px,py=pointer
    extent=round(5*6*scale+25)
    x0=max(0,px-extent);x1=min(w,px+extent)
    y0=max(0,py-extent*2);y1=min(h,py+extent)
    if x1<=x0 or y1<=y0:return None
    hsv=cv2.cvtColor(frame[y0:y1,x0:x1],cv2.COLOR_BGR2HSV)
    masks={'green':cv2.inRange(hsv,(52,100,80),(80,255,255)),
           'red':cv2.inRange(hsv,(0,165,155),(4,255,255))|cv2.inRange(hsv,(176,165,155),(180,255,255))}
    components={}
    for colour,mask in masks.items():
        connected=cv2.dilate(mask,np.ones((3,3),np.uint8))
        _,labels,stats,_=cv2.connectedComponentsWithStats(connected)
        components[colour]=(labels,stats)
    found=[]
    estimate=tiles(registration,[[px,py-30]])[0]
    for n in range(1,2 if wall else 6):
        base=np.round(estimate-n/2)+n/2
        for du in (-1,0,1):
            for dv in (-1,0,1):
                uv=base+[du,dv];cx,cy=pixels(registration,[uv])[0]
                bottom=cy+4.2*scale*n
                if (abs(cx-px)>max(25,5.6*scale) or not -max(10,4.2*scale*n-10)<py-bottom<65
                    or bottom>h*.79):continue
                for colour,mask in masks.items():
                    near=cv2.dilate(mask,np.ones((5,5),np.uint8));scores=[];outside=[]
                    for sign in (-1,1):
                        left=np.array([cx+sign*5.6*scale*n,cy]);low=np.array([cx,bottom])
                        line=np.array([left+(low-left)*t for t in np.linspace(.13,.90,36)])
                        normal=np.array([sign*4.2,5.6]);normal=normal/np.linalg.norm(normal)*5
                        samples=np.rint(line-[x0,y0]).astype(int)
                        beyond=np.rint(line+normal-[x0,y0]).astype(int)
                        if (samples<0).any() or (beyond<0).any() or (samples[:,0]>=mask.shape[1]).any() or (samples[:,1]>=mask.shape[0]).any() or (beyond[:,0]>=mask.shape[1]).any() or (beyond[:,1]>=mask.shape[0]).any():break
                        scores.append(float((near[samples[:,1],samples[:,0]]>0).mean()))
                        outside.append(float((mask[beyond[:,1],beyond[:,0]]>0).mean()))
                    # Match the boundary itself, not a connected-component box
                    # that can merge with a nearby tree or movement arrow.
                    # Outside contrast distinguishes the full footprint from a
                    # small diamond embedded inside a larger green footprint.
                    if len(scores)!=2 or min(scores)<.84 or max(outside)>.35:continue
                    if not wall:
                        # The floor is tiled: its inner 1x1/2x2 diamonds can
                        # share the same lower V as a 3x3 building. The actual
                        # connected floor must have the candidate's full width.
                        labels,stats=components[colour]
                        xx,yy=round(cx-x0),round(bottom-y0)
                        patch=labels[max(0,yy-3):min(labels.shape[0],yy+4),max(0,xx-3):min(labels.shape[1],xx+4)]
                        ids=np.unique(patch);ids=ids[ids>0]
                        if len(ids)!=1:continue
                        _,_,bw,bh,_=stats[ids[0]]
                        width=2*5.6*scale*n;height=2*4.2*scale*n
                        if not .86*width<=bw<=1.15*width+6 or bh>1.25*height+6:continue
                    found.append({'colour':colour,'size':n,'center':[float(cx),float(cy)],
                                  'tile_center':uv.tolist(),'score':min(scores)})
    unique={(a['colour'],a['size'],tuple(a['tile_center'])):a for a in found}
    return next(iter(unique.values())) if len(unique)==1 else None


def safe_preview(value):
    if not value or value.get('colour')!='green':return False
    n=value['size'];u,v=value['tile_center']
    return n/2<=u<=SIZE-n/2 and n/2<=v<=SIZE-n/2


def reserved_tiles(frame, registration):
    """Block uncertain future footprints as well as their visible white edges.

    Three or four observed tile-aligned sides and a grass interior protect a
    whole future footprint. Bright roofs and occupied footprints cannot reserve
    a large surrounding area merely because they contain white artwork.
    """
    h,w=frame.shape[:2]
    target=np.float32([[0,0],[SIZE*12,0],[0,SIZE*12]])
    source=pixels(registration,[(0,0),(SIZE,0),(0,SIZE)]).astype(np.float32)
    warp=cv2.warpAffine(frame,cv2.getAffineTransform(source,target),(SIZE*12,SIZE*12))
    hsv=cv2.cvtColor(warp,cv2.COLOR_BGR2HSV)
    bright=cv2.inRange(hsv,(0,0,180),(180,80,255))
    # Include translucent white footprint edges on bright grass.
    contrast=cv2.morphologyEx(hsv[:,:,2],cv2.MORPH_TOPHAT,np.ones((7,7),np.uint8))
    # Sunlit grass itself can have saturation below 160. It is not a white
    # footprint. Less-neutral translucent edges require actual local contrast.
    bright|=cv2.inRange(hsv,(0,0,175),(180,130,255)) & cv2.inRange(contrast,14,255)
    near=cv2.dilate(bright,np.ones((5,5),np.uint8))
    grass=cv2.inRange(hsv,(23,45,105),(47,225,255))
    blocked=np.zeros((SIZE,SIZE),bool)
    # Work on actual integer tile edges. A closed empty square reserves its
    # interior; existing building roofs never reserve a wide surrounding band.
    # Three independently observed sides also protect a partly occluded square.
    for n in range(1,6):
        for u in range(SIZE-n+1):
            x=u*12;right=(u+n)*12-1
            for v in range(SIZE-n+1):
                y=v*12;bottom=(v+n)*12-1
                xx=np.rint(np.linspace(x+2,right-2,max(8,n*8))).astype(int)
                yy=np.rint(np.linspace(y+2,bottom-2,max(8,n*8))).astype(int)
                scores=np.array([(near[y,xx]>0).mean(),(near[bottom,xx]>0).mean(),
                                 (near[yy,x]>0).mean(),(near[yy,right]>0).mean()])
                if not ((scores>=.75).all() or (scores>=.90).sum()>=3):continue
                interior=grass[y+4:bottom-3,x+4:right-3]
                if not interior.size or (interior>0).mean()<.86:continue
                blocked[u:u+n,v:v+n]=True
    return blocked
