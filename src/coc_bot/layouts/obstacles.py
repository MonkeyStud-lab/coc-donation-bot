"""Clear resource-priced import blockers, with a receipt outside the editor."""
import time
import uuid
import re
from difflib import SequenceMatcher
import cv2
import numpy as np
from coc_bot.accounts.store import read,write
from coc_bot.upgrades.vision import crop,compact,text,currency,resource_amount
from coc_bot.progression.reader import balance_amount
from coc_bot.progression.space import home_gems,home_builder_visible,ORDINARY,removal_digit_variants
from coc_bot.vision.battle_menu import home_build_control_visible
from coc_bot.attack.camera import compare_camera
from coc_bot.stop import interrupted_sleep


def obstacle_key(name):
    value=compact(name)
    # Inspected small caption glyph variants only; never apply to prices.
    return {'truwk':'trunk','stowe':'stone','baish':'bush'}.get(value,value)


def same_removal(first,second,*,seasonal):
    if not first or not second:return False
    if any(first[k]!=second[k] for k in ('cost','currency')):return False
    if np.linalg.norm(np.array(first['point'])-second['point'])>3:return False
    # Seasonal clearing already permits any resource-priced obstacle. Its
    # floating caption OCR is descriptive, not authority to spend. Ordinary-
    # only policy still needs the same complete known obstacle identity.
    return seasonal or obstacle_key(first['name'])==obstacle_key(second['name'])


def obstacle_name(frame,target,stop=None):
    """Isolate the tiny floating caption from white stones and decorations."""
    h,w=frame.shape[:2];x,y=target
    a=max(0,round(x-w*.16));b=max(0,round(y-h*.12))
    region=frame[b:max(b+1,round(y-h*.018)),a:min(w,round(x+w*.16))]
    white=cv2.inRange(cv2.cvtColor(region,cv2.COLOR_BGR2HSV),(0,0,210),(180,95,255))
    _,_,stats,_=cv2.connectedComponentsWithStats(white)
    groups=[]
    for left,top,bw,bh,area in stats[1:]:
        if not 4*h/1048<=bh<=23*h/1048 or bw>w*.045 or area<5:continue
        center=top+bh/2
        group=next((g for g in groups if abs(g[0]-center)<4*h/1048),None)
        if group:group[1].append((left,top,bw,bh))
        else:groups.append([center,[(left,top,bw,bh)]])
    lines=[]
    for _,parts in groups:
        parts.sort();runs=[];current=[]
        for part in parts:
            if current and part[0]-(current[-1][0]+current[-1][2])>12*w/1853:
                runs.append(current);current=[]
            current.append(part)
        if current:runs.append(current)
        for run in runs:
            if len(run)<3:continue
            left=min(p[0] for p in run);top=min(p[1] for p in run)
            right=max(p[0]+p[2] for p in run);bottom=max(p[1]+p[3] for p in run)
            if abs(a+(left+right)/2-x)>w*.035:continue
            lines.append((len(run),left,top,right,bottom))
    if not lines:return ''
    _,left,top,right,bottom=max(lines)
    label=cv2.copyMakeBorder(white[top:bottom,left:right],3,3,3,3,cv2.BORDER_CONSTANT,value=0)
    return text(255-label,stop=stop).strip()


def home_resources(frame,stop=None):
    if (stop and stop()) or not home_build_control_visible(frame) or not home_builder_visible(frame):return None
    gems=home_gems(frame,stop)
    balances={k:balance_amount(crop(frame,b),stop) for k,b in {
        'gold':(.82,.035,.958,.072),'elixir':(.82,.103,.958,.14)}.items()}
    if type(gems) is not int or any(type(v) is not int for v in balances.values()):return None
    return {'home_builder_visible':True,'gems':gems,'balances':balances}


def footprints(frame):
    from coc_bot.layouts.placement import planned_footprints
    return planned_footprints(frame)


def candidates(frame,polygons,*,lower_map=False,limit=30):
    h,w=frame.shape[:2];inside=np.zeros((h,w),np.uint8)
    for polygon in polygons:cv2.fillConvexPoly(inside,np.asarray(polygon,np.int32),255)
    hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
    ground=cv2.inRange(hsv,(24,45,125),(47,225,255))
    objects=cv2.bitwise_and(255-ground,inside)
    # Bright tree foliage can share the grass hue. Its high-contrast sprite
    # boundary must remain a candidate even when its interior looks like ground.
    edges=cv2.bitwise_and(cv2.Canny(cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY),80,160),inside)
    objects=cv2.morphologyEx(objects,cv2.MORPH_CLOSE,np.ones((7,7),np.uint8))
    objects=cv2.morphologyEx(objects,cv2.MORPH_OPEN,np.ones((3,3),np.uint8))
    contours,_=cv2.findContours(objects,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    extra,_=cv2.findContours(cv2.morphologyEx(edges,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8)),
                             cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    # Grey rock facets can share the grass hue with much less saturation.
    # Keep their compact sprite separate from the broad grass/edge masks.
    neutral=cv2.inRange(hsv,(0,0,45),(180,80,225)) & inside
    neutral=cv2.morphologyEx(cv2.morphologyEx(neutral,cv2.MORPH_CLOSE,np.ones((5,5),np.uint8)),cv2.MORPH_OPEN,np.ones((3,3),np.uint8))
    stones,_=cv2.findContours(neutral,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    result=[]
    for contour in sorted(stones,key=cv2.contourArea,reverse=True)+sorted(contours,key=cv2.contourArea,reverse=True)+sorted(extra,key=cv2.contourArea,reverse=True):
        if not 60<cv2.contourArea(contour)<w*h*.012:continue
        x,y,bw,bh=cv2.boundingRect(contour);point=(x+bw//2,y+bh//2)
        if bw>w*.12 or bh>h*.17:continue
        # Selecting an obstacle opens payment/finish controls below .60h.
        # Never let another candidate tap hit those controls from a stale list.
        # Lower map tiles are surveyed after a camera pan instead.
        # Only the automatic runner's positive native no-selection gate may
        # enable the lower canvas. Other callers retain the conservative area.
        bottom=.77 if lower_map else .58
        if not w*.14<point[0]<w*.76 or not h*.14<point[1]<h*bottom:continue
        foot=(x+bw//2,y+bh-1)
        if any(cv2.pointPolygonTest(np.asarray(p,np.float32),point,False)>=0 and
               cv2.pointPolygonTest(np.asarray(p,np.float32),foot,False)>=0 for p in polygons):
            if not any(np.linalg.norm(np.array(point)-v)<10 for v in result):result.append(point)
    return result if limit is None else result[:limit]


def selected(reader,frame,target,*,seasonal=False):
    if not reader.editing(frame):return None
    # A shovel/stash action can shift the resource Remove tile horizontally.
    # Locate its exact native word, then read only that tile's price and icon.
    point=reader.find(frame,'remove_word',(.22,.70,.78,.78),threshold=.97)
    if point is None:return None
    h,w=frame.shape[:2];x,y=point;sx=w/1853;sy=h/1048
    def tile(a,b,c,d):
        return frame[round(y+b*sy):round(y+d*sy),round(x+a*sx):round(x+c*sx)]
    # The exact full-word native template above is the label proof. Beige
    # button backgrounds pass the general white-text mask and can turn a
    # perfectly matched Remove label into unstable OCR gibberish.
    price_image=tile(-78,-122,78,-86)
    cost=resource_amount(price_image,reader.stop)
    # Beige seasonal tiles can join the general white-text mask. The same
    # inspected neutral-lettering fallback used for Home removal reads these
    # prices without guessing digits; conflicting readings block payment.
    from coc_bot.upgrades.digits import read_digits
    white=cv2.inRange(cv2.cvtColor(price_image,cv2.COLOR_BGR2HSV),(0,0,235),(180,30,255))
    alternate=read_digits(cv2.cvtColor(white,cv2.COLOR_GRAY2BGR),extra_templates=removal_digit_variants())
    alternate=int(alternate) if alternate and re.fullmatch(r'\d{1,5}',alternate) else None
    if cost is not None and alternate is not None and cost!=alternate:return None
    if cost is None:cost=alternate
    icon=tile(-36,-77,36,-33)
    if cv2.inRange(cv2.cvtColor(icon,cv2.COLOR_BGR2HSV),(35,100,150),(90,255,255)).mean()/255>.07:return None
    resource=currency(icon)
    if type(cost) is not int or not 0<cost<=50_000 or resource not in ('gold','elixir'):return None
    if target[1]<h*.10:return None
    name=obstacle_name(frame,target,reader.stop)
    if not name or len(name)>80 or not compact(name):return None
    if not seasonal and obstacle_key(name) not in ORDINARY:return None
    return {'name':name,'cost':cost,'currency':resource,'point':(x,round(y-38*sy))}


def outside_selected_tree(reader,frame,target):
    """Exclude a positively identified border tree, never authorize removal.

    A click on grass near the boundary can select a nearby outside tree. The
    inspected caption-and-sprite template supplies its actual ground anchor;
    the click position alone cannot prove that this object is in the village.
    Unknown artwork remains unreadable rather than being declared outside.
    """
    if not reader.editing(frame):return False
    if reader.find(frame,'remove_word',(.22,.70,.78,.78),threshold=.97) is None:return False
    h,w=frame.shape[:2];x,y=target
    point=reader.find(frame,'selected_border_tree',
        (max(0,x/w-.06),max(0,y/h-.09),min(1,x/w+.06),min(1,y/h+.09)),threshold=.99)
    if point is None:return False
    from coc_bot.layouts.grid import camera,tiles
    mapping=camera(frame,reader.stop or (lambda:False))
    if not mapping['registered']:return False
    # Asset centre to the inspected trunk/ground anchor, with one tile of
    # registration tolerance beyond the legal boundary before exclusion.
    uv=tiles(mapping,[(point[0],point[1]+25*h/1048)])[0]
    return bool(np.any(uv < -1) or np.any(uv > 45))


def removal_started(reader,frame,target,name):
    """The native demolition hammer/Cancel tile, never the editor's red Cancel."""
    if not reader.editing(frame):return False
    if reader.find(frame,'removal_cancel',(.22,.60,.78,.79),threshold=.98) is None:return False
    observed=obstacle_key(obstacle_name(frame,target,reader.stop));expected=obstacle_key(name)
    # This caption only binds an already-authorized payment to its native
    # in-progress control; it never authorizes a cost or currency. Small OCR
    # errors such as the inspected "@runk" must not hide the matching action.
    return observed==expected or (min(len(observed),len(expected))>=3
                                  and SequenceMatcher(None,observed,expected).ratio()>=.75)


def remove_selected(importer,target):
    s=importer.s;config=s.config
    state=read(importer.path,{});p=state.get('pending',{})
    proof=p.get('home_resources');polygons=p.get('blocked_footprints',[])
    if (p.get('phase')!='surveying_obstacles' or p.get('account')!=config.account_tag
        or p.get('slot')==p.get('original_slot') or not p.get('survey_collected_at')
        or not config.progression_clear_obstacles or not proof or time.time()-proof.get('at',0)>180):
        return {'status':'blocked','message':'No current, account-owned resource proof for obstacle removal'}
    if p.get('footprint_source') not in ('reviewed_native_import','registered_default_build_zone_v1'):
        return {'status':'blocked','message':'Import blocker geometry still needs a reviewed reference'}
    if not any(cv2.pointPolygonTest(np.asarray(v,np.float32),tuple(target),False)>=0 for v in polygons):
        return {'status':'blocked','message':'Obstacle is outside the verified build zone'}
    if importer.stop():return {'status':'stopped'}
    f=s.capture.screenshot();item=selected(importer.reader,f,target,seasonal=config.progression_clear_seasonal_obstacles)
    if item is None:return {'status':'not_obstacle'}
    second=selected(importer.reader,s.capture.screenshot(),target,seasonal=config.progression_clear_seasonal_obstacles)
    if not same_removal(item,second,seasonal=config.progression_clear_seasonal_obstacles):
        return {'status':'changed','message':'Obstacle selection did not agree on two fresh frames'}
    resource=item['currency'];reserve=config.upgrade_gold_reserve if resource=='gold' else config.upgrade_elixir_reserve
    if proof['balances'][resource]-item['cost']<reserve:return {'status':'waiting'}
    ledger_path=config.data_dir/'upgrades/state.json';ledger=read(ledger_path,{})
    if ledger.get('pending') or p.get('payment'):return {'status':'needs_review'}
    payment=item|{'kind':'obstacle','phase':'confirming','operation':uuid.uuid4().hex,
                  'balance_before':proof['balances'][resource],'gems_before':proof['gems'],'at':time.time()}
    # Either durable journal alone prevents another purchase after interruption.
    p['payment']=payment;write(importer.path,state)
    ledger['pending']=payment;write(ledger_path,ledger)
    if importer.stop():return {'status':'needs_review'}
    s.input.tap(*item['point'],jitter=0)
    if interrupted_sleep(1,importer.stop):return {'status':'needs_review'}
    first=s.capture.screenshot()
    cv2.imwrite(str(config.data_dir/'layouts/last-removal-start.png'),first)
    if removal_started(importer.reader,first,target,item['name']):
        second=s.capture.screenshot()
        if removal_started(importer.reader,second,target,item['name']):
            effect={
                'operation':payment['operation'],'account':config.account_tag,'cost':item['cost'],
                'currency':resource,'kind':'native_removal_in_progress','at':time.time()}
            effect_path=config.data_dir/'layouts/removal-proof.json'
            write(effect_path,effect)
            # Observe completion without touching Cancel, gem finishing, or
            # another obstacle. Finished seasonal rewards then settle before
            # the next starting balance is read. Stop retains the payment.
            deadline=time.monotonic()+35
            while not importer.stop() and time.monotonic()<deadline:
                frame=s.capture.screenshot()
                if not importer.reader.editing(frame):break
                if importer.reader.find(frame,'removal_cancel',(.22,.60,.78,.79),threshold=.98) is None:
                    fresh=s.capture.screenshot()
                    if importer.reader.editing(fresh) and importer.reader.find(fresh,'removal_cancel',(.22,.60,.78,.79),threshold=.98) is None:
                        effect['finished_at']=time.time();write(effect_path,effect);break
                if interrupted_sleep(.4,importer.stop):return {'status':'needs_review'}
    return reconcile(importer)


def reconcile(importer):
    s=importer.s;config=s.config
    state=read(importer.path,{})
    p=state.get('pending') or state.get('last_survey',{})
    payment=p.get('payment')
    ledger_path=config.data_dir/'upgrades/state.json';ledger=read(ledger_path,{})
    if p.get('account')!=config.account_tag:
        return {'status':'needs_review','message':'Obstacle payment belongs to another account'}
    completed=ledger.get('last_completed',{})
    if (payment and payment.get('operation') and not ledger.get('pending')
        and completed.get('operation')==payment['operation'] and completed.get('phase')=='confirmed'):
        # A crash between the two receipt writes must not cause another payment.
        p['payment_receipt']=completed;p.pop('payment',None);write(importer.path,state)
        return {'status':'making_room','name':completed['name'],'spent':completed['cost'],'currency':completed['currency']}
    if not payment or ledger.get('pending')!=payment:
        return {'status':'needs_review','message':'Obstacle payment journals disagree'}
    if importer.stop():return {'status':'needs_review'}
    if state.get('pending') and not importer.cancel_obstacle_survey():
        return {'status':'needs_review','message':'Cannot verify original active layout after removal'}
    frame=s.capture.screenshot()
    if importer.reader.active_slot(frame) is not None:
        if not importer.close():return {'status':'needs_review'}
    elif not home_resources(frame,importer.stop):
        return {'status':'needs_review','message':'Neither the original layout chooser nor home village is verified'}
    from coc_bot.layouts.importer import verify_owner
    verify_owner(s,importer.stop)
    if importer.stop():return {'status':'needs_review'}
    first=home_resources(s.capture.screenshot(),importer.stop)
    second=home_resources(s.capture.screenshot(),importer.stop)
    effect=read(config.data_dir/'layouts/removal-proof.json',{})
    started=(effect.get('operation')==payment['operation'] and effect.get('account')==config.account_tag
             and effect.get('kind')=='native_removal_in_progress' and effect.get('cost')==payment['cost']
             and effect.get('currency')==payment['currency'])
    expected=payment['balance_before']-payment['cost']
    if (not first or first!=second or first['gems']<payment['gems_before']
        or (first['balances'][payment['currency']]!=expected
            and not (started and first['balances'][payment['currency']]>=expected))):
        return {'status':'needs_review','message':'Obstacle resource receipt is uncertain; no repeat payment'}
    ledger['last_completed']=ledger.pop('pending')|{'phase':'confirmed','gems_after':first['gems'],
        'balance_after':first['balances'][payment['currency']],
        'receipt_method':'native_removal_and_home_receipt' if started else 'exact_deduction'};write(ledger_path,ledger)
    if started and effect.get('finished_at'):
        ledger['last_completed']['finished_at']=effect['finished_at'];write(ledger_path,ledger)
    # Obstacle removal does not occupy a builder. Even all builders being free
    # cannot prove it finished; only matching native completion evidence may
    # shorten the conservative settlement guard used by remember_removal().
    # cancel_obstacle_survey moves pending into last_survey. Reload that state
    # rather than writing the stale pre-cancellation object back over it.
    state=read(importer.path,{})
    receipt=state.get('last_survey',{})
    if receipt.get('payment',{}).get('operation')==payment['operation']:
        receipt['payment_receipt']=ledger['last_completed'];receipt.pop('payment',None)
        write(importer.path,state)
    return {'status':'making_room','name':payment['name'],'spent':payment['cost'],'currency':payment['currency']}
