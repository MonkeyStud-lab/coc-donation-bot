"""Detect stationary Build-list text, excluding animated thumbnails and timers."""
import cv2
import numpy as np


def menu_list_unchanged(before, after):
    if before.shape!=after.shape or len(before.shape)!=3:return False
    h,w=before.shape[:2]
    # Names and quantities, not the live village, icons, header or footer.
    a=before[round(h*.11):round(h*.89),round(w*.775):round(w*.925)]
    b=after[round(h*.11):round(h*.89),round(w*.775):round(w*.925)]
    if not a.size:return False
    masks=[cv2.inRange(cv2.cvtColor(c,cv2.COLOR_BGR2HSV),(0,0,190),(180,80,255))>0 for c in (a,b)]
    if min(m.sum() for m in masks)<100:return False
    overlap=2*np.count_nonzero(masks[0]&masks[1])/(masks[0].sum()+masks[1].sum())
    stable=(np.abs(a.astype(np.int16)-b.astype(np.int16)).max(axis=2)<=18).mean()
    return bool(overlap>=.99 and stable>=.97)
