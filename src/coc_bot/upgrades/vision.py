"""Read the inspected landscape Build menu; unknown layouts fail closed."""
from dataclasses import dataclass, asdict
from pathlib import Path
import re
import tempfile
import csv
import io

import cv2
import numpy as np

from coc_bot.runtime.processes import run_process


def compact(text):
    return re.sub(r"[^a-z]", "", text.lower())


def crop(frame, box):
    h, w = frame.shape[:2]
    a, b, c, d = box
    return frame[round(b*h):round(d*h), round(a*w):round(c*w)]


def text(image, *, digits=False, fraction=False, stop=None):
    if image is None or not image.size:
        return ""
    if stop and stop():
        return ""
    if (digits or fraction) and image.ndim==3:
        hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
        gray=cv2.bitwise_not(cv2.inRange(hsv,(0,0,170),(180,75,255)))
        gray=cv2.copyMakeBorder(gray,8,8,8,8,cv2.BORDER_CONSTANT,value=255)
    else:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    gray = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder)/"label.png"
        cv2.imwrite(str(path), gray)
        command = ["tesseract", str(path), "stdout", "--psm", "7", "-l", "eng"]
        if digits or fraction:
            command += ["-c", "tessedit_char_whitelist=0123456789" + ("/" if fraction else "")]
        result = run_process(command, text=True, timeout=4, stop_check=stop)
        return (result.stdout or "").strip() if result.returncode == 0 else ""


def amount(image, stop=None):
    from coc_bot.upgrades.digits import read_digits
    raw = read_digits(image) or ''
    if not re.fullmatch(r"[\d\s]+", raw):
        return None
    value = int(re.sub(r"\s", "", raw))
    return value if 0 <= value <= 500_000_000 else None


def currency(image):
    if not image.size:
        return None
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    masks = {
        "dark_elixir": ((110,40,35),(175,255,145)),
        "elixir": ((130,70,150),(175,255,255)),
        "gold": ((15,100,150),(34,255,255)),
    }
    scores = {key: float(cv2.inRange(hsv, lo, hi).mean())/255
              for key,(lo,hi) in masks.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > .07 else None


@dataclass(frozen=True)
class Candidate:
    name: str
    cost: int
    currency: str
    point: tuple[int,int]

    def public(self):
        return asdict(self)


class UpgradeReader:
    def __init__(self, stop=None):
        self.stop = stop

    def label(self, frame, box):
        return text(crop(frame, box), stop=self.stop)

    def menu_kind(self, frame):
        h,w = frame.shape[:2]
        if not 1.6 < w/h < 1.95:
            return None
        # Both this heading and the red close control must be present.
        close = crop(frame,(.973,.008,.997,.055))
        hsv=cv2.cvtColor(close,cv2.COLOR_BGR2HSV)
        red=cv2.bitwise_or(cv2.inRange(hsv,(0,100,100),(10,255,255)),
                           cv2.inRange(hsv,(170,100,100),(180,255,255)))
        if float(red.mean())/255 < .15:
            return None
        title = compact(self.label(frame, (.79,.012,.96,.05)))
        if title == "armyupgrades":
            return "research"
        if title in ("buildingsheroes", "buildingheroes"):
            return "buildings"
        return None

    def detail_close(self, frame):
        close=crop(frame,(.865,.04,.907,.113))
        hsv=cv2.cvtColor(close,cv2.COLOR_BGR2HSV)
        red=cv2.bitwise_or(cv2.inRange(hsv,(0,100,100),(10,255,255)),
                           cv2.inRange(hsv,(170,100,100),(180,255,255)))
        white=cv2.inRange(hsv,(0,0,200),(180,65,255))
        if red.mean()/255 < .20 or white.mean()/255 < .08:
            return None
        label=compact(self.label(frame,(.26,.035,.73,.095)))
        if not label.startswith(('upgrade','upgrading')) or 'toleve' not in label:
            return None
        h,w=frame.shape[:2]
        return round(w*.886),round(h*.075)

    def running_detail(self, frame, candidate):
        heading=compact(self.label(frame,(.26,.035,.73,.095)))
        timer=compact(self.label(frame,(.79,.82,.895,.865)))
        return (heading.startswith('upgrading'+compact(candidate.name)+'toleve')
                and timer=='timeleft' and self.detail_close(frame) is not None)

    def availability(self, frame, kind):
        from coc_bot.upgrades.digits import read_digits
        box = (.739,.945,.788,.982) if kind == 'buildings' else (.808,.945,.854,.982)
        raw = read_digits(crop(frame,box),fraction=True) or ''
        match = re.fullmatch(r'(\d)/(\d)',raw)
        if not match:
            return None
        free,total=map(int,match.groups())
        return (free,total) if 0 <= free <= total <= 6 else None

    def balances(self, frame):
        return {key:amount(crop(frame,box),self.stop) for key,box in {
            'gold':(.56,.033,.679,.073),
            'elixir':(.56,.104,.679,.143),
            'dark_elixir':(.59,.17,.685,.217),
        }.items()}

    def _headings(self, frame):
        """Read section labels with their positions; never infer them from color."""
        h,w=frame.shape[:2]
        strip=crop(frame,(.735,.065,.998,.892))
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'panel.png'
            cv2.imwrite(str(path),cv2.resize(strip,None,fx=2,fy=2))
            result=run_process(['tesseract',str(path),'stdout','--psm','6','-l','eng','tsv'],
                               text=True,timeout=6,stop_check=self.stop)
        words=list(csv.DictReader(io.StringIO(result.stdout or ''),delimiter='\t'))
        found=[]
        for i,word in enumerate(words[:-1]):
            first=compact(word.get('text',''))
            second=compact(words[i+1].get('text',''))
            phrase=first+second
            section='suggested' if first.startswith('suggested') and 'up' in phrase else ('other' if first.startswith('other') and 'up' in phrase else None)
            if section is not None:
                top=int(word['top'])/2+round(h*.065)
                bottom=(int(word['top'])+int(word['height']))/2+round(h*.065)
                found.append((section+'upgrades',round(top),round(bottom)))
        return found

    def candidates(self, frame):
        """Read only Suggested upgrades, never silently use Other upgrades."""
        h,w=frame.shape[:2]
        top=bottom=None
        for label,y0,y1 in self._headings(frame):
            if label == 'suggestedupgrades':
                top=y1+round(h*.008)
            elif label == 'otherupgrades' and top is not None:
                bottom=y0-round(h*.003)
                break
        if top is None or bottom is None:
            return [], False
        # Colored card interiors delimit rows; artwork is excluded from the test strip.
        strip=frame[top:bottom,round(w*.86):round(w*.90)]
        hsv=cv2.cvtColor(strip,cv2.COLOR_BGR2HSV)
        mask=cv2.inRange(hsv,(7,45,120),(30,190,220))
        rows=(mask.mean(axis=1)/255 > .70).astype(np.uint8)
        spans=[]; start=None
        for y,value in enumerate(np.append(rows,0)):
            if value and start is None:
                start=y
            if not value and start is not None:
                if y-start > h*.045:
                    spans.append((top+start,top+y))
                start=None
        found=[]
        for y0,y1 in spans:
            height=y1-y0
            name=text(frame[y0+round(height*.04):y0+round(height*.48),
                            round(w*.775):round(w*.953)],stop=self.stop)
            price=amount(frame[y0+round(height*.46):y1-round(height*.04),
                               round(w*.85):round(w*.983)],self.stop)
            resource=currency(frame[y0+round(height*.30):y1,
                                    round(w*.979):round(w*.996)])
            if name and price and resource:
                found.append(Candidate(name,price,resource,(round(w*.86),(y0+y1)//2)))
        return found, bottom < round(h*.89)

    def confirmation(self, frame, candidate):
        heading=self.label(frame,(.26,.035,.73,.095))
        normalized=compact(heading)
        if not normalized.startswith('upgrade'+compact(candidate.name)+'toleve'):
            return None
        h,w=frame.shape[:2]
        x0,y0=round(w*.46),round(h*.80)
        button=frame[y0:round(h*.95),x0:round(w*.79)]
        hsv=cv2.cvtColor(button,cv2.COLOR_BGR2HSV)
        green=cv2.inRange(hsv,(35,80,130),(90,255,255))
        green=cv2.morphologyEx(green,cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))
        contours,_=cv2.findContours(green,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        targets=[]
        for contour in contours:
            x,y,bw,bh=cv2.boundingRect(contour)
            if bw < w*.12 or bh < h*.07:
                continue
            cell=button[y:y+bh,x:x+bw]
            label=text(cell[round(bh*.10):round(bh*.40),round(bw*.15):round(bw*.85)],stop=self.stop)
            price=amount(cell[round(bh*.48):round(bh*.91),round(bw*.10):round(bw*.80)],self.stop)
            resource=currency(cell[round(bh*.35):round(bh*.95),round(bw*.79):round(bw*.99)])
            normalized=compact(label).replace('contirm','confirm')
            if not re.fullmatch(r'(?:ge)?(?:confirm|upgrade)',normalized):
                continue
            if price==candidate.cost and resource==candidate.currency:
                targets.append({'point':(x0+x+bw//2,y0+y+bh//2), 'level_text':heading,
                                'name':candidate.name,'cost':price,'currency':resource})
        return targets[0] if len(targets)==1 else None

    def active_names(self, frame):
        """Active upgrades use green progress rows above Suggested upgrades."""
        h,w=frame.shape[:2]
        headings=self._headings(frame)
        bottom=next((y0 for label,y0,_ in headings if label=='suggestedupgrades'),None)
        if bottom is None: return []
        panel=frame[round(h*.07):bottom,round(w*.735):round(w*.998)]
        hsv=cv2.cvtColor(panel,cv2.COLOR_BGR2HSV)
        green=cv2.inRange(hsv,(35,60,65),(90,255,255))
        # Newly started upgrades have only a thin green sliver at the left edge.
        rows=(green.mean(axis=1)/255 > .003).astype(np.uint8)
        result=[]; start=None
        for y,value in enumerate(np.append(rows,0)):
            if value and start is None: start=y
            if not value and start is not None:
                if y-start > h*.023:
                    a=start+round(h*.07); b=y+round(h*.07)
                    region=frame[a:b,round(w*.74):round(w*.93)]
                    hsv=cv2.cvtColor(region,cv2.COLOR_BGR2HSV)
                    mask=cv2.inRange(hsv,(0,0,220),(180,65,255))
                    letters=cv2.copyMakeBorder(255-mask,8,8,8,8,cv2.BORDER_CONSTANT,value=255)
                    result.append(compact(text(letters,stop=self.stop)))
                start=None
        return result
