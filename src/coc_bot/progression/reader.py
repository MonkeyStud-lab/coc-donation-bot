"""Read all priced building rows, including New and Other upgrades."""
import re
import cv2
import numpy as np
from functools import lru_cache
from pathlib import Path
from coc_bot.upgrades.vision import UpgradeReader, compact, text, currency, resource_amount, amount, crop


def row_key(row):
    return (compact(row['name']), row.get('new'), row.get('level'), row.get('cost'), row.get('currency'))


def wall_quantity(name, letters, *, extra_templates=None):
    """Read the suffix's actual glyphs; never translate an OCR '&' into 6."""
    stacked=re.fullmatch(r'(?i)\s*wall\s*[x×]\s*(\S{1,3})\s*',name)
    _,_,stats,_=cv2.connectedComponentsWithStats(letters)
    parts=sorted([(x,y,w,h) for x,y,w,h,area in stats[1:]
                  if h>=letters.shape[0]*.30 and area>=8])
    if stacked is None:
        return 1 if re.fullmatch(r'(?i)\s*wall\s*',name) and len(parts)==4 else None
    # W, a, l, l, x must all remain visible before the one-to-three digits.
    if not 6<=len(parts)<=8:return None
    tail=parts[5:]
    if any(h<max(v[3] for v in parts)*.75 for x,y,w,h in tail):return None
    x=min(v[0] for v in tail);y=min(v[1] for v in tail)
    right=max(a+c for a,b,c,d in tail);bottom=max(b+d for a,b,c,d in tail)
    from coc_bot.upgrades.digits import read_digits
    value=read_digits(cv2.cvtColor(letters[y:bottom,x:right],cv2.COLOR_GRAY2BGR),
                      extra_templates=counter_digit_variants()|red_digit_variants()|(extra_templates or {}))
    if not value or not re.fullmatch(r'\d{1,3}',value) or len(value)!=len(tail):return None
    # Conflicting valid OCR cannot authorize a quantity decrement receipt.
    if stacked[1].isdigit() and int(stacked[1])!=int(value):return None
    return int(value) if 1<=int(value)<=500 else None


def same_row_observation(first, second, shape):
    """Allow tiny scroll settling while requiring the same complete row identity."""
    if row_key(first)!=row_key(second):return False
    h,w=shape[:2]
    limits=(w*.005,h*.01,w*.005,h*.01)
    return all(abs(a-b)<=limit for a,b,limit in zip(first['box'],second['box'],limits))


def selected_title(frame, bounds, stop=None):
    image = crop(frame,bounds)
    mask = cv2.inRange(cv2.cvtColor(image,cv2.COLOR_BGR2HSV),(15,35,220),(65,200,255))
    count,labels,stats,_=cv2.connectedComponentsWithStats(mask)
    clean=np.zeros_like(mask)
    for i in range(1,count):
        if stats[i,3]>image.shape[0]*.40 and stats[i,4]>15:
            clean[labels==i]=255
    return text(255-clean,stop=stop)


@lru_cache(maxsize=1)
def red_digit_variants():
    with np.load(Path(__file__).with_name('assets')/'red_digits.npz',allow_pickle=False) as archive:
        variants = {key:archive[key] for key in archive.files}
    # The inspected capacity font supplies the same small outlined digits at
    # multiple pixel widths. Keep the normal strict score and ambiguity margin.
    with np.load(Path(__file__).with_name('assets')/'capacity_digits.npz',allow_pickle=False) as archive:
        variants.update({key:archive[key] for key in archive.files if key.split('_')[0]!='slash'})
    return variants


@lru_cache(maxsize=1)
def counter_digit_variants():
    with np.load(Path(__file__).with_name('assets')/'counter_digits.npz',allow_pickle=False) as archive:
        return {key:archive[key] for key in archive.files}


@lru_cache(maxsize=1)
def building_level_digit_variants():
    with np.load(Path(__file__).with_name('assets')/'building_level_digits.npz',allow_pickle=False) as archive:
        return {key:archive[key] for key in archive.files}


def balance_amount(image, stop=None):
    original=amount(image,stop)
    bright=cv2.inRange(cv2.cvtColor(image,cv2.COLOR_BGR2HSV),(0,0,230),(180,75,255))
    isolated=amount(cv2.cvtColor(bright,cv2.COLOR_GRAY2BGR),stop)
    if original is not None and isolated is not None and original!=isolated:return None
    if original is not None or isolated is not None:return original if original is not None else isolated
    # Empty resource bars show scenery and colored highlights behind the value.
    # Bound the complete bright digit group before matching the ORIGINAL glyphs.
    _,_,stats,_=cv2.connectedComponentsWithStats(bright)
    boxes=[(x,y,w,h) for x,y,w,h,area in stats[1:]
           if h>=image.shape[0]*.32 and area>=5 and .10<w/h<1.3]
    if not boxes:return None
    x=min(b[0] for b in boxes);y=min(b[1] for b in boxes)
    right=max(a+c for a,b,c,d in boxes);bottom=max(b+d for a,b,c,d in boxes)
    bounded=image[y:bottom,x:right]
    value=amount(bounded,stop)
    if value is not None:return value
    # Small white counters at starter halls use the same inspected outlined
    # font as capacity/price digits. Match the complete isolated group with
    # those existing variants; keep the strict glyph score and margin.
    from coc_bot.upgrades.digits import read_digits
    digits=read_digits(bounded,extra_templates=red_digit_variants())
    if digits and re.fullmatch(r'\d{1,9}',digits):return int(digits)
    # Pale scenery behind the translucent HUD can join the numeral outlines.
    # Require two strict glyph matches at separate brightness thresholds; never
    # turn a free-form OCR guess (e.g. 87 184 -> 873184) into spendable funds.
    readings=[]
    hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
    for threshold in (235,240):
        mask=cv2.inRange(hsv,(0,0,threshold),(180,75,255))
        value=read_digits(cv2.cvtColor(mask,cv2.COLOR_GRAY2BGR),extra_templates=red_digit_variants())
        if value and re.fullmatch(r'\d{1,9}',value):readings.append(int(value))
    return readings[0] if len(readings)==2 and readings[0]==readings[1] else None


class ProgressionReader(UpgradeReader):
    def wall_digit_templates(self):
        return {}

    def research_locked(self, frame):
        """Recognize the actual padlock in the Research tab, not a missing list."""
        if self.menu_kind(frame) != 'buildings':return False
        image=cv2.resize(frame,(1853,1048),interpolation=cv2.INTER_AREA)
        region=cv2.cvtColor(image[945:1020,1495:1580],cv2.COLOR_BGR2GRAY)
        reference=cv2.imread(str(Path(__file__).with_name('assets')/'research_lock.png'),cv2.IMREAD_GRAYSCALE)
        if reference is None:return False
        edges=cv2.Canny(region,60,150);target=cv2.Canny(reference,60,150)
        if np.count_nonzero(edges)<50:return False
        return float(cv2.matchTemplate(edges,target,cv2.TM_CCOEFF_NORMED).max())>=.94

    def availability(self,frame,kind):
        observed=super().availability(frame,kind)
        if observed is not None or kind!='buildings':return observed
        from coc_bot.upgrades.digits import read_digits
        raw=read_digits(crop(frame,(.739,.945,.788,.982)),fraction=True,
                        extra_templates=counter_digit_variants()) or ''
        match=re.fullmatch(r'(\d)/(\d)',raw)
        if not match:return None
        free,total=map(int,match.groups())
        return (free,total) if 0<=free<=total<=6 and total else None

    def target_level(self, frame, row):
        """Read only the black numeric target-level badge, never thumbnail art."""
        h,w=frame.shape[:2]
        _,top,_,_=row['box']
        region=frame[top+round(h*.035):top+round(h*.068),round(w*.736):round(w*.757)]
        dark=cv2.inRange(cv2.cvtColor(region,cv2.COLOR_BGR2HSV),(0,0,0),(180,255,65))
        # Thumbnail shadows can join the badge through a one-pixel bridge.
        # Separate that bridge before measuring the plate; otherwise thumbnail
        # highlights can become the tallest "digit" and hide a thin leading 1.
        kernel=max(2,round(w/1853*3))
        separated=cv2.morphologyEx(dark,cv2.MORPH_OPEN,np.ones((kernel,kernel),np.uint8))
        readings=[]
        for index,mask in enumerate((dark,separated)):
            contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
            badges=[]
            for contour in contours:
                x,y,bw,bh=cv2.boundingRect(contour)
                if not h*.012<bh<h*.028 or not .7<bw/bh<1.35:continue
                if cv2.contourArea(contour)/(bw*bh)<.50:continue
                from coc_bot.upgrades.digits import glyphs,read_digits
                badge=region[y:y+bh,x:x+bw]
                if index:badge=cv2.resize(badge,None,fx=2,fy=2,interpolation=cv2.INTER_NEAREST)
                count=len(glyphs(badge))
                if count not in (1,2):continue
                label=read_digits(badge,extra_templates=building_level_digit_variants())
                if label is None:label=text(badge,digits=True,stop=self.stop)
                # OCR can silently drop a thin leading 1: 13 must not become 3.
                # Every visible digit component must be represented in the result.
                if re.fullmatch(r'\d{1,2}',label) and len(label)==count and 1<=int(label)<=30:badges.append(int(label))
            if len(badges)==1:readings.append(badges[0])
        # Small wall badges can lose their border during separation. Preserve
        # the original observation, while conflicting valid reads still block.
        return readings[0] if readings and len(set(readings))==1 else None

    def balances(self, frame):
        value = super().balances(frame)
        for resource,box in (('gold',(.525,.035,.679,.072)),('elixir',(.525,.103,.679,.14))):
            if value[resource] is None:value[resource]=balance_amount(crop(frame,box),self.stop)
        # Low halls put the gem counter in the position used by dark elixir later.
        if currency(crop(frame,(.684,.16,.719,.22))) != 'dark_elixir':
            value['dark_elixir'] = None
        return value

    def rows(self, frame):
        if self.menu_kind(frame) not in ('buildings', 'research'):
            raise ValueError('The Build list is not verified')
        h, w = frame.shape[:2]
        top, bottom = round(h*.105), round(h*.89)
        strip = frame[top:bottom, round(w*.80):round(w*.97)]
        mask = cv2.inRange(cv2.cvtColor(strip, cv2.COLOR_BGR2HSV),
                           (7,45,getattr(self,'row_min_value',120)), (30,190,220))
        rows = (mask.mean(axis=1)/255 > getattr(self,'row_background_fraction',.45)).astype(np.uint8)
        rows = cv2.morphologyEx(rows[:,None], cv2.MORPH_CLOSE,
                               np.ones((getattr(self,'row_close_pixels',5),1),np.uint8))[:,0]
        found = []; start = None
        for y, value in enumerate(np.append(rows, 0)):
            if value and start is None:
                start = y
            if value or start is None:
                continue
            a, b = top+start, top+y; start = None
            if b-a < h*.060 or a <= top or b >= bottom:
                continue
            title = frame[a+3:min(b, a+round(h*.035)), round(w*.775):round(w*.925)]
            hsv = cv2.cvtColor(title,cv2.COLOR_BGR2HSV)
            letters = cv2.inRange(hsv,(0,0,205),(180,80,255)) | cv2.inRange(hsv,(35,80,170),(90,255,255))
            name = text(255-cv2.copyMakeBorder(letters,6,6,6,6,cv2.BORDER_CONSTANT,value=0), stop=self.stop)
            if not name.strip():name=text(title,stop=self.stop)
            quantity=wall_quantity(name,letters,extra_templates=self.wall_digit_templates())
            if quantity is not None and re.match(r'(?i)^\s*wall\s*[x×]',name):name='Wall'
            name = re.sub(r'(?i)\s+[x×]\s*\d+(?:\s+[\W\d_]+)?\s*$','',name).strip(' _=|.;—')
            name = {'clancastile':'Clan Castle','cannnon':'Cannon'}.get(compact(name),name)
            detail = text(frame[a+round(h*.035):min(b, a+round(h*.060)), round(w*.775):round(w*.85)], stop=self.stop)
            price_image = frame[a+round(h*.026):min(b,a+round(h*.065)), round(w*.85):round(w*.980)]
            price = resource_amount(price_image,self.stop)
            if price is None:
                hsv_price = cv2.cvtColor(price_image,cv2.COLOR_BGR2HSV)
                red = cv2.inRange(hsv_price,(0,90,140),(12,255,255)) | cv2.inRange(hsv_price,(170,90,140),(180,255,255))
                if np.count_nonzero(red) > 30:
                    price = amount(cv2.cvtColor(red,cv2.COLOR_GRAY2BGR),self.stop)
                    if price is None:
                        from coc_bot.upgrades.digits import read_digits
                        digits=read_digits(cv2.cvtColor(red,cv2.COLOR_GRAY2BGR),extra_templates=red_digit_variants())
                        if digits and re.fullmatch(r'\d{1,9}',digits):price=int(digits)
            resource_icon = frame[a+round(h*.028):min(b,a+round(h*.066)), round(w*.978):round(w*.996)]
            resource = currency(resource_icon)
            gem = cv2.inRange(cv2.cvtColor(resource_icon,cv2.COLOR_BGR2HSV),(35,70,130),(90,255,255))
            if gem.mean()/255 > .13:
                resource = 'gems'
            if compact(name)=='boat' and price is None and resource is None:
                from coc_bot.builder_base.vision import BuilderReader
                if BuilderReader(self.stop).find(frame,'setup_boat_free',(.93,a/h,.99,b/h),threshold=.94):
                    price,resource=0,'free'
            # Thumbnail levels are too small to authorize progression. Read the
            # full confirmation title instead of treating artwork as a number.
            level = None
            found.append({'name':name.strip(), 'cost':price, 'currency':resource, 'new':compact(detail)=='new',
                          'level':level, 'state':'upgrade', 'point':(round(w*.86), (a+b)//2), 'box':(round(w*.733),a,round(w*.267),b-a)})
            if compact(name)=='wall':found[-1]['quantity']=quantity
            if compact(name) in ('townhall','clancastle','wall'):
                found[-1]['target_level']=self.target_level(frame,found[-1])
        return found

    def filters_open(self, frame):
        return (compact(self.label(frame,(.348,.14,.49,.184)))=='resource'
                and compact(self.label(frame,(.348,.30,.43,.34)))=='type'
                and compact(self.label(frame,(.348,.553,.47,.60)))=='sorting')

    def selected_filter(self, frame):
        if not self.filters_open(frame):
            raise ValueError('Build filter controls could not be verified')
        for x,y in ((.418,.24),(.561,.24),(.704,.24),(.418,.397),(.561,.397),
                    (.418,.495),(.561,.495),(.704,.495)):
            image = crop(frame,(x-.062,y-.033,x+.062,y+.033))
            yellow = cv2.inRange(cv2.cvtColor(image,cv2.COLOR_BGR2HSV),(15,110,210),(36,255,255))
            if yellow.mean()/255 > .40:
                return round(x*frame.shape[1]),round(y*frame.shape[0])
        return None

    def unfiltered_top(self, frame):
        return any(label=='suggestedupgrades' for label,_,_ in self._headings(frame))
