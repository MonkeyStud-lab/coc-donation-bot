"""Place owned inventory in inactive copies using native acceptance receipts.

No resource payments occur here. Imported buildings retain their positions;
remaining owned structures use clear spare ground outside reserved footprints.
"""
import re
import time
from functools import lru_cache
from pathlib import Path
import cv2
import numpy as np
from loguru import logger
from coc_bot.accounts.store import read,write
from coc_bot.upgrades.vision import crop, text
from coc_bot.stop import interrupted_sleep


def signature(image):
    return cv2.resize(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),(32,32),interpolation=cv2.INTER_AREA)


def same_art(a,b):
    return bool(a is not None and b is not None and a['level']==b['level']
                and cv2.matchTemplate(np.array(a['art'],np.uint8),np.array(b['art'],np.uint8),cv2.TM_CCOEFF_NORMED)[0,0]>.96)


def rank_ground_targets(frame,mapping,targets,size):
    """Prefer space for the whole floor; this ranking never authorizes a drop."""
    from coc_bot.layouts.grid import pixels,SIZE
    resolution=12
    source=pixels(mapping,[(0,0),(SIZE,0),(0,SIZE)]).astype(np.float32)
    target=np.float32([[0,0],[SIZE*resolution,0],[0,SIZE*resolution]])
    hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
    grass=cv2.inRange(hsv,(23,45,105),(47,225,255))
    plane=cv2.warpAffine(grass,cv2.getAffineTransform(source,target),(SIZE*resolution,SIZE*resolution))
    integral=cv2.integral((plane>127).astype(np.uint8))
    def priority(point):
        low=np.rint((np.asarray(point)-size/2)*resolution).astype(int)
        high=low+size*resolution
        x,y=low;right,bottom=high
        quality=-1.
        if 0<=x<right<=SIZE*resolution and 0<=y<bottom<=SIZE*resolution:
            quality=(integral[bottom,right]-integral[y,right]-integral[bottom,x]+integral[y,x])/((right-x)*(bottom-y))
        # Quantize away tiny illumination differences before preferring the
        # edge. Keep every proposal; native overlap tests remain authoritative.
        return (-round(float(quality),1),-max(abs(point[0]-22),abs(point[1]-22)))
    return sorted(targets,key=priority)


@lru_cache(maxsize=1)
def inventory_digits():
    with np.load(Path(__file__).with_name('assets')/'inventory_level_digits.npz',allow_pickle=False) as archive:
        return {key:archive[key] for key in archive.files}


def inventory_level(reader,image):
    raw=reader.white_text(image)
    found=re.fullmatch(r'(?i)\s*level\s*(\d{1,2})\s*',raw)
    if found:return int(found[1]) if 1<=int(found[1])<=99 else None
    if re.fullmatch(r'(?i)\s*level\s*\S{1,2}\s*',raw) is None:return None
    # OCR commonly reads the native 11 as Il. Verify the actual suffix glyphs;
    # do not translate letters into guessed digits.
    white=cv2.inRange(cv2.cvtColor(image,cv2.COLOR_BGR2HSV),(0,0,190),(180,75,255))
    _,_,stats,_=cv2.connectedComponentsWithStats(white)
    parts=sorted((x,y,w,h) for x,y,w,h,area in stats[1:] if h>=image.shape[0]*.30 and area>5)
    if not 6<=len(parts)<=7:return None
    tail=parts[5:];x=min(v[0] for v in tail);y=min(v[1] for v in tail)
    right=max(a+c for a,b,c,d in tail);bottom=max(b+d for a,b,c,d in tail)
    from coc_bot.upgrades.digits import read_digits
    from coc_bot.progression.reader import building_level_digit_variants,red_digit_variants
    value=read_digits(cv2.cvtColor(white[y:bottom,x:right],cv2.COLOR_GRAY2BGR),
                      extra_templates=building_level_digit_variants()|red_digit_variants()|inventory_digits())
    return int(value) if value and value.isdigit() and len(value)==len(tail) and 1<=int(value)<=99 else None


def first_item(reader,frame):
    if not reader.editing(frame):return None
    border=crop(frame,(.003,.82,.10,.985))
    blue=cv2.inRange(cv2.cvtColor(border,cv2.COLOR_BGR2HSV),(80,55,90),(115,255,255)).mean()/255
    if blue<.25:return None
    label=crop(frame,(.009,.945,.099,.981))
    level=inventory_level(reader,label)
    if level is None:
        # Some owned buildings have no upgrade level. Accept only the captured
        # native hut artwork AND an actually blank caption, never failed OCR
        # of an ordinary level label.
        from pathlib import Path
        reference=cv2.imread(str(Path(__file__).with_name('assets')/'inventory_unleveled_hut.png'))
        white=cv2.inRange(cv2.cvtColor(label,cv2.COLOR_BGR2HSV),(0,0,190),(180,75,255))
        art=signature(crop(frame,(.007,.866,.099,.944)))
        if (np.count_nonzero(white)>10 or reference is None
            or cv2.matchTemplate(art,signature(reference),cv2.TM_CCOEFF_NORMED)[0,0]<.98):return None
    number=crop(frame,(.020,.807,.098,.853))
    white=cv2.inRange(cv2.cvtColor(number,cv2.COLOR_BGR2HSV),(0,0,220),(180,70,255))
    _,_,stats,_=cv2.connectedComponentsWithStats(white)
    # Storage artwork can reach this strip. Its thin reflected highlights are
    # not the solid white multiplication/count glyphs printed on a stack.
    def count_glyph(x,y,w,h,area):
        return h>=number.shape[0]*.35 and area>12 and area/(w*h)>=.20
    present=any(count_glyph(*part) for part in stats[1:])
    count=1
    if present:
        parts=sorted([(x,y,w,h) for x,y,w,h,area in stats[1:]
                      if count_glyph(x,y,w,h,area)])
        if not 2<=len(parts)<=4:return None
        from pathlib import Path
        reference=cv2.imread(str(Path(__file__).with_name('assets')/'inventory_multiplier.png'),cv2.IMREAD_GRAYSCALE)
        x,y,w,h=parts[0]
        if reference is None:return None
        prefix=cv2.resize(white[y:y+h,x:x+w],(reference.shape[1],reference.shape[0]),interpolation=cv2.INTER_NEAREST)>0
        expected=reference>0
        if (prefix&expected).sum()/max(1,(prefix|expected).sum())<.94:return None
        if parts[1][0]-(parts[0][0]+parts[0][2])>max(v[3] for v in parts)*.60:return None
        # The stack prefix is a separate multiplication glyph. Exclude it
        # before digit OCR rather than letting it turn 7 into an OCR letter.
        x=min(v[0] for v in parts[1:]);y=min(v[1] for v in parts[1:])
        right=max(a+c for a,b,c,d in parts[1:]);bottom=max(b+d for a,b,c,d in parts[1:])
        digits=cv2.cvtColor(white[y:bottom,x:right],cv2.COLOR_GRAY2BGR)
        from coc_bot.upgrades.digits import read_digits
        from coc_bot.progression.reader import red_digit_variants
        value=read_digits(digits,extra_templates=red_digit_variants())
        if value is None:value=text(255-digits,digits=True,stop=reader.stop)
        if not re.fullmatch(r'\d{1,3}',value) or not 2<=int(value)<=500:return None
        count=int(value)
    art=signature(crop(frame,(.007,.866,.099,.944)))
    wall=False
    from pathlib import Path
    for path in Path(__file__).with_name('assets').glob('inventory_wall_*.png'):
        reference=cv2.imread(str(path))
        if reference is not None and cv2.matchTemplate(art,signature(reference),cv2.TM_CCOEFF_NORMED)[0,0]>.98:
            wall=True;break
    return {'level':level,'count':count,'art':art.tolist(),'wall':wall,
            'point':(round(frame.shape[1]*.05),round(frame.shape[0]*.90))}


def tray_boxes(frame):
    h,w=frame.shape[:2]
    blue=cv2.inRange(cv2.cvtColor(frame[round(h*.82):],cv2.COLOR_BGR2HSV),
                     (80,55,90),(115,255,255))
    contours,_=cv2.findContours(blue,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    return sorted((x,y,bw,bh) for x,y,bw,bh in (cv2.boundingRect(c) for c in contours)
                  if x>0 and .09*w<bw<.115*w and bh>.11*h)


def tray_offsets(frame):
    # Short inventories centre themselves again whenever a card disappears.
    # Normalize each observed whole card to the reader's reference margin.
    return [max(0,x-round(frame.shape[1]*5/1853)) for x,y,bw,bh in tray_boxes(frame)] or [0]


def tray_start(frame):
    return bool(tray_boxes(frame))


def tray_item(reader,frame,slot=0):
    offsets=tray_offsets(frame)
    if slot>=len(offsets):return None
    offset=offsets[slot]
    if offset:
        shifted=frame.copy();top=round(frame.shape[0]*.80)
        shifted[top:,:frame.shape[1]-offset]=frame[top:,offset:]
        shifted[top:,frame.shape[1]-offset:]=0
    else:shifted=frame
    item=first_item(reader,shifted)
    if item is None:return None
    return item|{'slot':slot,'point':(item['point'][0]+offset,item['point'][1])}


def inventory_choice(reader,frame,pending):
    # The first card has a stable, observable count. Selecting farther cards
    # can scroll the native tray even during a valid drag. With the build zone
    # cleared, finish this card before advancing rather than paging mid-drag.
    item=tray_item(reader,frame)
    return item|{'measure_only':False,'anchor':item} if item else None


def planned_footprints(frame):
    """Four observed white sides, never an inferred missing edge."""
    h,w=frame.shape[:2];hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
    white=cv2.inRange(hsv,(0,0,155),(180,95,255))
    # Native planned edges are translucent over grass. Recover their local
    # brightness contrast; four long matching sides are still required below.
    highlights=cv2.morphologyEx(hsv[:,:,2],cv2.MORPH_TOPHAT,np.ones((9,9),np.uint8))
    white|=cv2.inRange(hsv,(0,0,175),(180,160,255)) & cv2.inRange(highlights,12,255)
    region=np.zeros_like(white);region[round(h*.10):round(h*.79),round(w*.12):round(w*.80)]=255
    white&=region
    diagonal=np.zeros_like(white)
    for sign in (-1,1):
        short=np.zeros((5,7),np.uint8);long=np.zeros((13,19),np.uint8)
        cv2.line(short,(0,0 if sign>0 else 4),(6,4 if sign>0 else 0),1,1)
        cv2.line(long,(0,0 if sign>0 else 12),(18,12 if sign>0 else 0),1,1)
        diagonal|=cv2.morphologyEx(cv2.morphologyEx(white,cv2.MORPH_CLOSE,short),cv2.MORPH_OPEN,long)
    white=diagonal
    lines=cv2.HoughLinesP(white,1,np.pi/360,22,minLineLength=round(w*.018),maxLineGap=4)
    if lines is None:return []
    eligible=[v for v in lines.reshape(-1,4) if v[2]!=v[0] and .60<abs((v[3]-v[1])/(v[2]-v[0]))<.90]
    if len(eligible)<4:return []
    slope=float(np.median([abs((y2-y1)/(x2-x1)) for x1,y1,x2,y2 in eligible]))
    groups={1:[],-1:[]}
    for x1,y1,x2,y2 in eligible:
        a=np.array([x1+y1/slope,-x1+y1/slope]);b=np.array([x2+y2/slope,-x2+y2/slope])
        sign=1 if (y2-y1)/(x2-x1)>0 else -1
        fixed,along=(1,0) if sign==1 else (0,1)
        value=float((a[fixed]+b[fixed])/2);lo,hi=sorted((a[along],b[along]))
        match=next((v for v in groups[sign] if abs(v[0]-value)<5),None)
        if match:match[1]=min(match[1],lo);match[2]=max(match[2],hi)
        else:groups[sign].append([value,float(lo),float(hi)])
    nearby=cv2.dilate(white,np.ones((5,5),np.uint8))
    grass=cv2.inRange(hsv,(23,45,105),(47,225,255));result=[]
    positive=sorted(groups[1]);negative=sorted(groups[-1])
    for index,(v0,lo0,hi0) in enumerate(positive):
      for v1,lo1,hi1 in positive[index+1:]:
        side=v1-v0
        if not 45<side<260:continue
        left,right=max(lo0,lo1)-15,min(hi0,hi1)+15
        others=[u for u,lo,hi in negative if left<=u<=right and lo<=v0+15 and hi>=v1-15]
        for k,u0 in enumerate(others):
          for u1 in others[k+1:]:
            if not .90<(u1-u0)/side<1.10:continue
            points=np.rint([((u-v)/2,slope*(u+v)/2) for u,v in
                            ((u0,v0),(u1,v0),(u1,v1),(u0,v1))]).astype(np.int32)
            if (points[:,0].min()<w*.12 or points[:,0].max()>w*.80
                or points[:,1].min()<h*.10 or points[:,1].max()>h*.79):continue
            valid=True
            for a,b in zip(points,np.roll(points,-1,axis=0)):
                samples=np.rint(np.linspace(a,b,50)).astype(int)
                if (nearby[samples[:,1],samples[:,0]]>0).mean()<.86:valid=False;break
            if not valid:continue
            inside=np.zeros_like(white);cv2.fillConvexPoly(inside,points,255)
            if (grass[inside>0]>0).mean()<.65:continue
            center=points.mean(axis=0)
            if any(np.linalg.norm(center-np.mean(p,axis=0))<w*.012 for p in result):continue
            result.append(points.tolist())
    return result


def reserved_mask(frame):
    """Exclude closed white planned footprints, plus all long white map edges."""
    h,w=frame.shape[:2]
    hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
    white=cv2.inRange(hsv,(0,0,155),(180,95,255))
    region=np.zeros_like(white);region[round(h*.12):round(h*.79),round(w*.12):round(w*.80)]=255
    white&=region
    edges=np.zeros_like(white)
    lines=cv2.HoughLinesP(white,1,np.pi/360,threshold=24,minLineLength=round(w*.018),maxLineGap=5)
    if lines is not None:
        for x1,y1,x2,y2 in lines.reshape(-1,4):
            if x1!=x2 and .50<abs((y2-y1)/(x2-x1))<1.05:cv2.line(edges,(x1,y1),(x2,y2),255,3)
    for polygon in planned_footprints(frame):cv2.fillConvexPoly(edges,np.asarray(polygon,np.int32),255)
    return edges


def spare_ground(frame,*,limit=18,wall=False):
    h,w=frame.shape[:2];blocked=reserved_mask(frame)
    hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
    grass=cv2.inRange(hsv,(23,45,105),(47,225,255))
    gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
    radius=max(12,round(w*(.0085 if wall else .030)));points=[]
    for y in np.linspace(h*.72,h*.20,30 if wall else 15):
        for x in np.linspace(w*.19,w*.75,40 if wall else 20):
            x,y=round(x),round(y)
            box=grass[y-radius:y+radius,x-radius:x+radius]
            if box.size==0 or box.mean()/255<.97:continue
            if blocked[y-radius:y+radius,x-radius:x+radius].any():continue
            patch=gray[y-radius:y+radius,x-radius:x+radius]
            if patch.std()>13:continue
            if any(np.linalg.norm(np.array([x,y])-p)<radius*1.3 for p in points):continue
            points.append((x,y))
    return points[:limit]


class InventoryPlacer:
    def __init__(self,importer):self.i=importer;self.s=importer.s

    def reset_inventory(self):
        """Prove the left limit by an unchanged full card after a tray swipe.

        Native chevrons fade out even on a scrolled page. The gesture stays
        below every map/control action, inside the inventory's bottom edge.
        """
        for _ in range(12):
            if self.i.stop():return False
            frame=self.s.capture.screenshot()
            if not self.i.reader.editing(frame):return False
            if self.i.reader.ready_save(frame) and self.i.reader.ready_save(self.s.capture.screenshot()):return True
            before=tray_item(self.i.reader,frame) if tray_start(frame) else None
            h,w=frame.shape[:2]
            if self.i.stop():return False
            self.s.input.swipe(round(w*.17),round(h*.975),round(w*.83),round(h*.975),450)
            if interrupted_sleep(.20,self.i.stop):return False
            fresh=self.s.capture.screenshot()
            if not self.i.reader.editing(fresh):return False
            after=tray_item(self.i.reader,fresh) if tray_start(fresh) else None
            if same_art(before,after) and before['count']==after['count']:
                again=tray_item(self.i.reader,self.s.capture.screenshot())
                if same_art(after,again) and after['count']==again['count']:return True
        return False

    def check_owner(self):
        state=read(self.i.path,{});p=state.get('pending',{})
        if (p.get('account')!=self.s.config.account_tag or p.get('phase')!='copying_to_empty_slot'
            or type(p.get('slot')) is not int or type(p.get('original_slot')) is not int
            or not 0<=p['slot']<3 or not 0<=p['original_slot']<3 or p['slot']==p['original_slot']
            or not p.get('backup') or p.get('placement')):
            raise ValueError('Inventory placement requires an owned, backed-up inactive copy without an uncertain move')
        if self.s.config.dry_run:raise ValueError('Layout edits are disabled in practice mode')
        return state,p

    def one(self):
        state,pending=self.check_owner()
        if self.i.stop():return {'status':'stopped'}
        return self._native_one(state,pending)

    def _native_one(self,state,pending):
        from coc_bot.adb.multitouch import Multitouch
        from coc_bot.layouts.grid import camera,pixels,tiles,outline,safe_preview,reserved_tiles,SIZE
        if pending.get('placement_cache_policy')!='native-red-world-v1':
            for group in pending.get('failed_ground',[]):group['tiles']=[]
            pending['placement_cache_policy']='native-red-world-v1';write(self.i.path,state)
        if not self.reset_inventory():return {'status':'changed','message':'Inventory start could not be verified'}
        frame=self.s.capture.screenshot();before=inventory_choice(self.i.reader,frame,pending)
        if before is None:return {'status':'unreadable_inventory'}
        fresh=self.s.capture.screenshot();again=tray_item(self.i.reader,fresh,before['slot'])
        if not same_art(before,again) or before['count']!=again['count']:
            folder=self.s.config.data_dir/'layouts';folder.mkdir(parents=True,exist_ok=True)
            cv2.imwrite(str(folder/'changed-before.png'),frame);cv2.imwrite(str(folder/'changed-after.png'),fresh)
            score=(float(cv2.matchTemplate(np.asarray(before['art'],np.uint8),np.asarray(again['art'],np.uint8),cv2.TM_CCOEFF_NORMED)[0,0]) if again else None)
            return {'status':'changed','message':'First card changed before pickup','before':{k:before[k] for k in ('level','count')},'after':{k:again[k] for k in ('level','count')} if again else None,'similarity':score}
        mapping=camera(fresh,self.i.stop)
        for _ in range(3):
            if mapping['registered'] or self.i.stop():break
            if interrupted_sleep(.25,self.i.stop):return {'status':'stopped'}
            fresh=self.s.capture.screenshot();again=tray_item(self.i.reader,fresh,before['slot'])
            if not same_art(before,again) or before['count']!=again['count']:return {'status':'changed'}
            mapping=camera(fresh,self.i.stop)
        if not mapping['registered']:
            cv2.imwrite(str(self.s.config.data_dir/'layouts/last-geometry.png'),fresh)
            return {'status':'needs_geometry','message':mapping['reason']}
        blocked=reserved_tiles(fresh,mapping)
        groups=pending.setdefault('failed_ground',[])
        learned=next((g for g in groups if same_art(before,g)),None)
        if learned is None:
            learned={'level':before['level'],'art':before['art'],'tiles':[]};groups.append(learned)
        def planned_overlap(target):
            n=learned.get('size',1)
            if n<=1:return False
            a,b=np.rint(np.asarray(target)-n/2).astype(int)
            return a<0 or b<0 or a+n>44 or b+n>44 or blocked[a:a+n,b:b+n].any()
        # Only clear terrain is proposed. The native green footprint makes the
        # final decision after selection and any automatic camera movement.
        targets=[]
        hsv=cv2.cvtColor(fresh,cv2.COLOR_BGR2HSV)
        grass=cv2.inRange(hsv,(23,45,105),(47,225,255))
        for u in range(SIZE):
            for v in range(SIZE):
                if blocked[u,v]:continue
                if [u+.5,v+.5] in learned['tiles']:continue
                if planned_overlap((u+.5,v+.5)):continue
                x,y=np.rint(pixels(mapping,[(u+.5,v+.5)])[0]).astype(int)
                if not fresh.shape[1]*.14<x<fresh.shape[1]*.77 or not fresh.shape[0]*.15<y<fresh.shape[0]*.72:continue
                if (grass[y-8:y+9,x-8:x+9]>0).mean()<.95:continue
                targets.append((u+.5,v+.5))
        # Fill peripheral spare ground first; retain the imported defensive core.
        targets=rank_ground_targets(fresh,mapping,targets,learned.get('size',1 if before['wall'] else 3))
        if not targets:
            folder=self.s.config.data_dir/'layouts';folder.mkdir(parents=True,exist_ok=True)
            cv2.imwrite(str(folder/'last-placement.png'),fresh)
            return {'status':'no_spare_ground','reserved_tiles':int(blocked.sum())}
        pending['placement']={'phase':'holding','before':before,'at':time.time()}
        write(self.i.path,state)
        if self.i.stop():return {'status':'stopped'}
        accepted=None;last=None;previous=before['point'];measured=False
        grab_offset=np.array([0.,30.]);grab_observed=False
        observations=[]
        with Multitouch(self.s.client,(frame.shape[1],frame.shape[0])) as touch:
            touch._send(0,0,previous)
            if interrupted_sleep(.20,self.i.stop):return {'status':'stopped'}
            # A diagonal from a right-hand card starts as a horizontal swipe
            # INSIDE the tray. The game then scrolls instead of picking it up.
            # Establish the native drag by lifting straight out of the tray.
            lifted=(previous[0],round(frame.shape[0]*.77))
            for step in range(1,9):
                touch._send(2,0,(previous[0],round(previous[1]+(lifted[1]-previous[1])*step/8)))
                if interrupted_sleep(.025,self.i.stop):return {'status':'stopped'}
            previous=lifted
            attempts=0
            for target in targets:
                if self.i.stop():return {'status':'stopped'}
                if planned_overlap(target):continue
                if attempts>=50:break
                index=attempts;attempts+=1
                pixel=pixels(mapping,[target])[0]
                destination=tuple(np.rint(pixel+grab_offset).astype(int).tolist())
                if not frame.shape[1]*.13<destination[0]<frame.shape[1]*.79 or not frame.shape[0]*.14<destination[1]<frame.shape[0]*.78:continue
                for step in range(1,9):
                    point=tuple(round(a+(b-a)*step/8) for a,b in zip(previous,destination))
                    touch._send(2,0,point)
                    if interrupted_sleep(.018,self.i.stop):return {'status':'stopped'}
                previous=destination
                if interrupted_sleep(.18,self.i.stop):return {'status':'stopped'}
                current=self.s.capture.screenshot()
                if not self.i.reader.editing(current):return {'status':'needs_review'}
                # Selecting from inventory can change the camera scale.
                if index==0:
                    updated=camera(current,self.i.stop)
                    if not updated['registered']:return {'status':'needs_geometry'}
                    mapping=updated
                value=outline(current,destination,mapping,wall=before['wall']);last=value
                observations.append({'pointer':destination,'outline':value})
                if value:
                    # A red floor still proves its dimensions. Use them to
                    # prune impossible edge cells; red NEVER authorizes UP.
                    learned.setdefault('size',value['size'])
                if value and not grab_observed:
                    # Native pickup anchors differ by building. Proposals must
                    # position its floor, not assume the finger is its centre.
                    grab_offset=np.asarray(destination)-np.asarray(value['center'])
                    grab_observed=True
                if index==0:
                    folder=self.s.config.data_dir/'layouts';folder.mkdir(parents=True,exist_ok=True)
                    cv2.imwrite(str(folder/'last-held.png'),current)
                if before['measure_only'] and value:
                    confirmation=outline(self.s.capture.screenshot(),destination,mapping,wall=before['wall'])
                    if confirmation and all(confirmation.get(k)==value[k] for k in ('colour','size','tile_center')):
                        learned['size']=value['size'];pending['placement']['phase']='returning_to_inventory'
                        write(self.i.path,state)
                        # Returning an owned item to the blue tray is a cancel,
                        # with an unchanged-count receipt required below.
                        for step in range(1,13):
                            touch._send(2,0,tuple(round(a+(b-a)*step/12) for a,b in zip(previous,before['point'])))
                            if interrupted_sleep(.02,self.i.stop):return {'status':'stopped'}
                        touch.release_fingers()
                        if interrupted_sleep(.12,self.i.stop):return {'status':'stopped'}
                        self.s.capture.screenshot();measured=True;break
                if not safe_preview(value):
                    # Missing/unstable rendering is not an occupied tile. The
                    # initial pickup can also shift the camera/grab anchor;
                    # cache red only when it actually refers to this target.
                    if (value and value['colour']=='red'
                        and np.linalg.norm(np.asarray(value['tile_center'])-target)<=.8):
                        learned['tiles']=(learned['tiles']+[list(target)])[-256:]
                    continue
                learned['size']=value['size']
                n=value['size'];u,v=value['tile_center']
                a,b=round(u-n/2),round(v-n/2)
                if blocked[a:a+n,b:b+n].any():
                    continue
                # Two independent fresh native outlines must agree before UP.
                confirmation=outline(self.s.capture.screenshot(),destination,mapping,wall=before['wall'])
                if not confirmation or any(confirmation.get(k)!=value[k] for k in ('colour','size','tile_center')):
                    continue
                accepted=value;pending['placement'].update(phase='releasing',native=value)
                write(self.i.path,state)
                if self.i.stop():return {'status':'stopped'}
                touch.release_fingers()
                # Keep the touch server alive until a rendered frame follows
                # UP. Immediate transport teardown can cancel an otherwise
                # valid drop before Android processes the release.
                if interrupted_sleep(.12,self.i.stop):return {'status':'stopped'}
                self.s.capture.screenshot()
                break
            if accepted is None and not measured:
                # Never release an unreadable floor on the last proposed legal
                # tile. Move well beyond a registered boundary to cancel it,
                # then require an unchanged inventory receipt below. If that
                # receipt is unknown, the durable move intent is retained.
                outside=[(u,v) for u in (-4,48) for v in range(8,37,4)]
                outside += [(u,v) for v in (-4,48) for u in range(8,37,4)]
                options=[]
                for uv in outside:
                    x,y=pixels(mapping,[uv])[0];point=(round(x),round(y+30))
                    if frame.shape[1]*.14<point[0]<frame.shape[1]*.77 and frame.shape[0]*.15<point[1]<frame.shape[0]*.73:
                        options.append(point)
                if options:
                    destination=min(options,key=lambda p:np.linalg.norm(np.array(p)-previous))
                    for step in range(1,13):
                        touch._send(2,0,tuple(round(a+(b-a)*step/12) for a,b in zip(previous,destination)))
                        if interrupted_sleep(.02,self.i.stop):return {'status':'stopped'}
                    if interrupted_sleep(.25,self.i.stop):return {'status':'stopped'}
                    observations.append({'cancel_outside':destination})
        if interrupted_sleep(.3,self.i.stop):return {'status':'stopped'}
        current=self.s.capture.screenshot()
        if not self.i.reader.editing(current):return {'status':'needs_review'}
        self.s.input.tap(round(frame.shape[1]*.04),round(frame.shape[0]*.67),jitter=0)
        if interrupted_sleep(.2,self.i.stop):return {'status':'stopped'}
        if before['slot'] and not self.reset_inventory():return {'status':'needs_review','message':'Inventory page did not settle after drag'}
        a_frame=self.s.capture.screenshot();b_frame=self.s.capture.screenshot()
        a=tray_item(self.i.reader,a_frame,before['slot']);b=tray_item(self.i.reader,b_frame,before['slot'])
        folder=self.s.config.data_dir/'layouts';folder.mkdir(parents=True,exist_ok=True)
        cv2.imwrite(str(folder/'last-receipt.png'),b_frame)
        write(folder/'placement-receipt.json',{'before':{k:v for k,v in before.items() if k!='art'},
              'first':{k:v for k,v in a.items() if k!='art'} if a else None,
              'second':{k:v for k,v in b.items() if k!='art'} if b else None,
              'same_before_first':same_art(before,a),'same_first_second':same_art(a,b),
              'accepted':accepted,'observations':observations})
        complete=self.i.reader.ready_save(a_frame) and self.i.reader.ready_save(b_frame)
        changed=(same_art(a,b) and a['count']==b['count'] and
                 (same_art(before,a) and a['count']==before['count']-1 or
                  before['count']==1 and not same_art(before,a)))
        if accepted and before['count']==1 and before['slot']>0 and a is None and b is None:
            left=tray_item(self.i.reader,a_frame);right=tray_item(self.i.reader,b_frame)
            anchor=before['anchor']
            changed=(same_art(anchor,left) and same_art(left,right)
                     and anchor['count']==left['count']==right['count'])
        if accepted and (changed or before['count']==1 and complete):
            pending.setdefault('placements',[]).append(pending.pop('placement')|{'phase':'confirmed'})
            write(self.i.path,state)
            logger.info('Layout placement confirmed: level {}, remaining stack {}',before['level'],a['count'] if a else 0)
            return {'status':'placed','native':accepted,'native_complete':bool(complete)}
        if same_art(before,a) and same_art(a,b) and a['count']==b['count']==before['count']:
            pending.pop('placement');write(self.i.path,state)
            if measured:
                logger.info('Layout inventory measured: level {}, slot {}, footprint {}x{}',before['level'],before['slot'],learned['size'],learned['size'])
                return {'status':'probed','size':learned['size']}
            return {'status':'no_spare_ground' if not accepted else 'rejected'}
        return {'status':'needs_review','message':'Native inventory receipt is uncertain; no repeated drag'}
