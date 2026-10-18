"""Reuse verified battle lettering only while the same bright controls remain."""
import cv2
import numpy as np


class BattleFrameGate:
    def __init__(self, recognize, active_recognize=None):
        self.recognize = recognize
        self.active_recognize = active_recognize
        self.reference = None
        self.shape = None
        self.active = False

    @staticmethod
    def masks(frame, active=False):
        h,w=frame.shape[:2]
        masks=[]
        controls = ((.45,.02,.55,.047),(.83,.695,.985,.73)) if active else (
            (.015,.715,.13,.775),(.45,.02,.55,.047))
        for left,top,right,bottom in controls:
            crop=frame[round(h*top):round(h*bottom),round(w*left):round(w*right)]
            masks.append(cv2.inRange(cv2.cvtColor(crop,cv2.COLOR_BGR2HSV),
                                     (0,0,185),(180,65,255))>0)
        return masks

    def accept(self, frame):
        masks=self.masks(frame,self.active)
        timer_confirmed=False
        if self.reference is not None and frame.shape==self.shape:
            timer_index=0 if self.active else 1
            timer_confirmed=self.same_lettering(masks[timer_index],self.reference[timer_index])
            # Positive foreground overlap, not an agreement on empty background.
            if all(self.same_lettering(a,b) for a,b in zip(masks,self.reference)):
                return True
        if self.recognize(frame):
            self.active=False
            self.reference=self.masks(frame)
            self.shape=frame.shape
            return True
        if self.reference is not None and self.active_recognize and self.active_recognize(
                frame,timer_confirmed=timer_confirmed):
            self.active=True
            self.reference=self.masks(frame,True)
            self.shape=frame.shape
            return True
        return False

    @staticmethod
    def same_lettering(a,b):
        return (a.shape==b.shape and a.sum()>100 and b.sum()>100 and
                2*np.count_nonzero(a&b)/(a.sum()+b.sum())>.94)
