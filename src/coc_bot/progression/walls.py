"""Instant wall upgrades confirm level and payment, rather than a builder timer."""
import re
import time
from loguru import logger
from coc_bot.upgrades.vision import crop, text, compact, resource_amount, currency, Candidate
from coc_bot.upgrades.runner import write_json
from coc_bot.progression.reader import selected_title, balance_amount
from coc_bot.progression import wall_evidence

# Retry bulk after a reader update instead of carrying over an old OCR failure.
BULK_READER_REVISION = 1


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
                'upgrade':True,'point':candidate['pay'],'red':candidate['red']}
    import cv2
    button_label=crop(frame,(.489,.808,.572,.857))
    mask=cv2.inRange(cv2.cvtColor(button_label,cv2.COLOR_BGR2HSV),(0,0,205),(180,70,255))
    label=compact(text(255-mask,stop=stop))
    price_image=crop(frame,(.515,.715,.555,.751))
    price=resource_amount(price_image,stop)
    hsv=cv2.cvtColor(price_image,cv2.COLOR_BGR2HSV)
    red=cv2.inRange(hsv,(0,110,140),(12,255,255)) | cv2.inRange(hsv,(170,110,140),(180,255,255))
    resource=currency(crop(frame,(.555,.715,.573,.75)))
    return {'level':level,'cost':price,'currency':resource,'upgrade':label=='upgrade',
            'red':cv2.countNonZero(red)>red.size*.02,
            'point':(round(frame.shape[1]*.528),round(frame.shape[0]*.79))}


class WallUpgrade:
    def __init__(self,runner):self.r=runner

    def finish(self,state,**proof):
        updated=state.copy()
        completed=updated.pop('pending')|{'phase':'confirmed',**proof}
        updated['last_completed']=completed
        write_json(self.r.path,updated)
        state.pop('pending')
        state['last_completed']=completed
        wall_evidence.mark_confirmed(self.r,completed)

    def recover(self, state, *, immediate=False):
        try:
            return self._recover(state, immediate)
        except wall_evidence.EvidenceError as exc:
            return {'status':'needs_review','message':f'Wall after evidence unavailable: {exc}'}

    def _recover(self, state, immediate):
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
            if immediate and not point:
                wall_evidence.observe(r,pending,'after_selection',frame,confirmation_visible=False)
            if point:
                if 'intent_id' in pending and not immediate:
                    return {'status':'needs_review','message':'Pending wall confirmation requires review after interruption'}
                if pending.get('confirmation_attempts',0)>=1:
                    return {'status':'needs_review','message':'Bulk wall confirmation was already sent; no repeated payment'}
                wall_evidence.observe(r,pending,'bulk_dialog',frame,cost=cost,currency=pending['currency'])
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
            inventory=self.scan_after(frame,pending,unit_cost,target)
            balance=inventory.get('balances',{}).get(pending['currency'])
            if (not inventory.get('complete') or not inventory.get('unfiltered') or inventory.get('unknown')
                or type(balance) is not int or not before-cost<=balance<before
                or queue_count(inventory['rows'],pending|{'cost':unit_cost},target,complete=True)!=remaining-count):
                return {'status':'needs_review','message':'Wall level queue and payment could not both be verified'}
        self.finish(state,level_after=target,receipt_method='two_complete_wall_queues')
        return {'status':'recovered','message':'Previous wall upgrade independently confirmed; no payment repeated'}

    def run(self,row):
        try:
            return self._run(row)
        except wall_evidence.EvidenceError as exc:
            return {'status':'needs_review','message':f'Wall after evidence unavailable: {exc}'}

    def _run(self,row, *, allow_bulk=True):
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
        if first and second and (first.get('red') or second.get('red')):
            return {'status':'waiting','message':'Wall price is red; nothing spent'}
        if (first is None or first!=second or not first['upgrade'] or
                (first['cost'],first['currency'])!=(row['cost'],row['currency'])):
            from coc_bot.runtime.verification import save_frame
            save_frame(r.config,'wall-first',first_frame)
            save_frame(r.config,'wall-second',second_frame)
            return {'status':'blocked','message':'Wall level, price or upgrade control is uncertain'}
        if before is None or wall_balance(second_frame,r.reader,row['currency'],r.stop)!=before:
            return {'status':'blocked','message':'Wall resources changed or could not be read before payment'}
        target=first['level']+1
        counts=[queue_count(r.reader.rows(f),row,target) if r.reader.menu_kind(f)=='buildings' else None
                for f in (first_frame,second_frame)]
        remaining=counts[0] if counts[0]==counts[1] else None
        # Every payment needs a recoverable before observation. A direct
        # level read may disappear when an instant upgrade deselects the wall.
        if type(remaining) is not int or remaining<1:
            from coc_bot.runtime.verification import save_frame
            save_frame(r.config,'wall-queue-before',second_frame)
            return {'status':'blocked','message':'Wall queue count/target level is unverified; nothing spent'}
        state=r.state()
        if state.get('pending'):
            return {'status':'needs_review','message':'Resolve the saved upgrade payment before upgrading walls'}
        from coc_bot.progression.bulk_walls import control,BulkWalls
        last=state.get('last_completed',{})
        recent_single=(last.get('single_wall_fallback') is True and last.get('phase')=='confirmed'
                       and last.get('bulk_reader_revision')==BULK_READER_REVISION
                       and last.get('level_before')==first['level'] and last.get('currency')==row['currency']
                       and 0<=time.time()-last.get('at',0)<3600)
        if allow_bulk and not recent_single and control(second_frame,'upgrade_more') is not None:
            result=BulkWalls(r).run(row,first,remaining,before,(first_frame,second_frame))
            if result['status'] not in ('blocked','changed') or r.state().get('pending') or r.stopped():
                return result
            logger.info('Bulk wall preview failed before payment: {}. Reopening for one wall.', result['message'])
            r.close()
            if r.stopped():return {'status':'stopped'}
            return self._run(row,allow_bulk=False)
        receipt={'kind':'wall','name':'Wall','cost':row['cost'],'currency':row['currency'],
                          'level_before':first['level'],'balance_before':before,'phase':'confirming','at':time.time(),
                          'remaining_before':remaining,'target_level':target}
        if not allow_bulk or recent_single:
            receipt['single_wall_fallback']=True
            receipt['bulk_reader_revision']=BULK_READER_REVISION
        failure=wall_evidence.begin(r,state,receipt,(first_frame,second_frame))
        if failure:return failure
        pending=state['pending']
        if r.stopped():return {'status':'needs_review'}
        r.input.tap(*first['point'],jitter=0)
        if r.wait(.8):return {'status':'needs_review'}
        frame=r.capture.screenshot();confirmation=r.reader.confirmation(frame,candidate)
        if confirmation is not None:
            wall_evidence.observe(r,pending,'single_dialog',frame,cost=row['cost'],currency=row['currency'])
            if r.reader.confirmation(r.capture.screenshot(),candidate)!=confirmation:
                return {'status':'needs_review','message':'Wall confirmation changed; no second tap sent'}
            if r.stopped():return {'status':'needs_review'}
            r.input.tap(*confirmation['point'],jitter=0)
            if r.wait(.8):return {'status':'needs_review'}
            frame=r.capture.screenshot()
        after=wall_panel(frame,r.stop)
        balance=wall_balance(frame,r.reader,row['currency'],r.stop)
        wall_evidence.observe(r,pending,'after_panel',frame,level=after and after['level'],balance=balance)
        # The village can paint the old balance while an instant upgrade
        # settles. Re-read the screen only; never repeat either payment tap.
        expected_balance=before-row['cost']
        for _ in range(2):
            if balance is not None and (balance<=expected_balance or balance>before):break
            if r.stopped() or r.wait(.5):return {'status':'stopped'}
            frame=r.capture.screenshot()
            after=wall_panel(frame,r.stop)
            balance=wall_balance(frame,r.reader,row['currency'],r.stop)
            wall_evidence.observe(r,pending,'after_panel',frame,level=after and after['level'],balance=balance)
        confirmed=after is not None and after['level']==target and balance==expected_balance
        method='selected_wall_level'
        if not confirmed and balance==expected_balance:
            # Instant upgrades deselect the wall. In that layout, independently
            # verify that exactly one wall left this target-level/price queue.
            confirmed=self.confirm_queue(row,target,remaining,frame,expected_balance,pending)
            method='two_wall_queue_frames'
        if not confirmed and balance==expected_balance:
            # Instant upgrades can close the sidebar and deselect the wall.
            # Reopen only the verified Build menu and read complete inventories.
            return self.recover(state)
        if not confirmed:
            return {'status':'needs_review','message':'Instant wall upgrade was not independently confirmed; repeat spending blocked'}
        self.finish(state,level_after=target,receipt_method=method)
        return {'status':'started','message':'Wall level '+str(target)+' confirmed','spent':row['cost']}

    def scan_after(self,opening_frame,pending,unit_cost,target):
        inventory=self.r.scan(opening_frame)
        if 'intent_id' in pending:
            readable=inventory.get('complete') and inventory.get('unfiltered') and not inventory.get('unknown')
            count=queue_count(inventory['rows'],pending|{'cost':unit_cost},target,complete=bool(readable))
            # The frame is the menu at entry; the count describes the whole scroll scan.
            wall_evidence.observe(self.r,pending,'after_inventory',opening_frame,
                                  image_source='menu_at_scan_start',
                                  balance=inventory.get('balances',{}).get(pending['currency']),
                                  remaining=count,target_level=target,complete=inventory.get('complete'),
                                  unfiltered=inventory.get('unfiltered'),unknown=inventory.get('unknown'))
        return inventory

    def confirm_queue(self,row,target,remaining,frame,expected_balance,pending=None):
        r=self.r
        if remaining>1:
            for _ in range(2):
                if r.stopped() or r.reader.menu_kind(frame)!='buildings':return False
                count=queue_count(r.reader.rows(frame),row,target)
                balance=wall_balance(frame,r.reader,row['currency'],r.stop)
                wall_evidence.observe(r,pending or {},'after_queue',frame,remaining=count,target_level=target,balance=balance)
                if count!=remaining-1 or balance!=expected_balance:return False
                frame=r.capture.screenshot()
            return True
        # The last wall disappears from the list. A missing row on one scrolled
        # page proves nothing: require two complete, readable inventories.
        for _ in range(2):
            if r.stopped():return False
            r.close();opened=r.open_menu('buildings')
            if opened is None:return False
            inventory=self.scan_after(opened,pending or {},row['cost'],target)
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
