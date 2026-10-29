"""Move the placement preview, never tap arbitrary map positions to buy things."""
from functools import lru_cache
from pathlib import Path
import time
import cv2
from coc_bot.upgrades.vision import crop, Candidate
from coc_bot.upgrades.runner import write_json
from coc_bot.progression.reader import balance_amount


@lru_cache(maxsize=4)
def _asset(name):
    return cv2.imread(str(Path(__file__).with_name('assets')/('place_'+name+'.png')))


def _locate(frame, name, *, check_threshold=205, reference_name=None):
    canvas = cv2.resize(frame,(1853,1048))
    # Tall buildings place their preview controls near the top of the world.
    region = crop(canvas,(.16,.02,.85,.80))
    asset = _asset(reference_name or name)
    if asset is None: return None
    if name=='no' and reference_name=='no_builder':
        # A red Barracks roof can join the cancel button's red component.
        # The inspected full button still has its exact white X and border.
        base=_asset('no')
        def cross_width(value):
            white=cv2.inRange(cv2.cvtColor(value,cv2.COLOR_BGR2HSV),(0,0,205),(180,70,255))
            shapes,_=cv2.findContours(white,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
            eligible=[v for v in shapes if cv2.boundingRect(v)[3]>=10]
            return cv2.boundingRect(max(eligible,key=cv2.contourArea))[2] if eligible else None
        a,b=cross_width(asset),cross_width(base)
        if not a or not b:return None
        found=[]
        for factor in (.92,.96,1.,1.04,1.08):
            sample=cv2.resize(asset,None,fx=factor,fy=factor)
            _,score,_,(x,y)=cv2.minMaxLoc(cv2.matchTemplate(region,sample,cv2.TM_CCOEFF_NORMED))
            if score>=.97:
                scale=factor*a/b
                found.append((score,{'point':(round((1853*.16+x+sample.shape[1]/2)*frame.shape[1]/1853),
                                             round((1048*.02+y+sample.shape[0]/2)*frame.shape[0]/1048)),
                                    'scale':scale,'width':round(base.shape[1]*scale*frame.shape[1]/1853)}))
        return max(found,key=lambda v:v[0])[1] if found else None
    def colored(image):
        hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
        # White checkmark is isolated even when the green button's antialiased
        # corners touch green grass and merge the color component into the map.
        if name=='yes':return cv2.inRange(hsv,(0,0,check_threshold),(180,70,255))
        return cv2.inRange(hsv,(0,100,100),(10,255,255))|cv2.inRange(hsv,(170,100,100),(180,255,255))
    reference_contours,_=cv2.findContours(colored(asset),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    eligible=[v for v in reference_contours if cv2.boundingRect(v)[3]>=12]
    if not eligible:return None
    reference_shape=max(eligible,key=cv2.contourArea)
    a,b,c,d=cv2.boundingRect(reference_shape);reference=asset[b:b+d,a:a+c]
    contours,_=cv2.findContours(colored(region),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    found=[]
    for contour in contours:
        x,y,w,h=cv2.boundingRect(contour)
        if not 12<w<160 or not 12<h<160 or not .65<w/h<1.6:continue
        cell=cv2.resize(region[y:y+h,x:x+w],(c,d),interpolation=cv2.INTER_AREA)
        if name=='yes':
            green=cv2.inRange(cv2.cvtColor(cell,cv2.COLOR_BGR2HSV),(25,70,110),(90,255,255))
            if green.mean()/255<.10:continue
        score=float(cv2.matchTemplate(cell,reference,cv2.TM_CCOEFF_NORMED)[0,0])
        if reference_name=='yes_builder' and score>=.78:
            # Small camera-scale changes alter antialiasing of the gray native
            # check. Its contour, normalized mask and enabled green face must
            # all agree; this fallback never applies to Home construction.
            overlap=float(cv2.matchTemplate(colored(cell),colored(reference),cv2.TM_CCOEFF_NORMED)[0,0])
            shape=cv2.matchShapes(contour,reference_shape,cv2.CONTOURS_MATCH_I1,0)
            green=cv2.inRange(cv2.cvtColor(cell,cv2.COLOR_BGR2HSV),(25,70,110),(90,255,255)).mean()/255
            if overlap>=.82 and shape<=.06 and green>=.25:score=max(score,.90)
        if score>=.90:
            found.append((score,round((round(1853*.16)+x+w/2)*frame.shape[1]/1853),
                          round((round(1048*.02)+y+h/2)*frame.shape[0]/1048),w/c))
    if not found:return None
    _,x,y,scale=max(found)
    return {'point':(x,y),'scale':scale,'width':round(c*scale*frame.shape[1]/1853)}


def controls(frame, *, check_threshold=205, check_asset=None, cancel_asset=None):
    no,yes = _locate(frame,'no',reference_name=cancel_asset),_locate(frame,'yes',check_threshold=check_threshold,reference_name=check_asset)
    if not no:return None
    a,b=no['point']
    if yes and (abs(b-yes['point'][1])>no['width']*.20 or
                not no['width']*1.3<yes['point'][0]-a<no['width']*2.8 or
                abs(yes['scale']/no['scale']-1)>.25):
        yes=None
    scale=no['scale']
    return {'cancel':no['point'],'confirm':yes['point'] if yes else None,
            'ghost':(round(a+frame.shape[1]*26*scale/1853),round(b+frame.shape[0]*55*scale/1048))}


class Construction:
    def __init__(self, runner):
        self.runner = runner
        self.controls = getattr(runner,'construction_controls',controls)

    def locate_space(self):
        r = self.runner
        frame = r.capture.screenshot()
        for x,y in [(None,None),(.5,.55),(.43,.48),(.56,.48),(.36,.55),(.63,.55),(.5,.67),(.43,.63),(.57,.63)]:
            if r.stopped(): return None
            observed = self.controls(frame)
            if observed is None: raise ValueError('Building placement preview disappeared')
            if observed['confirm']:
                second = self.controls(r.capture.screenshot())
                if second == observed:
                    return observed
            if x is not None and r.config.progression_rearrange:
                start = observed['ghost']
                # A verified preview owns this drag. No existing building is selected.
                r.input.client.run(['shell','input','touchscreen','draganddrop',str(start[0]),str(start[1]),
                                    str(round(x*frame.shape[1])),str(round(y*frame.shape[0])),'900'])
                if r.wait(): return None
                frame = r.capture.screenshot()
        observed = self.controls(frame)
        if observed and not r.stopped():
            if observed['confirm'] and self.controls(r.capture.screenshot())==observed:
                return observed
            r.input.tap(*observed['cancel'],jitter=0)
            r.wait()
        return None

    def start(self, row, before):
        r = self.runner
        located = r.find_row(row)
        if located is None: return {'status':'changed','message':'New-building row changed'}
        fresh,frame = located
        if r.stopped(): return {'status':'stopped'}
        balances = r.reader.balances(frame)
        available = r.reader.availability(frame,'buildings')
        if balances != before['balances'] or r.eligibility('buildings',
                Candidate(
                    fresh['name'],fresh['cost'],fresh['currency'],fresh['point']),balances,available):
            return {'status':'changed','message':'Construction resources or builder availability changed'}
        r.input.tap(*fresh['point'],jitter=0)
        if r.wait(): return {'status':'stopped'}
        placement = self.locate_space()
        if not placement:
            if r.stopped():return {'status':'stopped'}
            from coc_bot.progression.space import SpaceMaker
            return SpaceMaker(r).run()
        # Re-read the unchanged resource counters before the one spending tap.
        screen = r.capture.screenshot()
        normal = {'gold':(.87,.035,.953,.072), 'elixir':(.87,.103,.953,.14)}
        balance = balance_amount(crop(screen,normal[row['currency']]),r.stop)
        if balance != balances[row['currency']] or controls(screen) != placement:
            if not r.stopped():r.input.tap(*placement['cancel'],jitter=0)
            return {'status':'changed','message':'Placement or resource amount changed'}
        state = r.state()
        state['pending'] = {'kind':'construction','name':row['name'],'cost':row['cost'],
                            'currency':row['currency'],'balance_before':balance,'at':time.time(),
                            'row':row,'free_before':available[0],'phase':'confirming'}
        write_json(r.path,state)
        if r.stopped():return {'status':'needs_review','pending':state['pending']}
        r.input.tap(*placement['confirm'],jitter=0)
        if r.wait(1.2):return {'status':'needs_review','pending':state['pending']}
        screen = r.capture.screenshot()
        after = balance_amount(crop(screen,normal[row['currency']]),r.stop)
        if controls(screen) is not None or after != balance-row['cost']:
            return {'status':'needs_review','message':'Construction outcome is uncertain; repeat purchases are blocked'}
        state['last_completed'] = state.pop('pending') | {'phase':'confirmed'}
        from coc_bot.layouts.runner import dirty
        dirty(r.config)
        write_json(r.path,state)
        return {'status':'started','message':row['name']+' construction confirmed','spent':row['cost'],'currency':row['currency']}
