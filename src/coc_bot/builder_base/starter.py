"""Count-verified early Builder Base army, separate from the hero/witch executor."""
import time
import re
import cv2
import numpy as np
from coc_bot.upgrades.vision import crop,resource_amount,text


def army(reader,frame):
    if not reader.attack_menu(frame):return None
    groups=[]
    for i in range(7):
        x=.165+i*.059
        region=crop(frame,(x,.38,x+.061,.50))
        found=reader.find(frame,'setup_army_barbarian',(x,.38,x+.061,.50),threshold=.94)
        if found:
            value=resource_amount(crop(frame,(x+.014,.383,x+.026,.411)),reader.stop)
            if value is None:
                raw=text(crop(frame,(x+.013,.382,x+.027,.413)),digits=True,stop=reader.stop)
                value=int(raw) if re.fullmatch(r'\d{1,2}',raw) else None
            if value!=3:return None
            groups.append(value)
        elif region.std()>12:
            return None  # A hero/different troop cannot become a blank camp.
    if not groups or len(groups)>6:return None
    return {'family':'raged_barbarian','groups':len(groups),'units':sum(groups)}


def cards(reader,frame):
    if not reader.battle(frame):return []
    from coc_bot.builder_base.vision import ASSETS
    ref=cv2.imread(str(ASSETS/'starter_battle_portrait.png'),cv2.IMREAD_GRAYSCALE)
    if ref is None:return []
    box=(.04,.84,.84,.95);region=cv2.cvtColor(crop(frame,box),cv2.COLOR_BGR2GRAY)
    h,w=frame.shape[:2];base_scale=w/1853;matches=[];found=[]
    for factor in (.94,.98,1,1.04,1.08,1.12):
        scale=base_scale*factor
        sample=cv2.resize(ref,None,fx=scale,fy=scale)
        if sample.shape[0]>region.shape[0] or sample.shape[1]>region.shape[1]:continue
        scores=cv2.matchTemplate(region,sample,cv2.TM_CCOEFF_NORMED)
        for _ in range(6):
            _,score,_,(a,b)=cv2.minMaxLoc(scores)
            if score<.94:break
            point=(round(w*box[0])+a+sample.shape[1]//2,round(h*box[1])+b+sample.shape[0]//2)
            matches.append((score,point,scale,sample.shape))
            scores[max(0,b-sample.shape[0]):b+sample.shape[0],max(0,a-sample.shape[1]):a+sample.shape[1]]=-1
    for score,point,scale,shape in sorted(matches,reverse=True):
        if any(abs(c['point'][0]-point[0])<w*.035 for c in found):continue
        x,y=point
        number=frame[round(y-78*scale):round(y-40*scale),round(x+14*scale):round(x+40*scale)]
        count=resource_amount(number,reader.stop)
        if count is None:
            value=text(number,digits=True,stop=reader.stop)
            count=int(value) if re.fullmatch(r'[0-3]',value) else None
        portrait=crop(frame,((x-shape[1]/2)/w,(y-shape[0]/2)/h,(x+shape[1]/2)/w,(y+shape[0]/2)/h))
        colored=(cv2.cvtColor(portrait,cv2.COLOR_BGR2HSV)[:,:,1]>75).mean()>.35
        if type(count) is int and 0<=count<=3 and (colored or count==0):found.append({'point':point,'count':count})
    return sorted(found,key=lambda c:c['point'][0])


def card(reader,frame):
    found=cards(reader,frame)
    return found[0] if found else None


def watch(r, *, deploy):
    from coc_bot.builder_base.runner import deployment_points
    deadline=time.monotonic()+420
    done=0;failures=0;points=[];reference=None;zoomed=False
    while time.monotonic()<deadline:
        frame=r.frame();button=r.reader.result_button(frame)
        from coc_bot.builder_base.tutorials import recover
        if recover(r,frame):continue
        if button and r.reader.result_button(r.frame())==button:
            r.evidence(frame,'starter-results');r.phase('leaving_results');r.tap(button);r.wait(2);continue
        if r.reader.reward_button(frame):
            frame=r.settle_village(r.reader.home)
        if r.reader.home(frame) and r.reader.home(r.frame()):
            r.phase('builder_home')
            return {'status':'returned' if done or not deploy else 'no_verified_deployment','verified_deployments':done}
        if not deploy or not r.reader.battle(frame):r.wait(1);continue
        prepared=r.record.get('starter_army',{})
        if r.record.get('starter_confirmed',0)==prepared.get('units'):
            r.wait(1);continue
        if not zoomed:
            # Match the established Builder attack's camera preparation. A
            # scouting close-up can put every candidate tile inside a building
            # or outside the visible arena. Read all cards/targets again after
            # the gesture; no coordinates from the close-up survive it.
            r.zoom(frame);zoomed=True
            r.wait(.4);continue
        observed=cards(r.reader,frame)
        if len(observed)!=r.record.get('starter_army',{}).get('groups'):
            failures+=1
            if failures>=6:
                r.evidence(frame,'starter-unrecognized-cards')
                raise ValueError('Starter battle cards could not be verified; no deployment input')
            r.wait(.5);continue
        failures=0
        current=next((c for c in observed if c['count']),None)
        if current is None:r.wait(1);continue
        expected=r.record.get('starter_army',{}).get('units')
        sent=r.record.get('starter_sent',0)
        if type(expected) is not int or sum(c['count'] for c in observed)!=expected-sent:
            raise ValueError('Starter army count changed unexpectedly; deployment stopped')
        fresh=r.frame()
        if cards(r.reader,fresh)!=observed:r.wait(.3);continue
        r.tap(current['point']);r.wait(.15)
        before=r.frame()
        if reference is None:points=deployment_points(before);reference=before.copy() if points else None
        else:
            from coc_bot.attack.camera import compare_camera
            motion=compare_camera(reference,before)
            if not motion['verified'] or abs(motion['scale']-1)>.003 or np.abs(np.asarray(motion['transform'])[:2,2]).max()>3:
                raise ValueError('Starter camera moved; saved deployment targets discarded')
        if not points:
            r.evidence(before,'starter-no-deploy-zone')
            raise ValueError('No verified clear Builder Base placement tile')
        # Persist possible deployment before input. Recovery observes the battle
        # without replaying troops, even if Stop interrupts the receipt check.
        r.record['starter_sent']=sent+1;r.phase('battle')
        r.tap(points[sent%len(points)]);r.wait(.4)
        after=cards(r.reader,r.frame())
        if len(after)==len(observed) and sum(c['count'] for c in after)==expected-sent-1:
            done+=1;r.record['starter_confirmed']=sent+1;r.phase('battle')
        else:
            r.evidence(r.frame(),'starter-count-unverified')
            raise ValueError('Starter deployment receipt is uncertain; no further map taps')
    raise ValueError('Starter Builder Base battle did not return within seven minutes')
