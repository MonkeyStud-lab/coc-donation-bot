"""Bounded automatic obstacle clearing and native defensive-layout completion.

The active slot is untouched during clearing and placement. Payments, editor
inputs, draft checkpoints and activation each have independent native receipts.
"""
import time
import cv2
import numpy as np
from loguru import logger
from coc_bot.accounts.store import read,write
from coc_bot.layouts.catalog import catalog,official_layout
from coc_bot.layouts.importer import LayoutImporter
from coc_bot.layouts.grid import camera,pixels,tiles,zone
from coc_bot.layouts.obstacles import home_resources,candidates,selected,remove_selected,reconcile,outside_selected_tree
from coc_bot.layouts.placement import InventoryPlacer
from coc_bot.progression.home import ensure_home
from coc_bot.stop import interrupted_sleep

REVISION='defensive-clear-first-v8'


def dirty(config):
    path=config.data_dir/'layouts/state.json';state=read(path,{})
    state.setdefault('automatic',{}).update(dirty=True,next_check_at=0,stage='clearing',
                                          survey_cursor=0,survey_rejected=[],unfit_references=[],fit_retry=None,
                                          clearance_pass=True,cleared_at=0,compatibility={},selected_reference=None)
    if state.get('draft'):state['draft']['automatic_revision']=None
    write(path,state)


class LayoutRunner:
    def __init__(self,session,stop=lambda:False):
        self.s=session;self.stop=stop;self.i=LayoutImporter(session,stop)

    def record(self,**values):
        state=read(self.i.path,{})
        state.setdefault('automatic',{}).update(values,updated_at=time.time())
        write(self.i.path,state)

    def wait(self,seconds):return interrupted_sleep(seconds,self.stop)

    def home(self):
        # These HUD readings include the Home-only builder face and gem icon.
        # Builder COUNTS are not required for removal. Avoid a full scenery/OCR
        # recovery scan after the native chooser already returned us Home.
        if home_resources(self.s.capture.screenshot(),self.stop):return True
        return ensure_home(self.s.navigator)

    def mapped_frame(self):
        """Remove All and inventory selection can animate the native camera."""
        previous=None
        for _ in range(8):
            if self.stop():return None
            frame=self.s.capture.screenshot()
            if not self.i.reader.editing(frame):return None
            mapping=camera(frame,self.stop)
            if mapping['registered']:
                anchors=pixels(mapping,[(5,5),(39,5),(39,39),(5,39)])
                if previous is not None and np.max(np.linalg.norm(anchors-previous,axis=1))<2:
                    return frame,mapping
                previous=anchors
            else:previous=None
            if self.wait(.25):return None
        folder=self.s.config.data_dir/'layouts';folder.mkdir(parents=True,exist_ok=True)
        cv2.imwrite(str(folder/'last-geometry.png'),frame)
        self.record(geometry_error=mapping)
        return None

    def reframe(self,center):
        """Pan only empty/survey map, reacquiring terrain after every swipe."""
        previous=None
        for _ in range(2):
            if self.stop():return None
            view=self.mapped_frame()
            if view is None:return None
            frame,registration=view
            point=pixels(registration,[center])[0]
            delta=np.array([frame.shape[1]*.43,frame.shape[0]*.42])-point
            if np.linalg.norm(delta)<55:return frame,registration
            if previous is not None and np.linalg.norm(point-previous)<15:return frame,registration
            previous=point
            dx,dy=np.rint(np.clip(delta,[-350,-220],[350,220])).astype(int)
            start=(round(frame.shape[1]*.43),round(frame.shape[0]*.42))
            # Two fingers pan the camera without dragging a selected building.
            from coc_bot.adb.multitouch import Multitouch
            with Multitouch(self.s.client,(frame.shape[1],frame.shape[0])) as touch:
                origins=[(start[0]-100,start[1]),(start[0]+100,start[1])]
                for finger,point in enumerate(origins):touch._send(0,finger,point)
                for step in range(1,15):
                    for finger,(x,y) in enumerate(origins):
                        touch._send(2,finger,(x+round(int(dx)*step/14),y+round(int(dy)*step/14)))
                    if self.wait(.025):return None
            if self.wait(.25):return None
        # A native camera limit may prevent exact centering. Targets are still
        # constrained to the observed HUD-free viewport by candidates().
        return self.mapped_frame()

    def zoom_out(self):
        from coc_bot.adb.multitouch import Multitouch
        # A crowded import can hide the landmarks until it is zoomed out.
        # This gesture needs only the verified editor and stays inside its map;
        # no placement or boundary decision is made from an unregistered view.
        frame=self.s.capture.screenshot()
        if not self.i.reader.editing(frame) or not self.i.reader.editing(self.s.capture.screenshot()):return False
        # The old wide pinch crossed the wrench toolbar. Both fingers must
        # stay inside the map for the game to interpret a zoom gesture.
        with Multitouch(self.s.client,(frame.shape[1],frame.shape[0])) as touch:
            touch.pinch(start_span=.40,end_span=.10,duration=.8)
        return self.mapped_frame() is not None

    def close_unsaved(self):
        state=read(self.i.path,{})
        p=state.get('pending',{})
        if p.get('phase') in ('opening','ready_to_activate','activating'):
            return self.recover()
        if p:
            if not self.i.cancel_obstacle_survey():return False
        frame=self.s.capture.screenshot()
        if self.i.reader.active_slot(frame) is not None:
            if not self.i.close():return False
        return self.home()

    def recover(self):
        """No new payments or drags during recovery, even when disabled."""
        state=read(self.i.path,{});p=state.get('pending',{})
        if p.get('account') not in (None,self.s.config.account_tag):return False
        if p.get('payment') or state.get('last_survey',{}).get('payment'):
            return reconcile(self.i).get('status')=='making_room'
        if p.get('phase')=='opening':
            first=self.i.reader.active_slot(self.s.capture.screenshot())
            if first is None or self.i.reader.active_slot(self.s.capture.screenshot())!=first:return False
            if not self.i.close():return False
            state['last_cancelled']=state.pop('pending');write(self.i.path,state)
            return True
        if p.get('phase')=='saving_draft':
            if self.i.reader.active_slot(self.s.capture.screenshot())==p.get('original_slot'):
                return self.i.save_draft() and self.i.close()
        if (p.get('phase')=='copying_to_empty_slot' and p.get('placements')
            and not p.get('placement') and self.i.reader.editing(self.s.capture.screenshot())):
            return self.i.save_draft() and self.i.close()
        if p.get('phase') in ('ready_to_activate','activating','saving_complete'):
            # A saved complete layout can be reimported later. Do not activate
            # it during recovery before the independent account check.
            f=self.s.capture.screenshot();active=self.i.reader.active_slot(f)
            if active is None and self.i.reader.editing(f):return self.close_unsaved()
            if active not in (p.get('original_slot'),p.get('slot')):return False
            if self.i.reader.active_slot(self.s.capture.screenshot())!=active:return False
            if not self.i.close():return False
            if p.get('phase')=='activating' and active==p.get('slot'):
                if not self.home():return False
                state['completed']=state.pop('pending')|{'status':'active','activated_at':time.time()}
                if state.get('draft',{}).get('slot')==p['slot']:state.pop('draft')
                write(self.i.path,state)
                self.record(stage='verifying',hall=p['hall'],revision=REVISION,dirty=True,last_status='verifying')
            else:
                state['last_cancelled']=state.pop('pending');write(self.i.path,state)
            return True
        return self.close_unsaved() if p else True

    def _open(self,url,hall,proof=None):
        draft=read(self.i.path,{}).get('draft',{})
        protected=((draft['slot'],) if draft.get('account')==self.s.config.account_tag
                   and type(draft.get('slot')) is int and 0<=draft['slot']<3 else ())
        if not self.i.open(url,hall):return False
        if not self.i.select_empty(replace_inactive=self.s.config.layouts_replace_inactive,exclude_slots=protected):return False
        for _ in range(16):
            if self.stop():return False
            if not self.i.dismiss_editor_chat():return False
            frame=self.s.capture.screenshot()
            point=self.i.reader.inventory_notice(frame)
            if point:
                if self.stop() or self.i.reader.inventory_notice(self.s.capture.screenshot())!=point:return False
                self.s.input.tap(*point,jitter=0)
            elif self.i.reader.editing(frame) and self.i.reader.editing(self.s.capture.screenshot()):break
            if self.wait(.3):return False
        else:return False
        # A complete imported copy needs no tile geometry or obstacle survey.
        # Native Save is the authority that every owned building is placed.
        ready=(not proof and self.i.reader.ready_save(self.s.capture.screenshot())
               and self.i.reader.ready_save(self.s.capture.screenshot()))
        if not ready and not self.zoom_out():return False
        if proof:
            state=read(self.i.path,{})
            state['pending']['home_resources']=proof
            write(self.i.path,state)
        return True

    def _clear_one(self,url,hall,deadline):
        a=home_resources(self.s.capture.screenshot(),self.stop)
        b=home_resources(self.s.capture.screenshot(),self.stop)
        if a and b and a!=b:return {'status':'waiting','message':'Resource counters have not settled'}
        if not a or not b:
            if not ensure_home(self.s.navigator):return {'status':'blocked','message':'Home is unverified'}
            a=home_resources(self.s.capture.screenshot(),self.stop)
            b=home_resources(self.s.capture.screenshot(),self.stop)
        if not a or a!=b:return {'status':'waiting','message':'Home resource counters have not settled'}
        if not self.i.open_survey(hall,a|{'at':time.time()}):return {'status':'blocked','message':'Inactive survey editor could not be verified'}
        if not self.zoom_out():return {'status':'needs_geometry'}
        if not self.i.expose_obstacles() or not self.i.confirm_obstacle_survey():return {'status':'needs_review'}
        # Account verification and native loading can consume a cold visit's
        # budget. Allow real work after setup rather than reopening forever.
        deadline=max(deadline,time.monotonic()+30)
        survey=read(self.i.path,{}).get('automatic',{})
        policy=[hall,self.s.config.progression_clear_seasonal_obstacles,'clear-first-full-canvas-v8']
        fresh_survey=(survey.get('survey_policy')!=policy or time.time()-survey.get('survey_started_at',0)>86400)
        cursor=0 if fresh_survey else survey.get('survey_cursor',0)
        if type(cursor) is not int or not 0<=cursor<=5:cursor=0
        rejected=[] if fresh_survey else survey.get('survey_rejected',[])
        views=[];removable=False
        self.record(survey_policy=policy,survey_cursor=cursor,survey_rejected=rejected,
                    survey_started_at=time.time() if fresh_survey else survey['survey_started_at'])
        centers=(None,(11,11),(33,11),(33,33),(11,33))
        for view_index in range(cursor,len(centers)):
            center=centers[view_index]
            if self.stop() or time.monotonic()>deadline:return {'status':'yielding'}
            if center is None:
                view=self.mapped_frame()
            else:view=self.reframe(center)
            if view is None:return {'status':'needs_geometry'}
            frame,registration=view;polygon=zone(registration,margin=0)
            views.append(center)
            # The visit deadline bounds work; truncating the list could mark a
            # dense view clear while obstacles beyond the first 30 are unseen.
            points=candidates(frame,[polygon.tolist()],lower_map=True,limit=None)
            points.sort(key=lambda p:np.linalg.norm(np.array(p)-[frame.shape[1]*.43,frame.shape[0]*.42]))
            for target in points:
                if self.stop() or time.monotonic()>deadline:return {'status':'yielding'}
                uv=tiles(registration,[target])[0]
                if any(np.linalg.norm(uv-r)<.60 for r in rejected):continue
                fresh=self.s.capture.screenshot()
                if not self.i.reader.editing(fresh):return {'status':'needs_review'}
                if not self.i.reader.idle_editor(fresh):
                    # This known blank margin is left of every payment tile.
                    # Deselect first, then positively prove the native idle
                    # instruction. Absence of a Remove label alone is unsafe.
                    if self.stop():return {'status':'stopped'}
                    self.s.input.tap(round(fresh.shape[1]*.04),round(fresh.shape[0]*.67),jitter=0)
                    if self.wait(.15):return {'status':'stopped'}
                    fresh=self.s.capture.screenshot()
                if (not self.i.reader.idle_editor(fresh)
                    or not self.i.reader.idle_editor(self.s.capture.screenshot())):
                    return {'status':'needs_review','message':'Empty editor selection could not be verified'}
                current=camera(fresh,self.stop)
                if not current['registered']:return {'status':'needs_geometry'}
                target=tuple(np.rint(pixels(current,[uv])[0]).astype(int).tolist())
                h,w=fresh.shape[:2]
                if not w*.14<target[0]<w*.76 or not h*.14<target[1]<h*.77:continue
                polygon=zone(current,margin=0)
                if self.stop():return {'status':'stopped'}
                self.s.input.tap(*target,jitter=0)
                if self.wait(.2):return {'status':'stopped'}
                selection=self.s.capture.screenshot()
                if outside_selected_tree(self.i.reader,selection,target):
                    # This only excludes an identified outside object; it
                    # authorizes no payment. Animated foliage need not match
                    # the same sprite again on the next frame.
                    rejected.append(uv.tolist())
                    self.record(survey_cursor=view_index,survey_rejected=rejected)
                    continue
                item=selected(self.i.reader,selection,target,
                              seasonal=self.s.config.progression_clear_seasonal_obstacles)
                if not item:
                    if self.i.reader.find(selection,'remove_word',(.22,.70,.78,.78),threshold=.97) is not None:
                        return {'status':'waiting','message':'A removal control is visible but its price or obstacle identity is unreadable'}
                    rejected.append(uv.tolist())
                    self.record(survey_cursor=view_index,survey_rejected=rejected)
                    continue
                removable=True
                state=read(self.i.path,{})
                p=state['pending'];p.update(footprint_source='registered_default_build_zone_v1',
                       blocked_footprints=[polygon.tolist()],camera=current,obstacle_tile=uv.tolist())
                write(self.i.path,state)
                result=remove_selected(self.i,target)
                logger.info('Layout obstacle {}: {} — {}',item['name'],result['status'],result.get('message',''))
                if result['status'] in ('making_room','needs_review','stopped'):return result
                if result['status']=='blocked':return result
                if result['status']=='waiting':continue
                rejected.append(uv.tolist())
            if removable:return {'status':'waiting','message':'A remaining obstacle needs resources or a verified removal receipt'}
            self.record(survey_cursor=view_index+1,survey_rejected=rejected)
        if not removable:
            if not self.close_unsaved():return {'status':'needs_review'}
            self.finish_clearance(url,views)
            return {'status':'cleared'}
        return {'status':'waiting'}

    def finish_clearance(self,url,views):
        self.record(stage='matching',clearance_pass=False,survey_views=views,cleared_at=time.time(),
                    compatibility={},selected_reference=None,
                    fit_retry={'link':url,'last_removal_at':read(self.i.path,{}).get('automatic',{}).get('last_removal_at',0)})

    def _activate_complete(self,hall,count):
        if not self.i.save_complete() or not self.i.activate():return {'status':'needs_review'}
        self.record(stage='verifying',hall=hall,revision=REVISION,dirty=True)
        return self._finish_verification(hall,count)

    def _verify_active_home(self,hall):
        from coc_bot.layouts.verification import active_preview,signature,compare
        state=read(self.i.path,{});p=state.get('completed',{})
        if (p.get('account')!=self.s.config.account_tag or p.get('hall')!=hall
            or type(p.get('slot')) is not int):
            return {'verified':False,'reason':'No account-owned native activation receipt'}
        expected=p.get('home_expected')
        if expected is None:
            f=self.s.capture.screenshot();active=self.i.reader.active_slot(f)
            if active is None:
                if not self.i.open_editor():return {'verified':False,'reason':'Native editor did not open for verification'}
                f=self.s.capture.screenshot();active=self.i.reader.active_slot(f)
            if active!=p['slot'] or self.i.reader.active_slot(self.s.capture.screenshot())!=active:
                if active is not None:self.i.close()
                self.record(stage='importing',dirty=True)
                return {'verified':False,'reason':'Native active layout changed; import must be retried'}
            preview=active_preview(f,active)
            expected=signature(preview,self.stop) if preview is not None else None
            if expected is None:
                self.i.close()
                return {'verified':False,'reason':'Active preview geometry is unverified'}
            p['home_expected']=expected;write(self.i.path,state)
        f=self.s.capture.screenshot()
        if self.i.reader.active_slot(f) is not None:
            if not self.i.close():return {'verified':False,'reason':'Could not close the verified editor'}
        if self.stop() or not self.home():return {'verified':False,'reason':'Home is not ready'}
        # Pinching changes only the Home camera, after Home HUD verification.
        # It prevents a zoomed-in village from hiding most of the arrangement.
        from coc_bot.adb.multitouch import Multitouch
        f=self.s.capture.screenshot()
        with Multitouch(self.s.client,(f.shape[1],f.shape[0])) as touch:
            touch.pinch(start_span=.40,end_span=.10,duration=.8)
        if self.wait(.5):return {'verified':False,'reason':'Stopped during Home verification'}
        results=[]
        for _ in range(2):
            f=self.s.capture.screenshot()
            actual=signature(f,self.stop,home=True)
            results.append(compare(expected,actual))
            if self.stop():return {'verified':False,'reason':'Stopped during Home verification'}
        if (time.time()-p.get('activated_at',time.time())>90
            and all(v.get('cells',0)>=128 and v.get('correlation',1)<.75 for v in results)):
            # A settled, clearly different village must be reimported. Keep a
            # short grace for delayed native application rather than repeating
            # the same import immediately after an optimistic green badge.
            self.record(stage='importing',dirty=True)
        return {'verified':all(v['verified'] for v in results),'observations':results}

    def _finish_verification(self,hall,count):
        result=self._verify_active_home(hall)
        state=read(self.i.path,{})
        if state.get('completed'):
            state['completed'].update(home_verified=bool(result.get('verified')),home_verification=result,
                                      home_verified_at=time.time() if result.get('verified') else None)
            write(self.i.path,state)
        if not result.get('verified'):
            self.record(last_verification=result)
            return {'status':'verifying','message':'The active preview must match the real Home village','verification':result}
        self.record(stage='active',hall=hall,revision=REVISION,dirty=False,
                    next_check_at=time.time()+3600,activated_at=time.time())
        return {'status':'active','placed_this_visit':count,'home_verified':True}

    def exhausted_reference(self,url,hall):
        """Resurvey once, then try another reference instead of looping forever."""
        state=read(self.i.path,{});automatic=state.get('automatic',{})
        retry={'link':url,'last_removal_at':automatic.get('last_removal_at',0)}
        if not automatic.get('cleared_at') and automatic.get('fit_retry')!=retry:
            self.record(stage='clearing',fit_retry=retry,survey_cursor=0,survey_rejected=[],clearance_pass=True)
            return
        failed=list(automatic.get('unfit_references',[]))
        if url not in failed:failed.append(url)
        remaining=[official_layout(v['link'],hall) for v in catalog(hall) if v.get('link')]
        remaining=[link for link in remaining if link not in failed]
        self.record(stage='matching' if remaining else 'needs_reference',selected_reference=None,
                    unfit_references=failed,fit_retry=None,clearance_pass=False)

    def _place(self,url,hall,deadline):
        state=read(self.i.path,{})
        # An empty resurvey changes no geometry. Reimport only after an actual
        # removal (or construction/revision change), not after every survey.
        clearance=state.get('automatic',{}).get('last_removal_at',0)
        if (state.get('draft') and state['draft'].get('automatic_revision')==REVISION
            and state['draft'].get('hall')==hall and state['draft'].get('link')==url
            and (state['draft'].get('saved_at',0)>clearance or state['draft'].get('placements'))):
            draft=state['draft']
            if (draft.get('account')==self.s.config.account_tag
                and draft.get('ground_invalidated_at',0)<clearance):
                # Red floors were true before the obstacle disappeared. Keep
                # confirmed placements and measured sizes, but reconsider the
                # newly freed ground rather than caching it as occupied forever.
                for group in draft.get('failed_ground',[]):group['tiles']=[]
                draft.update(placement_view=0,ground_invalidated_at=clearance)
                write(self.i.path,state)
            if not self.i.resume_draft(chooser_url=url,replace_inactive=self.s.config.layouts_replace_inactive):
                return {'status':'needs_review','message':'Saved inactive draft could not be verified'}
        elif not self._open(url,hall):return {'status':'blocked'}
        return self._place_open(url,hall,deadline)

    def _import(self,url,hall,deadline):
        """Native import tests the actual account inventory, including merged defenses."""
        if not self._open(url,hall):return {'status':'blocked','message':'Native copy could not be opened'}
        if (self.i.reader.ready_save(self.s.capture.screenshot())
            and self.i.reader.ready_save(self.s.capture.screenshot())):
            return self._activate_complete(hall,0)
        from coc_bot.layouts.compatibility import assess_remaining
        assessment=assess_remaining(self.i)
        if assessment is None:
            assessment={'count':None,'small':False,'unreadable':True}
        automatic=read(self.i.path,{}).get('automatic',{})
        results=dict(automatic.get('compatibility',{}));results[url]=assessment
        self.record(compatibility=results)
        logger.info('Layout compatibility: remaining={}, small={}, readable={}',
                    assessment['count'],assessment['small'],not assessment.get('unreadable',False))
        if automatic.get('selected_reference')==url and (assessment['small'] or assessment.get('probe')):
            state=read(self.i.path,{})
            state['pending']['bounded_trial']=bool(assessment.get('probe'))
            write(self.i.path,state)
            self.record(stage='placing',reference=url)
            return self._place_open(url,hall,deadline)
        if not self.close_unsaved():return {'status':'needs_review'}
        self.record(stage='matching',selected_reference=None)
        return {'status':'matching','remaining':assessment['count'],'small_difference':assessment['small']}

    def _place_open(self,url,hall,deadline):
        state=read(self.i.path,{});state['pending']['automatic_revision']=REVISION
        write(self.i.path,state)
        centers=((33,33),(11,33),(33,11),(11,11),(22,22))
        cursor=read(self.i.path,{}).get('pending',{}).get('placement_view',0)
        if type(cursor) is not int or not 0<=cursor<len(centers):cursor=0
        if self.reframe(centers[cursor]) is None:return {'status':'needs_geometry'}
        deadline=max(deadline,time.monotonic()+30)
        count=0
        reframes=iter(enumerate(centers[cursor+1:],cursor+1))
        while not self.stop() and time.monotonic()<deadline:
            if not self.i.show_tools():return {'status':'stopped'}
            f=self.s.capture.screenshot()
            if self.i.reader.ready_save(f) and self.i.reader.ready_save(self.s.capture.screenshot()):
                return self._activate_complete(hall,count)
            from coc_bot.layouts.compatibility import MAX_REMAINDER
            pending=read(self.i.path,{}).get('pending',{})
            if len(pending.get('placements',[]))>=MAX_REMAINDER:
                self.exhausted_reference(url,hall)
                return {'status':'candidate_incomplete','message':'Six-placement limit reached without native completion; original base retained'}
            result=InventoryPlacer(self.i).one()
            if result['status']=='probed':continue
            if result['status']!='placed':
                if result['status']=='unreadable_inventory' and pending.get('bounded_trial'):
                    self.exhausted_reference(url,hall)
                    return {'status':'candidate_incomplete','message':'Trial reached unknown inventory without native completion; trying another reference'}
                if result['status']=='no_spare_ground' and not read(self.i.path,{}).get('pending',{}).get('placement'):
                    target=next(reframes,None)
                    if target is not None:
                        latest=read(self.i.path,{})
                        latest['pending']['placement_view']=target[0];write(self.i.path,latest)
                        if self.reframe(target[1]) is not None:continue
                        result={'status':'needs_geometry'}
                # Uncertain placement keeps its journal. The next run discards
                # only the inactive unsaved copy before reconstructing it.
                if result['status']=='no_spare_ground':
                    latest=read(self.i.path,{})
                    if latest.get('pending'):
                        latest['pending']['placement_view']=0;write(self.i.path,latest)
                    self.exhausted_reference(url,hall)
                if (count or result['status']=='no_spare_ground') and not read(self.i.path,{}).get('pending',{}).get('placement'):
                    # Keep already receipted moves when the next camera read or
                    # tray item is unreadable. Never save an uncertain drag.
                    if self.i.save_draft() and self.i.close():
                        return {'status':'draft','placed_this_visit':count,'retry_reason':result['status']}
                return result
            count+=1
            if result.get('native_complete'):
                # The final item can finish at the visit deadline. Its native
                # Save must not be mistaken for incomplete Finish later.
                return self._activate_complete(hall,count)
        if not self.stop() and self.i.save_draft():
            if not self.i.close():return {'status':'needs_review'}
            return {'status':'draft','placed_this_visit':count}
        return {'status':'stopped'}

    def remember_removal(self):
        latest=read(self.i.path,{})
        receipt=latest.get('last_survey',{}).get('payment_receipt')
        if not receipt:return
        journal=latest.setdefault('automatic',{})
        history=journal.get('removals',[])
        if not any(v.get('operation')==receipt.get('operation') for v in history):
            journal['removals']=(history+[receipt])[-128:]
        journal['last_removal_at']=receipt['at']
        # Clearing is a complete pass, never one removal followed by fitting.
        journal.update(stage='clearing',clearance_pass=True,cleared_at=0,dirty=True,
                       compatibility={},selected_reference=None)
        # Let an obstacle's reward finish before reading the starting balance
        # for another payment. A prior seasonal reward can fill storage and
        # otherwise hide the exact deduction of the next obstacle.
        journal['removal_settle_until']=(receipt['finished_at']+3 if receipt.get('finished_at') else receipt['at']+90)
        write(self.i.path,latest)

    def run(self,seconds=120):
        config=self.s.config;state=read(self.i.path,{})
        if self.stop():return {'status':'stopped'}
        if state.get('pending') or state.get('last_survey',{}).get('payment'):
            recovered=self.recover()
            if recovered:self.remember_removal()
            return {'status':'recovered' if recovered else 'needs_review'}
        if config.dry_run or not config.layouts_enabled:return {'status':'disabled'}
        hall=config.account_town_hall
        if type(hall) is not int or not 2<=hall<=18:
            return {'status':'unavailable','message':'A verified Town Hall is required'}
        choices=[v for v in catalog(hall) if v.get('link')]
        if not choices:
            # Remember the checked Hall even without an editor. Otherwise the
            # scheduler retries an unsupported starter Hall on every idle loop.
            # A later verified Hall change bypasses this Hall-specific cooldown.
            self.record(hall=hall,revision=REVISION,stage='unavailable',last_status='unavailable',
                        next_check_at=time.time()+3600)
            return {'status':'unavailable','message':'Native layout copy/editor is unavailable at this Town Hall; leaving the base unchanged'}
        automatic=state.get('automatic',{})
        if time.time()<automatic.get('removal_settle_until',0):
            return {'status':'waiting','message':'Waiting for the previous obstacle removal and reward to settle'}
        # A policy change must not dismantle an already verified active village.
        if (automatic.get('stage')=='active' and automatic.get('hall')==hall
            and not automatic.get('dirty') and state.get('completed',{}).get('home_verified')
            and state['completed'].get('account')==config.account_tag
            and state['completed'].get('hall')==hall):
            self.record(revision=REVISION)
            automatic=read(self.i.path,{}).get('automatic',{})
        new_reference=automatic.get('hall')!=hall or automatic.get('revision')!=REVISION
        if (automatic.get('stage')=='active' and automatic.get('hall')==hall
            and automatic.get('revision')==REVISION and not automatic.get('dirty')):
            complete=state.get('completed',{})
            if complete.get('home_verified') and time.time()-complete.get('home_verified_at',0)<3600:
                return {'status':'current'}
            self.record(stage='verifying',dirty=True)
            return self._finish_verification(hall,0)
        if not new_reference and time.time()<automatic.get('next_check_at',0):return {'status':'waiting'}
        if not config.progression_clear_obstacles:return {'status':'disabled','message':'Enable build-zone obstacle clearing'}
        # Import receipts contain canonical URL encoding. Compare and resume
        # that same reference rather than restarting because ':' became %3A.
        failed=[] if new_reference else automatic.get('unfit_references',[])
        links=[official_layout(v['link'],hall) for v in choices]
        links=[link for link in links if link not in failed]
        if not links:return {'status':'unavailable','message':'The available layouts could not fit this inventory; the active base is unchanged'}
        url=links[0]
        self.record(**({'stage':'clearing','dirty':True,'survey_cursor':0,'survey_rejected':[],
                        'survey_started_at':0,'unfit_references':[],'fit_retry':None,'clearance_pass':True,
                        'cleared_at':0,'compatibility':{},'selected_reference':None} if new_reference else {}),hall=hall,revision=REVISION)
        deadline=time.monotonic()+max(30,min(300,seconds))
        result={'status':'blocked'}
        try:
            stage=read(self.i.path,{}).get('automatic',{}).get('stage','importing')
            if new_reference:stage='clearing'
            cleared=read(self.i.path,{}).get('automatic',{}).get('cleared_at',0)
            if stage in ('importing','placing','matching') and (not cleared or time.time()-cleared>86400):
                stage='clearing';self.record(stage=stage,clearance_pass=True,survey_cursor=0,survey_rejected=[],survey_started_at=0)
            if stage=='needs_reference':
                results=read(self.i.path,{}).get('automatic',{}).get('compatibility',{})
                if any(link not in results for link in links):
                    stage='matching';self.record(stage=stage)
                    if not cleared or time.time()-cleared>86400:
                        stage='clearing';self.record(stage=stage,clearance_pass=True,survey_cursor=0,survey_rejected=[],survey_started_at=0)
            if stage in ('matching','importing'):
                automatic=read(self.i.path,{}).get('automatic',{})
                results=automatic.get('compatibility',{})
                pending=[link for link in links if link not in results]
                if pending:url=pending[0]
                else:
                    candidates=[link for link in links if results.get(link,{}).get('small') or results.get(link,{}).get('probe')]
                    if not candidates and any(v.get('unreadable') for v in results.values()):
                        self.record(stage='matching',compatibility={k:v for k,v in results.items() if not v.get('unreadable')})
                        result={'status':'unreadable_inventory','message':'Some candidate inventories could not be read; retrying them without placing'}
                        return result
                    if not candidates:
                        self.record(stage='needs_reference')
                        result={'status':'needs_reference','message':'No compatible copy: remaining inventory exceeds the small-placement limit; original base retained'}
                        return result
                    url=min(candidates,key=lambda link:(not results[link].get('small'),results[link]['count']))
                    self.record(selected_reference=url)
                stage='importing'
            elif stage=='placing':
                chosen=read(self.i.path,{}).get('automatic',{}).get('selected_reference')
                if chosen in links:url=chosen
                else:
                    stage='matching';self.record(stage=stage)
            if stage=='verifying':result=self._finish_verification(hall,0)
            elif stage=='importing':result=self._import(url,hall,deadline)
            elif stage=='placing':result=self._place(url,hall,deadline)
            elif stage=='matching':result={'status':'matching'}
            elif stage=='needs_reference':result={'status':'needs_reference','message':'A compatible layout is needed'}
            else:
                removed=0
                while not self.stop():
                    result=self._clear_one(url,hall,deadline)
                    if result.get('status')!='making_room':break
                    self.remember_removal();removed+=1
                    if removed>=1 or time.monotonic()+45>deadline:break
                if removed:result['removed_this_visit']=removed
            return result
        finally:
            state=read(self.i.path,{})
            p=state.get('pending',{})
            # Do not throw away an uncertain payment. Native draft saves and
            # completed removals have already closed their editor themselves.
            if p and not p.get('payment') and not self.stop():
                if not self.close_unsaved():result.update(status='needs_review')
            cooldown=(86400 if result.get('status')=='active' else
                      30 if result.get('status') in ('making_room','cleared','draft','matching') else 180)
            if config.donation_enabled:cooldown=max(300,cooldown)
            self.record(last_status=result.get('status'),next_check_at=time.time()+cooldown)
            if not self.stop() and not read(self.i.path,{}).get('pending'):
                if config.donation_enabled:self.s.navigator.ensure_clan_chat()
                else:self.home()
