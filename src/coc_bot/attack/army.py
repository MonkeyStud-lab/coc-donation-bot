"""Read visible army cards without changing selection or authorizing deployment."""
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from functools import lru_cache
import re
import shutil
import subprocess
import tempfile

import cv2
import numpy as np

from coc_bot.adb.client import AdbStopped
from coc_bot.runtime.processes import run_process, ProcessStopped


def check_stop(stop_check):
    if stop_check and stop_check():
        raise AdbStopped('Army observation stopped')


@dataclass(frozen=True)
class ArmyCard:
    slot: str
    box: tuple[int, int, int, int]
    unit_id: str | None
    kind: str
    quantity: int | None
    identity_score: float = 0
    identity_margin: float = 0
    stable: bool = False
    confirmed: bool = False
    quantity_source: str = 'unreadable'

    def to_dict(self):
        return asdict(self)


class UnitCatalog:
    """Match alpha-masked artwork; confidence and runner-up margin must agree.

    Unknown heroes/skins are deliberately not named from card order or level.
    Downloaded artwork is supplemented by private, explicitly reviewed card crops.
    """
    def __init__(self, icons_dir: Path, units: dict | None = None):
        self.templates = []
        self.references = []
        for path in sorted(Path(icons_dir).rglob('*')):
            if path.suffix.lower() not in ('.webp', '.png'):
                continue
            image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
            if image is None or image.ndim != 3 or image.shape[2] != 4:
                continue
            alpha = (image[:,:,3] > 100).astype(np.uint8)*255
            if np.count_nonzero(alpha) < 100:
                continue
            stats = (units or {}).get(path.stem)
            siege_ids = {'wall_wrecker','battle_blimp','stone_slammer','siege_barracks',
                         'log_launcher','flame_flinger','battle_drill'}
            kind = stats.category if stats else ('spell' if path.parent.name == 'spells' else
                                                 'siege' if path.stem in siege_ids else 'troop')
            self.templates.append((path.stem, kind, image[:,:,:3], alpha))

    def add_references(self, frame, cards, *, picker=False):
        """Carry artwork identity across pages, never slot positions or quantities."""
        sift = cv2.SIFT_create(nfeatures=500)
        for card in cards:
            if not card.unit_id or not (card.stable or card.confirmed):
                continue
            x,y,w,h = card.box
            image = frame[y:y+h,x:x+w]
            mask = np.zeros((h,w),np.uint8)
            # Deployed heroes gain an ability graphic over the lower portrait.
            # Keep their crown/face landmarks too; counts and bottom levels are
            # still excluded for stacked troops and spells.
            top = .08 if card.kind == 'hero' else .24
            if picker:
                # Picker cards share level/housing badges and Info controls.
                # Only central facial artwork may establish troop identity.
                mask[round(h*.25):round(h*.78),round(w*.32):round(w*.78)] = 255
            else:
                mask[round(h*top):round(h*.78),round(w*.15):round(w*.85)] = 255
            keys,descriptors = sift.detectAndCompute(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),mask)
            if descriptors is not None:
                self.references.append((card.unit_id,card.kind,keys,descriptors,w,h))

    def identify_reference(self, cell, *, kind=None, stop_check=None):
        if not self.references:
            return None
        keys,descriptors=cv2.SIFT_create(nfeatures=500).detectAndCompute(cv2.cvtColor(cell,cv2.COLOR_BGR2GRAY),None)
        if descriptors is None or len(descriptors)<2:
            return None
        accepted = {}
        for unit_id,category,ref_keys,ref_desc,w,h in self.references:
            check_stop(stop_check)
            if kind is not None and category != kind:
                continue
            pairs=cv2.BFMatcher().knnMatch(ref_desc,descriptors,k=2)
            matches=[p[0] for p in pairs if len(p)==2 and p[0].distance<.65*p[1].distance]
            if len(matches)<8:
                continue
            source=np.float32([ref_keys[m.queryIdx].pt for m in matches])
            target=np.float32([keys[m.trainIdx].pt for m in matches])
            transform,inliers=cv2.estimateAffinePartial2D(source,target,method=cv2.RANSAC,ransacReprojThreshold=2)
            if transform is None or inliers is None:
                continue
            good=inliers.ravel().astype(bool)
            scale=float(np.hypot(transform[0,0],transform[1,0]))
            rotation=float(np.degrees(np.arctan2(transform[1,0],transform[0,0])))
            spread=np.ptp(source[good],axis=0)
            # A hero's ability artwork replaces much of its portrait. Allow
            # those outliers only with twice as many agreeing landmarks and
            # wider two-dimensional coverage, never a pet badge alone.
            quality=(good.mean()>=.65 or category=='hero' and good.sum()>=16 and
                     good.mean()>=.55 and spread[0]>w*.25 and spread[1]>h*.25)
            if (good.sum()>=8 and quality and .4<scale<2.5 and abs(rotation)<8 and
                    spread[0]>w*.20 and spread[1]>h*.15):
                score=(int(good.sum()),float(good.mean()),category)
                if unit_id not in accepted or score>accepted[unit_id]:
                    accepted[unit_id]=score
        scores=sorted([(n,ratio,unit_id,category) for unit_id,(n,ratio,category) in accepted.items()],reverse=True)
        if not scores or len(scores)>1 and scores[0][0]-scores[1][0]<4:
            return None
        n,ratio,unit_id,category=scores[0]
        return unit_id,category,ratio,(n-(scores[1][0] if len(scores)>1 else 0))/n

    def locate_references(self, frame, *, stop_check=None):
        """Find reviewed artwork in the army bar when scenery joins its border.

        Positions come from fresh, geometrically consistent portrait landmarks,
        never from the old slot. The resulting crops must still pass identity
        and quantity checks before they can authorize any input.
        """
        if not self.references: return []
        height,width=frame.shape[:2];top=round(height*.79)
        keys,descriptors=cv2.SIFT_create(nfeatures=2500).detectAndCompute(
            cv2.cvtColor(frame[top:],cv2.COLOR_BGR2GRAY),None)
        if descriptors is None or len(descriptors)<2:return []
        found={}
        for unit_id,kind,ref_keys,ref_desc,w,h in self.references:
            check_stop(stop_check)
            pairs=cv2.BFMatcher().knnMatch(ref_desc,descriptors,k=2)
            matches=[p[0] for p in pairs if len(p)==2 and p[0].distance<.65*p[1].distance]
            if len(matches)<8:continue
            source=np.float32([ref_keys[m.queryIdx].pt for m in matches])
            target=np.float32([keys[m.trainIdx].pt for m in matches])
            matrix,inliers=cv2.estimateAffinePartial2D(source,target,method=cv2.RANSAC,ransacReprojThreshold=2)
            if matrix is None or inliers is None:continue
            good=inliers.ravel().astype(bool);spread=np.ptp(source[good],axis=0)
            scale=float(np.hypot(matrix[0,0],matrix[1,0]))
            angle=float(np.degrees(np.arctan2(matrix[1,0],matrix[0,0])))
            quality=(good.mean()>=.65 or kind=='hero' and good.sum()>=16 and
                     good.mean()>=.55 and spread[0]>w*.25 and spread[1]>h*.25)
            if not (good.sum()>=8 and quality and .65<scale<1.5 and abs(angle)<3
                    and spread[0]>w*.20 and spread[1]>h*.15):continue
            corners=cv2.transform(np.float32([[[0,0],[w,0],[w,h],[0,h]]]),matrix)[0]
            x,y=np.floor(corners.min(axis=0)-2).astype(int)
            right,bottom=np.ceil(corners.max(axis=0)+2).astype(int)
            y+=top;bottom+=top
            if not (2<x<right<width-2 and top-5<y<bottom<=height+3
                    and width*.05<right-x<width*.10 and height*.12<bottom-y<height*.24):continue
            box=(int(x),int(y),int(right-x),int(min(height,bottom)-y))
            if unit_id not in found or good.sum()>found[unit_id][0]:
                found[unit_id]=(int(good.sum()),box)
        return [value[1] for value in found.values()]

    def identify(self, cell, *, kind=None, stop_check=None):
        reference = self.identify_reference(cell,kind=kind,stop_check=stop_check)
        if reference:
            return reference
        scores = []
        for unit_id, category, image, mask in self.templates:
            check_stop(stop_check)
            if kind is not None and kind != category:
                continue
            best,best_factor = 0.,.85
            for factor in (.60, .75, .85, 1., 1.15):
                scale = min(cell.shape[:2])*factor/max(image.shape[:2])
                size = tuple(max(1, round(n*scale)) for n in image.shape[1::-1])
                if size[0] >= cell.shape[1] or size[1] >= cell.shape[0] or min(size) < 12:
                    continue
                template = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
                alpha = cv2.resize(mask, size, interpolation=cv2.INTER_NEAREST)
                match = cv2.matchTemplate(cell, template, cv2.TM_CCORR_NORMED, mask=alpha)
                match[~np.isfinite(match)] = 0
                score = float(cv2.minMaxLoc(match)[1])
                if score > best:
                    best,best_factor = score,factor
            scores.append((best, unit_id, category, best_factor, image, mask))
        scores.sort(key=lambda entry:entry[0],reverse=True)
        if not scores:
            return None, 'unknown', 0., 0.
        refined = []
        for score,unit_id,category,factor,image,mask in scores[:5]:
            for trial in np.arange(max(.4,factor-.12),factor+.121,.02):
                check_stop(stop_check)
                scale = min(cell.shape[:2])*trial/max(image.shape[:2])
                size = tuple(max(1,round(n*scale)) for n in image.shape[1::-1])
                if size[0]>=cell.shape[1] or size[1]>=cell.shape[0]:
                    continue
                template = cv2.resize(image,size,interpolation=cv2.INTER_AREA)
                alpha = cv2.resize(mask,size,interpolation=cv2.INTER_NEAREST)
                values = cv2.matchTemplate(cell,template,cv2.TM_CCORR_NORMED,mask=alpha)
                values[~np.isfinite(values)] = 0
                score = max(score,float(cv2.minMaxLoc(values)[1]))
            refined.append((score,unit_id,category))
        refined.sort(reverse=True)
        score, unit_id, category = refined[0]
        margin = score - (refined[1][0] if len(refined) > 1 else 0)
        return (unit_id if score >= .94 and margin >= .025 else None,
                category if score >= .94 and margin >= .025 else 'unknown', score, margin)


def zero_glyph(glyph):
    """The game's block zero has one tall centered hole; six/nine do not."""
    h,w=glyph.shape
    if not .65<w/h<1.2: return False
    background=cv2.copyMakeBorder(255-glyph,1,1,1,1,cv2.BORDER_CONSTANT,value=255)
    _,_,stats,centers=cv2.connectedComponentsWithStats(background)
    holes=[(box,center) for box,center in zip(stats[1:],centers[1:])
           if box[0]>0 and box[1]>0 and box[0]+box[2]<w+2 and box[1]+box[3]<h+2 and box[4]>4]
    return (len(holes)==1 and holes[0][0][3]>=h*.42 and
            .40<(holes[0][1][1]-1)/h<.60 and .30<(holes[0][1][0]-1)/w<.70)


@lru_cache(maxsize=1)
def badge_digit_variants():
    path=Path(__file__).with_name('assets')/'badge_digits.npz'
    if not path.is_file():return {}
    with np.load(path,allow_pickle=False) as archive:return {key:archive[key] for key in archive.files}


def read_badge(cell, *, stop_check=None):
    """Read xN at the TOP of a card. Never mistake a bottom level for quantity."""
    if not shutil.which('tesseract') or not cell.size:
        return None
    crop = cell[:max(1, round(cell.shape[0]*.27))]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    white = cv2.inRange(hsv, (0,0,185), (180,60,255))
    _,_,stats,_ = cv2.connectedComponentsWithStats(white)
    components = [tuple(int(v) for v in s[:4]) for s in stats[1:]
                  if s[4]>8 and cell.shape[0]*.07 < s[3] < cell.shape[0]*.18]
    # Segment glyphs before OCR: the game's plain vertical 1s otherwise merge
    # into a single letter l, turning x11 into x1. An x-shaped prefix and shared
    # baseline are required, so hero levels cannot become army quantities.
    prefixes = []
    for x,y,w,h in components:
        # Two-digit starter quantities can center the x prefix in the header.
        # Its shape/baseline and top-only search establish the badge, not x.
        if not .65 < w/h < 1.3:
            continue
        glyph = cv2.resize(white[y:y+h,x:x+w],(20,20),interpolation=cv2.INTER_NEAREST)>0
        yy,xx = np.indices((20,20))
        ideal = (abs(xx-yy)<5)|(abs(xx+yy-19)<5)
        overlap = (glyph&ideal).sum()/max(1,(glyph|ideal).sum())
        if overlap>.65:
            prefixes.append((x,y,w,h))
    readings = []
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder)/'badge.png'
        for px,py,pw,ph in prefixes:
            digits = sorted([b for b in components if b[0]>=px+pw and
                             abs((b[1]+b[3])-(py+ph))<=ph*.3 and .75<b[3]/ph<1.5 and b[2]/b[3]<1.2])
            text,last = '',px+pw
            for x,y,w,h in digits[:3]:
                if x-last>ph*.5:
                    break
                check_stop(stop_check)
                glyph = white[y:y+h,x:x+w]
                if w/h<.52 and (glyph>0).mean()>.60:
                    digit = '1'
                elif zero_glyph(glyph):
                    digit = '0'
                else:
                    from coc_bot.upgrades.digits import read_digits
                    matched=read_digits(cv2.cvtColor(glyph,cv2.COLOR_GRAY2BGR),extra_templates=badge_digit_variants())
                    if matched is not None and re.fullmatch(r'\d',matched):
                        # The outlined 8 can be read as 3 by single-character
                        # OCR. Prefer the strict, margin-checked game-font bank.
                        text+=matched;last=x+w
                        continue
                    image=cv2.resize(255-glyph,None,fx=5,fy=5,interpolation=cv2.INTER_NEAREST)
                    image=cv2.copyMakeBorder(image,20,20,20,20,cv2.BORDER_CONSTANT,value=255)
                    cv2.imwrite(str(path),image)
                    try:
                        result=run_process(['tesseract',str(path),'stdout','--psm','13','-l','eng',
                                            '-c','tessedit_char_whitelist=0123456789'],
                                           text=True,timeout=1.5,stop_check=stop_check)
                    except ProcessStopped as exc:
                        raise AdbStopped('Army observation stopped') from exc
                    except (OSError,subprocess.TimeoutExpired):
                        text='';break
                    digit=(result.stdout or '').strip()
                if not re.fullmatch(r'\d',digit):
                    text='';break
                text+=digit;last=x+w
            if text and int(text)<=352:
                readings.append(int(text))
    # Different reads are ambiguity, not a reason to choose the larger number.
    return readings[0] if readings and len(set(readings)) == 1 else None


def card_boxes(frame, page):
    """Current UI layout gates only the search bands, not unit identity/order."""
    h,w = frame.shape[:2]
    outline_boxes=[]
    if page == 'army_confirmation':
        x0,y0,x1,y1 = round(w*.28),round(h*.25),round(w*.99),round(h*.69)
    elif page == 'battle':
        # Deployed heroes/siege rise above the normal row to show a health bar.
        x0,y0,x1,y1 = round(w*.05),round(h*.79),round(w*.99),round(h*.995)
    else:
        raise ValueError('Unsupported army page')
    if page == 'battle':
        # Opaque dark card outlines survive bright/blue scenery showing through
        # the army bar. Color components alone can merge the entire row into it.
        band=frame[y0:round(h*.998)]
        candidates=[]
        outlines=[(band.max(axis=2)<threshold).astype(np.uint8)*255 for threshold in (55,75,95,110)]
        # Selecting a hero reveals equipment chips attached above its dark
        # outline. Its closed white selection border still gives the actual
        # card bounds, independently of those extra chips.
        outlines.append(cv2.inRange(cv2.cvtColor(band,cv2.COLOR_BGR2HSV),
                                    (0,0,195),(180,65,255)))
        for dark in outlines:
            dark=cv2.morphologyEx(dark,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
            contours,_=cv2.findContours(dark,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                x,y,bw,bh=cv2.boundingRect(contour)
                if w*.06<bw<w*.09 and h*.13<bh<h*.22 and x>2 and x+bw<w-2:
                    candidates.append((x,y+y0,bw,bh))
        boxes=[]
        for box in sorted(candidates,key=lambda b:b[2]*b[3],reverse=True):
            x,y,bw,bh=box
            if any(max(0,min(x+bw,a+c)-max(x,a))*max(0,min(y+bh,b+d)-max(y,b)) /
                   min(bw*bh,c*d)>.65 for a,b,c,d in boxes):
                continue
            boxes.append(box)
        outline_boxes=boxes
    hsv = cv2.cvtColor(frame[y0:y1,x0:x1],cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv,(75,60,90),(165,255,255))
    mask = cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    contours,_ = cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    parts = [cv2.boundingRect(c) for c in contours]
    max_height = .22 if page == 'battle' else .20
    regular = [b for b in parts if w*.05 < b[2] < w*.10 and h*.12 < b[3] < h*max_height]
    width = float(np.median([b[2] for b in regular])) if regular else 0
    boxes = []
    for x,y,bw,bh in parts:
        if not h*.12 < bh < h*max_height or bw < w*.05:
            continue
        n = 1
        if bw > w*.10 and page == 'battle' and width:
            # Adjacent hero portraits can join above their cards. Split only
            # when the component agrees with the observed card width and gaps.
            gap = width*.095
            n = round((bw+gap)/(width+gap))
            if not 2 <= n <= 5 or abs(bw-(n*width+(n-1)*gap)) > width*.15:
                continue
        elif bw > w*.10:
            continue
        part_width = (bw-(n-1)*width*.095)/n if n>1 else bw
        for i in range(n):
            left = x0+x+round(i*(part_width+width*.095))-3
            top = y0+y-5
            right = min(w, left+round(part_width)+6)
            bottom = min(h,top+bh+10)
            if left <= 1 or right >= w-1:
                continue
            boxes.append((left,top,right-left,bottom-top))
    if page == 'army_confirmation':
        # Tall hero cards have a distinct layout. Detect their purple outlines
        # independently; do not infer the equipped hero's identity from its slot.
        left = frame[round(h*.25):round(h*.94),:round(w*.425)]
        mask = cv2.inRange(cv2.cvtColor(left,cv2.COLOR_BGR2HSV),(115,65,65),(165,255,255))
        mask = cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))
        contours,_ = cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            x,y,bw,bh = cv2.boundingRect(contour)
            if w*.07 < bw < w*.12 and bh > h*.5:
                boxes.append((x,round(h*.25)+y,bw,bh))
    # One broken dark outline must not hide a hero when the other cards have
    # complete outlines. Supplement with independently observed color shapes.
    for box in boxes:
        x,y,bw,bh=box
        if not any(max(0,min(x+bw,a+c)-max(x,a))*max(0,min(y+bh,b+d)-max(y,b)) /
                   min(bw*bh,c*d)>.65 for a,b,c,d in outline_boxes):
            outline_boxes.append(box)
    return sorted(outline_boxes)


def visible_card_boxes(frame, page, catalog, *, stop_check=None):
    boxes=card_boxes(frame,page)
    if page=='battle':
        for x,y,w,h in catalog.locate_references(frame,stop_check=stop_check):
            if not any(max(0,min(x+w,a+c)-max(x,a))*max(0,min(y+h,b+d)-max(y,b)) /
                       min(w*h,c*d)>.65 for a,b,c,d in boxes):
                boxes.append((x,y,w,h))
    return sorted(boxes)


def read_army(frame, page, catalog, *, stop_check=None):
    cards = []
    h,w = frame.shape[:2]
    for index, box in enumerate(visible_card_boxes(frame,page,catalog,stop_check=stop_check)):
        check_stop(stop_check)
        x,y,bw,bh = box
        cell = frame[y:y+bh,x:x+bw]
        if page == 'army_confirmation' and x < w*.43 and bh > h*.40:
            unit_id,kind,score,margin = None,'hero',0.,0.
            quantity,source = 1,'single hero card; availability unverified'
        else:
            hint = ('troop' if y < h*.46 else 'siege' if x>w*.77 else 'spell') if page=='army_confirmation' else None
            # Hero cards have different artwork from the unit icon pack. Do not
            # run every troop/spell template over each unknown hero portrait.
            purple=cv2.inRange(cv2.cvtColor(cell,cv2.COLOR_BGR2HSV),(115,60,80),(165,255,255))
            pet=cell[round(bh*.07):round(bh*.33),round(bw*.04):round(bw*.39)]
            neutral=cv2.inRange(cv2.cvtColor(pet,cv2.COLOR_BGR2HSV),(0,0,150),(180,55,255))
            hero_hint=page=='battle' and purple.mean()/255>.12 and neutral.mean()/255>.12
            reference=catalog.identify_reference(cell,stop_check=stop_check) if hero_hint else None
            if reference: unit_id,kind,score,margin=reference
            elif hero_hint: unit_id,kind,score,margin=None,'hero',0.,0.
            else: unit_id,kind,score,margin = catalog.identify(cell,kind=hint,stop_check=stop_check)
            quantity = read_badge(cell,stop_check=stop_check)
            source = 'xN badge' if quantity is not None else 'unreadable'
            if kind == 'hero' and quantity is None:
                quantity,source = 1,'identified hero card; availability checked during execution'
            if quantity is None and kind == 'siege':
                quantity,source = 1,'single siege card; availability unverified'
            if page == 'battle' and unit_id is None and quantity is None:
                purple = cv2.inRange(cv2.cvtColor(cell,cv2.COLOR_BGR2HSV),(115,60,80),(165,255,255))
                pet=cell[round(bh*.07):round(bh*.33),round(bw*.04):round(bw*.39)]
                neutral=cv2.inRange(cv2.cvtColor(pet,cv2.COLOR_BGR2HSV),(0,0,150),(180,55,255))
                if purple.mean()/255 > .12 and neutral.mean()/255>.12:
                    kind,quantity,source = 'hero',1,'single hero card; identity/availability unverified'
        cards.append(ArmyCard(f'card-{index}',box,unit_id,kind,quantity,score,margin,
                              quantity_source=source))
    return cards


def depleted_card(cell):
    """Grey, dark artwork with no readable count is depleted, never an OCR default."""
    h,w=cell.shape[:2]
    art=cell[round(h*.28):round(h*.76),round(w*.18):round(w*.82)]
    hsv=cv2.cvtColor(art,cv2.COLOR_BGR2HSV)
    return bool((hsv[:,:,1]<45).mean()>.85 and np.median(hsv[:,:,2])<145)


def resolve_live_card(frame, catalog, unit_id, *, stop_check=None):
    """Artwork references resolve position; OCR runs only for the requested card."""
    found=[]
    for index,box in enumerate(visible_card_boxes(frame,'battle',catalog,stop_check=stop_check)):
        check_stop(stop_check)
        x,y,w,h=box;cell=frame[y:y+h,x:x+w]
        match=catalog.identify_reference(cell,stop_check=stop_check)
        if not match or match[0]!=unit_id: continue
        _,kind,score,margin=match
        quantity=read_badge(cell,stop_check=stop_check)
        if quantity is None and depleted_card(cell): quantity=0
        elif quantity is None and kind in ('hero','siege'): quantity=1
        found.append(ArmyCard(f'card-{index}',box,unit_id,kind,quantity,score,margin))
    if len(found)!=1: raise ValueError('Unit is hidden or ambiguous: '+unit_id)
    return found[0]


def resolve_just_depleted(frame, catalog, before, *, stop_check=None, spent=1):
    """Check the last consumed card when its dark border no longer segments.

    A prior box is only a search area immediately after that unit's map tap.
    Current artwork must still identify the unit, be visibly depleted, and show
    x0 for stacked units. It never authorizes selecting a remembered position.
    """
    if type(spent) is not int or not 1<=spent<=5 or before.quantity!=spent or before.kind=='hero':
        raise ValueError('No verified empty card: '+before.unit_id)
    x,y,w,h=before.box;cell=frame[y:y+h,x:x+w]
    identity=catalog.identify_reference(cell,stop_check=stop_check)
    if not identity or identity[0]!=before.unit_id or not depleted_card(cell):
        raise ValueError('No verified empty card: '+before.unit_id)
    if before.kind!='siege':
        gray=cv2.cvtColor(cell,cv2.COLOR_BGR2GRAY)
        enhanced=cv2.normalize(gray,None,0,255,cv2.NORM_MINMAX)
        if read_badge(cv2.cvtColor(enhanced,cv2.COLOR_GRAY2BGR),stop_check=stop_check)!=0:
            raise ValueError('Empty quantity could not be read: '+before.unit_id)
    return replace(before,quantity=0,quantity_source='verified depleted artwork')


def agree_cards(first, second):
    """Require repeated identity/count and position agreement; never auto-confirm."""
    result = []
    for card in second:
        candidates = [old for old in first if old.unit_id == card.unit_id and old.kind == card.kind and
                      old.quantity == card.quantity and
                      max(abs(a-b) for a,b in zip(old.box,card.box)) <= 6]
        stable = len(candidates)==1 and card.unit_id is not None and card.quantity is not None
        result.append(replace(card,stable=stable))
    return result


def correct_cards(cards, corrections):
    """Corrections affect this observation only, never the user's existing army."""
    if not isinstance(corrections,list) or len(corrections)>len(cards):
        raise ValueError('Invalid army corrections')
    by_slot = {card.slot:card for card in cards}
    seen = set()
    for value in corrections:
        if not isinstance(value,dict) or set(value) != {'slot','unit_id','kind','quantity','confirmed'}:
            raise ValueError('Choose a unit, type, quantity and confirmation for each corrected card')
        slot = value['slot']
        if not isinstance(slot,str) or slot not in by_slot or slot in seen:
            raise ValueError('Unknown or duplicate card')
        seen.add(slot)
        unit_id,kind,q = value['unit_id'],value['kind'],value['quantity']
        if value['confirmed'] is False:
            if (unit_id not in (None,'') and (not isinstance(unit_id,str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}',unit_id)) or
                    kind not in ('troop','hero','siege','spell','unknown') or
                    (q is not None and (type(q) is not int or not 0<=q<=300 or kind in ('hero','siege') and q>1))):
                raise ValueError('Invalid unconfirmed card')
            by_slot[slot]=replace(by_slot[slot],unit_id=unit_id or None,kind=kind,quantity=q,confirmed=False)
            continue
        if (not isinstance(unit_id,str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}',unit_id) or
                kind not in ('troop','hero','siege','spell') or type(q) is not int or not 0<=q<=300 or
                type(value['confirmed']) is not bool or kind in ('hero','siege') and q>1):
            raise ValueError('Invalid unit identity, type or quantity')
        by_slot[slot] = replace(by_slot[slot],unit_id=unit_id,kind=kind,quantity=q,confirmed=value['confirmed'])
    return [by_slot[card.slot] for card in cards]
