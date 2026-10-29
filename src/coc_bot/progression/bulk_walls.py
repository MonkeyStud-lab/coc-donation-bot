"""Native multi-wall selection; only gold/elixir payments are supported."""
from pathlib import Path
import re
import time
import cv2
import numpy as np


def controls(frame, name, bounds=(0,.66,.72,.90)):
    ref=cv2.imread(str(Path(__file__).with_name('assets')/('wall_'+name+'.png')))
    if ref is None:return []
    h,w=frame.shape[:2];scale=w/1853
    ref=cv2.resize(ref,None,fx=scale,fy=scale)
    left,top,right,bottom=round(w*bounds[0]),round(h*bounds[1]),round(w*bounds[2]),round(h*bounds[3])
    region=frame[top:bottom,left:right]
    if ref.shape[0]>region.shape[0] or ref.shape[1]>region.shape[1]:return []
    scores=cv2.matchTemplate(region,ref,cv2.TM_CCOEFF_NORMED)
    found=[]
    for _ in range(4):
        _,score,_,(x,y)=cv2.minMaxLoc(scores)
        if score<.96:break
        found.append((x+left+ref.shape[1]//2,y+top+ref.shape[0]//2))
        scores[max(0,y-ref.shape[0]):y+ref.shape[0],max(0,x-ref.shape[1]):x+ref.shape[1]]=0
    return found


def control(frame, name, bounds=(0,.66,.72,.90)):
    found=controls(frame,name,bounds)
    return found[0] if found else None


def maximum_affordable(balance, reserve, unit_cost, available):
    if any(type(v) is not int for v in (balance,reserve,unit_cost,available)) or unit_cost<=0:
        return 0
    return max(0,min(available,(balance-reserve)//unit_cost))


def confirmation(frame, cost, resource, stop=None):
    from coc_bot.upgrades.vision import crop,text
    if resource not in ('gold','elixir') or type(cost) is not int or cost<=0:return None
    if not control(frame,'confirm_title',(.30,.25,.68,.36)):return None
    if not control(frame,'confirm_cancel',(.27,.56,.49,.73)):return None
    okay=control(frame,'confirm_okay',(.51,.56,.71,.73))
    if okay is None:return None
    lines=text(crop(frame,(.29,.41,.70,.455)),stop=stop)+text(crop(frame,(.29,.455,.70,.50)),stop=stop)
    body=re.sub(r'[^a-z0-9]','',lines.lower())
    if body!='doyoureallywanttoupgradetheselectedwallsfor'+str(cost)+resource:return None
    return okay


def selection(frame, resource, stop=None):
    from coc_bot.progression.reader import selected_title
    from coc_bot.upgrades.vision import crop,currency,resource_amount
    title=selected_title(frame,(.24,.64,.50,.697),stop)
    match=re.fullmatch(r'walllevel([0-9il]{1,2})x([0-9il]{1,3})',re.sub(r'[^a-z0-9]','',title.lower()))
    if not match:return None
    # The outlined numeric 1 is read as I in this exact heading. Count changes
    # and the independently read unit-price multiplication must also agree.
    level,count=(int(v.replace('i','1').replace('l','1')) for v in match.groups())
    if not 1<=level<=30 or not 1<=count<=500:return None
    choices=[p for p in payments(frame,stop) if p['currency']==resource]
    if len(choices)!=1:return None
    return choices[0]|{'level':level,'count':count,'plus':control(frame,'add_one'),
                      'minus':control(frame,'remove_one') or control(frame,'remove_one_disabled')}


def payments(frame, stop=None):
    return [price for point in controls(frame,'upgrade_label')
            if (price:=payment(frame,point,stop)) is not None]


def payment(frame, button, stop=None):
    from coc_bot.upgrades.vision import currency
    # Position derives from the identified Upgrade tile, never a gem/item tile.
    h,w=frame.shape[:2];x,y=button;scale=w/1853
    price_image=frame[round(y-130*scale):round(y-82*scale),round(x-80*scale):round(x+58*scale)]
    icon=frame[round(y-130*scale):round(y-82*scale),round(x+58*scale):round(x+88*scale)]
    resource=currency(icon)
    if resource not in ('gold','elixir'):return None
    from coc_bot.progression.reader import balance_amount
    price=balance_amount(price_image,stop)
    hsv=cv2.cvtColor(price_image,cv2.COLOR_BGR2HSV)
    red=(cv2.inRange(hsv,(0,100,140),(12,255,255)) | cv2.inRange(hsv,(170,100,140),(180,255,255)))
    red_value=None
    if price is None:
        from coc_bot.upgrades.digits import read_digits
        from coc_bot.progression.reader import red_digit_variants
        digits=read_digits(price_image,extra_templates=red_digit_variants())
        if digits and digits.isdigit():price=int(digits)
    if price is None:
        from coc_bot.upgrades.vision import text
        from coc_bot.upgrades.digits import glyphs
        count_glyphs=len(glyphs(cv2.cvtColor(red,cv2.COLOR_GRAY2BGR)))
        if 1<=count_glyphs<=9:
            isolated=cv2.copyMakeBorder(255-red,8,8,8,8,cv2.BORDER_CONSTANT,value=255)
            digits=text(cv2.cvtColor(isolated,cv2.COLOR_GRAY2BGR),digits=True,stop=stop).replace(' ','')
            if digits.isdigit() and len(digits)==count_glyphs:
                price=red_value=int(digits)
    if type(price) is not int or price<=0:return None
    from coc_bot.upgrades.digits import read_digits
    from coc_bot.progression.reader import red_digit_variants
    red_price=read_digits(cv2.cvtColor(red,cv2.COLOR_GRAY2BGR),extra_templates=red_digit_variants())
    unaffordable_color=bool(red_value==price or red_price and red_price.isdigit() and int(red_price)==price)
    return {'price':price,'red':unaffordable_color,'pay':button,'currency':resource}


class BulkWalls:
    def __init__(self, runner):self.r=runner

    def settled(self, resource):
        previous=None
        for _ in range(4):
            if self.r.stopped():return None
            current=selection(self.r.capture.screenshot(),resource,self.r.stop)
            if current is not None and current==previous:return current
            previous=current
            if self.r.wait(.15):return None
        return None

    def run(self, row, first, remaining, balance):
        r=self.r;resource=row['currency'];unit_cost=row['cost']
        reserve=getattr(r.config,'upgrade_'+resource+'_reserve')
        maximum=maximum_affordable(balance,reserve,unit_cost,remaining)
        if maximum<1:return {'status':'waiting','message':'No walls fit the resource reserve'}
        a=r.capture.screenshot();point=control(a,'upgrade_more')
        if point is None or control(r.capture.screenshot(),'upgrade_more')!=point:
            return {'status':'blocked','message':'Upgrade More control changed; no payment sent'}
        r.input.tap(*point,jitter=0)
        if r.wait(.4):return {'status':'stopped'}
        value=self.settled(resource)
        if value is None or (value['level'],value['count'],value['price'])!=(first['level'],1,unit_cost):
            return {'status':'blocked','message':'Bulk wall starting count/price could not be verified'}
        # The unaffordable/red selection is only a preview. At zero reserve,
        # allow exactly one overrun then -1, as in the native workflow. A
        # configured reserve stops before consuming those protected resources.
        ceiling=min(remaining,maximum+(reserve==0 and maximum<remaining))
        for _ in range(500):
            if r.stopped():return {'status':'stopped'}
            if value['count']>=ceiling:break
            if value['plus'] is None:return {'status':'blocked','message':'Add one wall is unavailable before the target count'}
            before=value
            r.input.tap(*value['plus'],jitter=0)
            if r.wait(.12):return {'status':'stopped'}
            value=self.settled(resource)
            if (value is None or value['level']!=first['level'] or value['count']!=before['count']+1
                or value['price']!=unit_cost*value['count']):
                return {'status':'blocked','message':'Bulk wall count/price did not increase by one; nothing spent'}
            if value['red'] or value['price']>balance-reserve:break
        if value['red'] or value['price']>balance-reserve:
            if value['minus'] is None:return {'status':'blocked','message':'Remove one wall could not be verified'}
            before=value
            r.input.tap(*value['minus'],jitter=0)
            if r.wait(.12):return {'status':'stopped'}
            value=self.settled(resource)
            if value is None or value['count']!=before['count']-1:
                return {'status':'blocked','message':'Bulk wall subtraction could not be verified'}
        if (value['count']!=maximum or value['red'] or value['price']!=unit_cost*maximum
            or value['price']>balance-reserve):
            return {'status':'blocked','message':'Maximum affordable wall price/count is unverified'}
        from coc_bot.progression.walls import wall_balance,WallUpgrade
        fresh=r.capture.screenshot()
        if selection(fresh,resource,r.stop)!=value or wall_balance(fresh,r.reader,resource,r.stop)!=balance:
            return {'status':'changed','message':'Resources or wall selection changed before payment'}
        # Slot/reserve/exclusion policy applies to the entire batch cost too.
        from coc_bot.upgrades.vision import Candidate
        availability=r.reader.availability(fresh,'buildings')
        blocked=r.eligibility('buildings',Candidate('Wall',value['price'],resource,value['pay']),
                              {resource:balance},availability)
        if blocked:return {'status':'blocked','message':blocked}
        state=r.state()
        state['pending']={'kind':'wall','name':'Wall','cost':value['price'],'unit_cost':unit_cost,
                          'count':maximum,'currency':resource,'level_before':first['level'],
                          'target_level':first['level']+1,'remaining_before':remaining,
                          'balance_before':balance,'phase':'confirming','at':time.time()}
        from coc_bot.upgrades.runner import write_json
        write_json(r.path,state)
        if r.stopped():return {'status':'needs_review'}
        r.input.tap(*value['pay'],jitter=0)
        if r.wait(.8):return {'status':'needs_review'}
        # The dedicated Upgrade Walls confirmation is reconciled from the same
        # durable intent. Generic building confirmation must not authorize it.
        result=WallUpgrade(r).recover(state)
        if result['status']=='recovered':
            return {'status':'started','count':maximum,'spent':value['price'],
                    'message':str(maximum)+' wall upgrades independently confirmed'}
        return result
