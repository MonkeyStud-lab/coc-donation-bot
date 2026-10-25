"""Strict glyph matching for the current game font; no guessing missing digits."""
from functools import lru_cache
from pathlib import Path
import cv2
import numpy as np


def glyphs(image):
    if image is None or not image.size:
        return []
    hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
    neutral=hsv[:,:,2][hsv[:,:,1] <= 85]
    if not neutral.size:
        return []
    threshold=max(80,min(180,int(neutral.max()*.75)))
    mask=cv2.inRange(hsv,(0,0,threshold),(180,85,255))
    count,labels,stats,_=cv2.connectedComponentsWithStats(mask)
    boxes=[(x,y,w,h) for x,y,w,h,area in stats[1:]
           if h >= image.shape[0]*.32 and area >= 5 and w>=2]
    if not boxes:
        return []
    tallest=max(b[3] for b in boxes)
    boxes=sorted([b for b in boxes if b[3] >= tallest*.75],key=lambda b:b[0])
    result=[]
    pieces=[]
    for x,y,w,h in boxes:
        if w>h*1.25:
            projection=mask[y:y+h,x:x+w].sum(axis=0)
            lo,hi=round(w*.30),round(w*.70)
            cut=lo+int(np.argmin(projection[lo:hi]))
            if min(cut,w-cut)<h*.20:
                return []
            pieces.extend(((x,y,cut,h),(x+cut,y,w-cut,h)))
        else:
            pieces.append((x,y,w,h))
    for x,y,w,h in pieces:
        if w>h*1.25:
            return []
        shape=cv2.resize(mask[y:y+h,x:x+w],(24,32),interpolation=cv2.INTER_AREA)/255
        result.append((shape,w/h))
    return result


@lru_cache(maxsize=1)
def bank():
    path=Path(__file__).with_name('assets')/'digits.npz'
    if not path.is_file():
        return {}
    with np.load(path,allow_pickle=False) as archive:
        return {key:archive[key] for key in archive.files}


def read_digits(image, *, fraction=False, extra_templates=None):
    result=[]
    templates=bank() | (extra_templates or {})
    for shape,aspect in glyphs(image):
        scores={}
        for key,packed in templates.items():
            label=key.split('_')[0]
            if label=='slash' and not fraction:
                continue
            template=packed[:-1].reshape(32,24)
            overlap=float(np.minimum(shape,template).sum())/max(1,float(np.maximum(shape,template).sum()))
            score=overlap - min(.3,abs(aspect-float(packed[-1]))*.25)
            scores[label]=max(scores.get(label,0),score)
        ranked=sorted(scores.items(),key=lambda item:item[1],reverse=True)
        if len(ranked)<2 or ranked[0][1]<.86 or ranked[0][1]-ranked[1][1]<.035:
            return None
        result.append('/' if ranked[0][0]=='slash' else ranked[0][0])
    return ''.join(result) if result else None
