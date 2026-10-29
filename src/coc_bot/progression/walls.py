"""Instant wall upgrades confirm level and payment, rather than a builder timer."""
import re
import time
from coc_bot.upgrades.vision import crop, text, compact, resource_amount, currency, Candidate
from coc_bot.upgrades.runner import write_json
from coc_bot.progression.reader import selected_title, balance_amount
from coc_bot.vision.battle_menu import _white_label


def wall_panel(frame, stop=None):
    title=selected_title(frame,(.24,.640,.50,.697),stop)
    match=re.fullmatch(r'walllevel(\d{1,2})',re.sub(r'[^a-z0-9]','',title.lower()))
    if not match:return None
    level=int(match[1])
    if not 1<=level<=30:return None
    from coc_bot.progression.bulk_walls import payments
    candidates=payments(frame,stop)
    candidate=next((v for v in candidates if v['currency']=='gold'),next(iter(candidates),None))
    if candidate:
        return {'level':level,'cost':candidate['price'],'currency':candidate['currency'],
                'upgrade':True,'point':candidate['pay']}
    import cv2
    button_label=crop(frame,(.489,.808,.572,.857))
    mask=cv2.inRange(cv2.cvtColor(button_label,cv2.COLOR_BGR2HSV),(0,0,205),(180,70,255))
    label=compact(text(255-mask,stop=stop))
    price=resource_amount(crop(frame,(.515,.715,.555,.751)),stop)
    resource=currency(crop(frame,(.555,.715,.573,.75)))
    return {'level':level,'cost':price,'currency':resource,'upgrade':label=='upgrade',
            'point':(round(frame.shape[1]*.528),round(frame.shape[0]*.79))}


class WallUpgrade:
    def __init__(self,runner):self.r=runner

    def recover(self, state):
        pending=state.get('pending',{})
        remaining,target=pending.get('remaining_before'),pending.get('target_level')
        before,cost=pending.get('balance_before'),pending.get('cost')
        count=pending.get('count',1)
        unit_cost=pending.get('unit_cost',cost)
        if (pending.get('kind')!='wall' or any(type(v) is not int for v in (remaining,target,before,cost))
            or remaining<1 or cost<=0 or type(count) is not int or not 1<=count<=remaining
            or type(unit_cost) is not int or unit_cost*count!=cost
            or pending.get('currency') not in ('gold','elixir')):
            return {'status':'needs_review','message':'Wall receipt lacks an independent before observation'}
        r=self.r
        if 'unit_cost' in pending:
            from coc_bot.progression.bulk_walls import confirmation
            frame=r.capture.screenshot()
            point=confirmation(frame,cost,pending['currency'],r.stop)
            if point:
                if pending.get('confirmation_attempts',0)>=1:
                    return {'status':'needs_review','message':'Bulk wall confirmation was already sent; no repeated payment'}
                if r.stopped() or confirmation(r.capture.screenshot(),cost,pending['currency'],r.stop)!=point:
                    return {'status':'needs_review','message':'Bulk wall payment confirmation changed'}
                pending.update(phase='paying',confirmation_attempts=1)
                write_json(r.path,state)
                if r.stopped():return {'status':'needs_review'}
                r.input.tap(*point,jitter=0)
                if r.wait(.8):return {'status':'needs_review'}
        for _ in range(2):
            if r.stopped():return {'status':'stopped'}
            r.close();frame=r.open_menu('buildings')
            if frame is None:return {'status':'stopped'}
            inventory=r.scan(frame)
            balance=inventory.get('balances',{}).get(pending['currency'])
            if (not inventory.get('complete') or not inventory.get('unfiltered') or inventory.get('unknown')
                or type(balance) is not int or not before-cost<=balance<before
                or queue_count(inventory['rows'],pending|{'cost':unit_cost},target,complete=True)!=remaining-count):
                return {'status':'needs_review','message':'Wall level queue and payment could not both be verified'}
        state['last_completed']=state.pop('pending')|{'phase':'confirmed','level_after':target,
                                                     'receipt_method':'two_complete_wall_queues'}
        write_json(r.path,state)
        return {'status':'recovered','message':'Previous wall upgrade independently confirmed; no payment repeated'}

    def run(self,row):
        if row.get('currency') not in ('gold','elixir'):
            return {'status':'blocked','message':'Walls require a verified gold or elixir price'}
        r=self.r;found=r.find_row(row)
        if found is None:return {'status':'changed','message':'Wall row changed'}
        selected,frame=found
        before=r.reader.balances(frame).get(row['currency'])
        available=r.reader.availability(frame,'buildings')
        candidate=Candidate(row['name'],row['cost'],row['currency'],selected['point'])
        blocked=r.eligibility('buildings',candidate,r.reader.balances(frame),available)
        if blocked:return {'status':'blocked','message':blocked}
        if r.stopped():return {'status':'stopped'}
        r.input.tap(*selected['point'],jitter=0)
        if r.wait():return {'status':'stopped'}
        first_frame=r.capture.screenshot();second_frame=r.capture.screenshot()
        first=wall_panel(first_frame,r.stop)
        second=wall_panel(second_frame,r.stop)
        if (first is None or first!=second or not first['upgrade'] or
                (first['cost'],first['currency'])!=(row['cost'],row['currency'])):
            return {'status':'blocked','message':'Wall level, price or upgrade control is uncertain'}
        if before is None or wall_balance(second_frame,r.reader,row['currency'],r.stop)!=before:
            return {'status':'blocked','message':'Wall resources changed or could not be read before payment'}
        state=r.state()
        target=first['level']+1
        counts=[queue_count(r.reader.rows(f),row,target) if r.reader.menu_kind(f)=='buildings' else None
                for f in (first_frame,second_frame)]
        remaining=counts[0] if counts[0]==counts[1] else None
        from coc_bot.progression.bulk_walls import control,BulkWalls
        if type(remaining) is int and control(second_frame,'upgrade_more') is not None:
            return BulkWalls(r).run(row,first,remaining,before)
        state['pending']={'kind':'wall','name':'Wall','cost':row['cost'],'currency':row['currency'],
                          'level_before':first['level'],'balance_before':before,'phase':'confirming','at':time.time(),
                          'remaining_before':remaining,'target_level':target}
        write_json(r.path,state)
        if r.stopped():return {'status':'needs_review'}
        r.input.tap(*first['point'],jitter=0)
        if r.wait(.8):return {'status':'needs_review'}
        frame=r.capture.screenshot();confirmation=r.reader.confirmation(frame,candidate)
        if confirmation is not None:
            if r.reader.confirmation(r.capture.screenshot(),candidate)!=confirmation:
                return {'status':'needs_review','message':'Wall confirmation changed; no second tap sent'}
            if r.stopped():return {'status':'needs_review'}
            r.input.tap(*confirmation['point'],jitter=0)
            if r.wait(.8):return {'status':'needs_review'}
            frame=r.capture.screenshot()
        after=wall_panel(frame,r.stop)
        balance=wall_balance(frame,r.reader,row['currency'],r.stop)
        confirmed=after is not None and after['level']==target and balance==before-row['cost']
        if not confirmed and type(remaining) is int and remaining>=1 and balance==before-row['cost']:
            # Instant upgrades deselect the wall. In that layout, independently
            # verify that exactly one wall left this target-level/price queue.
            confirmed=self.confirm_queue(row,target,remaining,frame,before-row['cost'])
        if not confirmed and balance==before-row['cost'] and type(remaining) is int:
            # Instant upgrades can close the sidebar and deselect the wall.
            # Reopen only the verified Build menu and read complete inventories.
            result=self.recover(state)
            if result['status']=='recovered':return result
        if not confirmed:
            return {'status':'needs_review','message':'Instant wall upgrade was not independently confirmed; repeat spending blocked'}
        state['last_completed']=state.pop('pending')|{'phase':'confirmed','level_after':target}
        write_json(r.path,state)
        return {'status':'started','message':'Wall level '+str(target)+' confirmed','spent':row['cost']}

    def confirm_queue(self,row,target,remaining,frame,expected_balance):
        r=self.r
        if remaining>1:
            for _ in range(2):
                if r.stopped() or r.reader.menu_kind(frame)!='buildings':return False
                if queue_count(r.reader.rows(frame),row,target)!=remaining-1:return False
                if wall_balance(frame,r.reader,row['currency'],r.stop)!=expected_balance:return False
                frame=r.capture.screenshot()
            return True
        # The last wall disappears from the list. A missing row on one scrolled
        # page proves nothing: require two complete, readable inventories.
        for _ in range(2):
            if r.stopped():return False
            r.close();opened=r.open_menu('buildings')
            if opened is None:return False
            inventory=r.scan(opened)
            if (not inventory.get('complete') or not inventory.get('unfiltered') or inventory.get('unknown') or
                    inventory['balances'].get(row['currency'])!=expected_balance or
                    queue_count(inventory['rows'],row,target,complete=True)!=0):return False
        return True


def wall_balance(frame,reader,resource,stop=None):
    """Wall selection can keep the sidebar open or return to the full village."""
    kind=reader.menu_kind(frame)
    if kind=='buildings':return reader.balances(frame).get(resource)
    if kind is not None:return None
    box={'gold':(.87,.035,.953,.072),'elixir':(.87,.103,.953,.14)}[resource]
    return balance_amount(crop(frame,box),stop)


def queue_count(rows,wanted,target,complete=False):
    relevant=[v for v in rows if compact(v['name'])=='wall' and not v.get('new')
              and v.get('cost')==wanted['cost'] and v.get('currency')==wanted['currency']]
    if any(type(v.get('target_level')) is not int for v in relevant):return None
    matches=[v for v in relevant if v['target_level']==target]
    if not matches:return 0 if complete else None
    if len(matches)!=1:return None
    count=matches[0].get('quantity')
    return count if type(count) is int and 1<=count<=500 else None
