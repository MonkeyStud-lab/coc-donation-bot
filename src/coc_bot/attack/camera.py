"""Evidence for camera movement; a pinch request alone never establishes readiness."""
import math
import cv2
import numpy as np


def compare_camera(before, after):
    result = {'verified': False, 'reason': 'insufficient stable map features', 'scale': None,
              'zoomed_out': False, 'maximum_zoom_confirmed': False,
              'battlefield_mapping_ready': False}
    if before.shape != after.shape:
        return result | {'reason': 'capture dimensions changed'}
    h, w = before.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    # Sparse starter bases can have too little artwork in the central crop.
    # Include distributed terrain landmarks, while excluding fixed combat HUD.
    mask[int(h*.12):int(h*.80), int(w*.15):int(w*.85)] = 255
    mask[:int(h*.29),:int(w*.28)] = 0
    mask[:int(h*.23),int(w*.76):] = 0
    mask[int(h*.70):,:int(w*.48)] = 0
    orb = cv2.ORB_create(nfeatures=5000)
    k2, d2 = orb.detectAndCompute(cv2.cvtColor(after, cv2.COLOR_BGR2GRAY), mask)
    if d2 is None or len(d2) < 2:
        return result
    candidates = []
    # Large pinches exceed ORB's normal scale range. Match a small image pyramid,
    # then convert every source point back into original screenshot coordinates.
    for factor in (1., .75, .5, .35, 1.25):
        small = cv2.resize(before, None, fx=factor, fy=factor)
        small_mask = cv2.resize(mask, (small.shape[1], small.shape[0]), interpolation=cv2.INTER_NEAREST)
        k1, d1 = orb.detectAndCompute(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), small_mask)
        if d1 is None or len(d1) < 2:
            continue
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
        pairs = matcher.knnMatch(d1, d2, k=2)
        reverse = matcher.match(d2, d1)
        matches = [pair[0] for pair in pairs if len(pair) == 2 and
                   pair[0].distance < .60 * pair[1].distance and
                   reverse[pair[0].trainIdx].trainIdx == pair[0].queryIdx]
        if len(matches) < 24:
            continue
        src = np.float32([np.array(k1[m.queryIdx].pt) / factor for m in matches])
        dst = np.float32([k2[m.trainIdx].pt for m in matches])
        transform, inliers = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC,
                                                       ransacReprojThreshold=3, maxIters=3000)
        if transform is None or inliers is None:
            continue
        accepted = inliers.ravel().astype(bool)
        stable = src[accepted]
        scale = math.hypot(transform[0, 0], transform[1, 0])
        rotation = math.degrees(math.atan2(transform[1, 0], transform[0, 0]))
        spread = np.ptp(stable, axis=0) if len(stable) else np.zeros(2)
        valid = (int(accepted.sum()) >= 24 and accepted.mean() >= .55 and
                 spread[0] >= w*.20 and spread[1] >= h*.20 and
                 .2 <= scale <= 1.5 and abs(rotation) < 4)
        candidates.append(result | {'verified': bool(valid), 'scale': float(scale),
            'inliers': int(accepted.sum()), 'matches': len(matches),
            'rotation_degrees': float(rotation), 'transform': transform.tolist(),
            'reason': 'map transform verified' if valid else
            'map features do not establish a consistent transform',
            'zoomed_out': bool(valid and scale < .97)})
        if valid and factor==1 and int(accepted.sum())>=80 and .97<scale<1.03:
            return candidates[-1]
    best=max(candidates, key=lambda c: (c['verified'], c['inliers'])) if candidates else result
    if best['verified']: return best
    # Home villages with large empty areas/repeated decorations can defeat ORB
    # after a vertical camera shift. SIFT uses unique reciprocal artwork matches;
    # the same distributed-inlier requirements still apply.
    sift=cv2.SIFT_create(nfeatures=3000)
    k1,d1=sift.detectAndCompute(cv2.cvtColor(before,cv2.COLOR_BGR2GRAY),mask)
    k2,d2=sift.detectAndCompute(cv2.cvtColor(after,cv2.COLOR_BGR2GRAY),mask)
    if d1 is None or d2 is None or min(len(d1),len(d2))<2:return best
    matcher=cv2.BFMatcher();reverse=matcher.match(d2,d1)
    pairs=matcher.knnMatch(d1,d2,k=2)
    good=[p[0] for p in pairs if len(p)==2 and p[0].distance<.60*p[1].distance and reverse[p[0].trainIdx].trainIdx==p[0].queryIdx]
    if len(good)<24:return best
    src=np.float32([k1[m.queryIdx].pt for m in good]);dst=np.float32([k2[m.trainIdx].pt for m in good])
    transform,inliers=cv2.estimateAffinePartial2D(src,dst,method=cv2.RANSAC,ransacReprojThreshold=3,maxIters=3000)
    if transform is None or inliers is None:return best
    accepted=inliers.ravel().astype(bool);stable=src[accepted]
    scale=math.hypot(transform[0,0],transform[1,0]);rotation=math.degrees(math.atan2(transform[1,0],transform[0,0]))
    spread=np.ptp(stable,axis=0) if len(stable) else np.zeros(2)
    if (accepted.sum()<24 or accepted.mean()<.65 or spread[0]<w*.20 or spread[1]<h*.20 or
            not .2<=scale<=4 or abs(rotation)>=4):return best
    return result|{'verified':True,'reason':'map transform verified using reciprocal artwork features',
                   'scale':float(scale),'inliers':int(accepted.sum()),'matches':len(good),
                   'rotation_degrees':rotation,'transform':transform.tolist(),'zoomed_out':scale<.97}


def compare_zoom(before, after):
    """Scale-only evidence for repeated home decorations; never a map transform.

    Several different translation models must independently agree on zoom.
    This cannot authorize opponent coordinates or automatic deployment.
    """
    if before.shape!=after.shape:return {'verified_zoom':False}
    h,w=before.shape[:2];mask=np.zeros((h,w),np.uint8)
    mask[int(h*.18):int(h*.82),int(w*.13):int(w*.87)]=255
    sift=cv2.SIFT_create(nfeatures=5000)
    ka,da=sift.detectAndCompute(cv2.cvtColor(before,cv2.COLOR_BGR2GRAY),mask)
    kb,db=sift.detectAndCompute(cv2.cvtColor(after,cv2.COLOR_BGR2GRAY),mask)
    if da is None or db is None or min(len(da),len(db))<2:return {'verified_zoom':False}
    matcher=cv2.BFMatcher();reverse=matcher.match(db,da)
    pairs=matcher.knnMatch(da,db,k=2)
    matches=[p[0] for p in pairs if len(p)==2 and p[0].distance<.6*p[1].distance and reverse[p[0].trainIdx].trainIdx==p[0].queryIdx]
    source=np.float32([ka[m.queryIdx].pt for m in matches]);target=np.float32([kb[m.trainIdx].pt for m in matches]);scales=[];primary=None
    for _ in range(4):
        if len(source)<12:break
        matrix,inliers=cv2.estimateAffinePartial2D(source,target,method=cv2.RANSAC,ransacReprojThreshold=3,maxIters=3000)
        if matrix is None or inliers is None:break
        good=inliers.ravel().astype(bool)
        if good.sum()<12:break
        scale=float(np.hypot(matrix[0,0],matrix[1,0]));rotation=np.degrees(np.arctan2(matrix[1,0],matrix[0,0]))
        spread=np.ptp(source[good],axis=0)
        if .2<scale<4 and abs(rotation)<4:
            if primary is None and good.sum()>=24 and spread[0]>w*.20 and spread[1]>h*.20:
                primary=scale;scales.append(scale)
            elif primary is not None and abs(scale-primary)<.005 and spread[0]>w*.025 and spread[1]>h*.015:
                scales.append(scale)
        source,target=source[~good],target[~good]
    if len(scales)<2 or max(scales)-min(scales)>.005:return {'verified_zoom':False}
    return {'verified_zoom':True,'scale':float(np.median(scales)),
            'battlefield_mapping_ready':False,'reason':'Independent artwork groups agree on zoom only'}


def compare_home_zoom(before, after):
    """A wider HOME-only feature mask, excluding fixed HUD widgets.

    Sparse villages may keep their distinctive walls near the left edge. This
    evidence is for restoring home zoom only, never opponent deployment.
    """
    if before.shape != after.shape:return {'verified_zoom':False}
    h,w=before.shape[:2];mask=np.zeros((h,w),np.uint8)
    mask[round(h*.03):round(h*.86),round(w*.01):round(w*.98)]=255
    # Keep edge landmarks while excluding the actual fixed home controls:
    # player badge, resources, trophies/chat, shop, and bottom corner buttons.
    for y0,y1,x0,x1 in ((0,.20,0,.22),(0,.38,.76,1),
                         (.18,.60,0,.11),(.40,.60,.89,1),
                         (.70,1,.87,1),(.78,1,0,.20)):
        mask[round(h*y0):round(h*y1),round(w*x0):round(w*x1)]=0
    sift=cv2.SIFT_create(nfeatures=7000)
    b,db=sift.detectAndCompute(cv2.cvtColor(after,cv2.COLOR_BGR2GRAY),mask)
    if db is None or len(db)<2:return {'verified_zoom':False}
    matcher=cv2.BFMatcher()
    # At a large scale change, rendering removes different fine details. A
    # source pyramid compares artwork at similar sizes instead of relaxing
    # reciprocal matching or the distributed-inlier requirements.
    for factor in (1., .5, .35, .75):
        image=cv2.resize(before,None,fx=factor,fy=factor)
        source_mask=cv2.resize(mask,(image.shape[1],image.shape[0]),interpolation=cv2.INTER_NEAREST)
        a,da=sift.detectAndCompute(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),source_mask)
        if da is None or len(da)<2:continue
        reverse=matcher.match(db,da);pairs=matcher.knnMatch(da,db,k=2)
        matches=[p[0] for p in pairs if len(p)==2 and p[0].distance<.60*p[1].distance and
                 reverse[p[0].trainIdx].trainIdx==p[0].queryIdx]
        if len(matches)<24:continue
        source=np.float32([np.array(a[m.queryIdx].pt)/factor for m in matches])
        target=np.float32([b[m.trainIdx].pt for m in matches])
        matrix,inliers=cv2.estimateAffinePartial2D(source,target,method=cv2.RANSAC,
                                                  ransacReprojThreshold=3,maxIters=3000)
        if matrix is None or inliers is None:continue
        good=inliers.ravel().astype(bool)
        if good.sum()<24 or good.mean()<.60:continue
        spread=np.ptp(source[good],axis=0)
        scale=float(np.hypot(matrix[0,0],matrix[1,0]))
        rotation=float(np.degrees(np.arctan2(matrix[1,0],matrix[0,0])))
        if (spread[0]<w*.20 or spread[1]<h*.20 or
                not .2<scale<4 or abs(rotation)>=2):continue
        return {'verified_zoom':True,'scale':scale,'transform':matrix.tolist(),
                'battlefield_mapping_ready':False,'reason':'Distributed home-world features establish zoom'}
    return {'verified_zoom':False}
