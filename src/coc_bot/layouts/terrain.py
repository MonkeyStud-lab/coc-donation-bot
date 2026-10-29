"""Register permanent village terrain without treating it as a tile-grid proof.

The native empty-layout thumbnail supplies a reference independent of an
account's buildings. Correspondences exclude editor controls and the Empty
caption. This establishes a camera transform only; build-zone corners and
reserved building footprints still need independent native verification.
"""
import math
from functools import lru_cache

import cv2
import numpy as np


@lru_cache(maxsize=4)
def reference_features(shape, data, limit=6000):
    reference=np.frombuffer(data,np.uint8).reshape(shape)
    factor=min(4.,2300/max(shape[:2]))
    enlarged=cv2.resize(reference,None,fx=factor,fy=factor,interpolation=cv2.INTER_CUBIC)
    rh,rw=enlarged.shape[:2]
    mask=np.full((rh,rw),255,np.uint8)
    mask[round(rh*.39):round(rh*.67),round(rw*.28):round(rw*.75)]=0
    keys,descriptors=cv2.SIFT_create(nfeatures=limit,contrastThreshold=.02).detectAndCompute(
        cv2.cvtColor(enlarged,cv2.COLOR_BGR2GRAY),mask)
    return factor,keys,descriptors


def register(reference, frame, stop=lambda: False, *, feature_limit=6000):
    result = {'registered': False, 'reason': 'Insufficient consistent terrain landmarks'}
    if (not isinstance(reference, np.ndarray) or not isinstance(frame, np.ndarray)
        or reference.dtype != np.uint8 or frame.dtype != np.uint8
        or reference.ndim != 3 or frame.ndim != 3
        or reference.shape[2] != 3 or frame.shape[2] != 3
        or min(reference.shape[:2]) < 100 or min(frame.shape[:2]) < 200
        or max(reference.shape[:2]) > 1600 or max(frame.shape[:2]) > 4096):
        return result | {'reason': 'Invalid terrain reference or screenshot'}
    if stop():
        return result | {'reason': 'Stopped'}
    factor,keys,descriptors=reference_features(reference.shape,reference.tobytes(),feature_limit)
    h, w = frame.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    mask[round(h*.09):round(h*.79), :round(w*.80)] = 255
    mask[round(h*.40):round(h*.59), :round(w*.13)] = 0
    sift = cv2.SIFT_create(nfeatures=feature_limit, contrastThreshold=.02)
    observed, observed_descriptors = sift.detectAndCompute(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), mask)
    if stop():
        return result | {'reason': 'Stopped'}
    if descriptors is None or observed_descriptors is None or min(len(keys), len(observed)) < 24:
        return result
    matcher = cv2.BFMatcher()
    pairs = matcher.knnMatch(descriptors, observed_descriptors, k=2)
    reverse = matcher.match(observed_descriptors, descriptors)
    matches = [a for pair in pairs if len(pair) == 2 for a, b in [pair]
               if a.distance < .70*b.distance and reverse[a.trainIdx].trainIdx == a.queryIdx]
    if len(matches) < 24 or stop():
        return result
    source = np.float32([keys[m.queryIdx].pt for m in matches])
    target = np.float32([observed[m.trainIdx].pt for m in matches])
    transform, inliers = cv2.estimateAffinePartial2D(source, target, method=cv2.RANSAC,
                                                  ransacReprojThreshold=3, maxIters=10000)
    if transform is None or inliers is None or stop():
        return result
    accepted = inliers.ravel().astype(bool)
    if accepted.sum() < 24 or accepted.mean() < .75:
        return result
    src, dst = source[accepted], target[accepted]
    error = np.linalg.norm(src @ transform[:, :2].T + transform[:, 2] - dst, axis=1)
    spread = np.ptp(dst, axis=0)
    hull_area=cv2.contourArea(cv2.convexHull(dst))/(w*h)
    coverage=(spread[0]>=w*.12 and spread[1]>=h*.30 or
              spread[0]>=w*.60 and spread[1]>=h*.20 and hull_area>=.08)
    scale = math.hypot(transform[0, 0], transform[1, 0])
    rotation = math.degrees(math.atan2(transform[1, 0], transform[0, 0]))
    if (not np.isfinite(transform).all() or not .15 <= scale <= 2
        or abs(rotation) > 1 or not coverage
        or np.median(error) > 1 or np.quantile(error, .95) > 2.5):
        return result | {'reason': 'Terrain matches do not constrain a consistent camera',
                         'scale':float(scale),'rotation':float(rotation),
                         'spread':spread.tolist(),'median':float(np.median(error)),
                         'error_p95':float(np.quantile(error,.95)),'inliers':int(accepted.sum())}
    # Report coordinates in the original thumbnail, not its interpolation pyramid.
    transform[:, :2] *= factor
    return {'registered': True, 'reason': 'Permanent terrain landmarks agree',
            'transform': transform.tolist(), 'inliers': int(accepted.sum()),
            'matches': len(matches), 'error_p95': float(np.quantile(error, .95)),
            'landmark_hull': cv2.convexHull(dst).reshape(-1, 2).tolist(),
            'tile_grid_verified': False}


def project(registration, points):
    """Projection for inspection. It never certifies a legal build-zone target."""
    matrix = np.asarray(registration.get('transform'), dtype=float)
    points = np.asarray(points, dtype=float)
    if (registration.get('registered') is not True or matrix.shape != (2, 3)
        or points.ndim != 2 or points.shape[1] != 2
        or not np.isfinite(matrix).all() or not np.isfinite(points).all()):
        raise ValueError('Verified terrain registration and finite reference points are required')
    return points @ matrix[:, :2].T + matrix[:, 2]
