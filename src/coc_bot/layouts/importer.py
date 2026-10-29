"""Native layout import preserving the active Home Village slot."""
from pathlib import Path
from copy import deepcopy
import shlex
import time

import cv2
import numpy as np

from coc_bot.accounts.store import read,write,backup
from coc_bot.builder_base.vision import BuilderReader
from coc_bot.layouts.catalog import official_layout
from coc_bot.upgrades.vision import compact


def verify_owner(session,stop):
    """Short-lived proof on this device-owner session, never persisted to disk.

    A new controller/account visit creates a new session. Manual control cannot
    coexist with its device lease, so repeated editor visits need not reopen
    Profile and Settings for every individual obstacle.
    """
    expected=session.config.account_tag
    if not expected:raise ValueError('Save and verify this account before automatic layout work')
    proof=getattr(session,'_layout_owner_proof',None)
    if isinstance(proof,tuple) and len(proof)==2 and proof[0]==expected and 0<=time.monotonic()-proof[1]<480:
        return
    from coc_bot.accounts.navigation import verify_session
    verify_session(session,stop)
    if not stop():session._layout_owner_proof=(expected,time.monotonic())


class LayoutReader(BuilderReader):
    def __init__(self,stop=None):
        super().__init__(stop)
        self.templates={p.stem:cv2.imread(str(p)) for p in Path(__file__).with_name('assets').glob('*.png')}

    def import_arrow(self,frame,box):
        """The import arrow stretches as it bobs; thumbnail artwork is irrelevant."""
        from coc_bot.upgrades.vision import crop
        ref=self.templates.get('import_arrow')
        if ref is None:return False
        def mask(image):return cv2.inRange(cv2.cvtColor(image,cv2.COLOR_BGR2HSV),(10,145,180),(36,255,255))
        def shape(contour,canvas):
            x,y,w,h=cv2.boundingRect(contour);filled=np.zeros(canvas.shape,np.uint8)
            cv2.drawContours(filled,[contour],-1,255,-1)
            return cv2.resize(filled[y:y+h,x:x+w],(96,96),interpolation=cv2.INTER_NEAREST)>0
        reference=mask(ref);contours,_=cv2.findContours(reference,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        if not contours:return False
        expected=shape(max(contours,key=cv2.contourArea),reference)
        region=crop(cv2.resize(frame,(1853,1048)),box);orange=mask(region)
        contours,_=cv2.findContours(orange,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            x,y,w,h=cv2.boundingRect(contour)
            if not 70<=w<=150 or not 60<=h<=130 or cv2.contourArea(contour)<4000:continue
            observed=shape(contour,orange)
            if (observed&expected).sum()/(observed|expected).sum()>=.93:return True
        return False

    def empty_slot(self,frame,*,replace_inactive=False,exclude_slots=()):
        if not isinstance(exclude_slots,(tuple,list,set)) or any(type(v) is not int or not 0<=v<3 for v in exclude_slots):
            raise ValueError('Invalid protected layout slot')
        if not (self.find(frame,'editor_title',(.33,.015,.67,.14),threshold=.96)
                and self.find(frame,'import_prompt',(.29,.76,.72,.85),threshold=.96)
                and self.find(frame,'home_tab',(.25,.17,.46,.25),threshold=.96)):
            return None
        active=[];empty=[]
        mask=cv2.inRange(cv2.cvtColor(cv2.resize(frame,(1853,1048)),cv2.COLOR_BGR2HSV),
                         (30,70,190),(90,255,255))>0
        for index,(a,b) in enumerate(((.03,.34),(.357,.64),(.67,.95))):
            left=(48,627,1206)[index];right=left+590
            # The active slot's continuous lime border is independent of the
            # scenery and the optional Ranked Defense line moving its caption.
            horizontal=mask[338:355,left+20:right-20].mean(axis=1).max()
            vertical=mask[380:700,left:left+12].mean(axis=0).max()
            if horizontal>.9 and vertical>.9:active.append(index)
            if self.find(frame,'empty_slot',(a,.49,b,.69),threshold=.98):empty.append(index)
        if len(active)!=1:return None
        chosen=next((i for i in empty if i!=active[0] and i not in exclude_slots),None)
        replacing=False
        if chosen is None and replace_inactive:
            # Replacement is explicitly opt-in. The import arrow must verify
            # the owned slot itself; unknown/locked thumbnails never qualify.
            for i,(a,b) in enumerate(((.03,.34),(.357,.64),(.67,.95))):
                if i!=active[0] and i not in exclude_slots and self.import_arrow(frame,(a,.37,b,.52)):
                    chosen=i;replacing=True;break
        if chosen is None:return None
        result={'slot':chosen,'original_slot':active[0],
                'point':(round(frame.shape[1]*(.185,.498,.811)[chosen]),round(frame.shape[0]*.53))}
        return result|{'replacing':True} if replacing else result

    def inventory_notice(self,frame):
        if (self.find(frame,'edit_notice_title',(.32,.25,.68,.35),threshold=.96)
            and (self.find(frame,'edit_notice_message',(.27,.37,.73,.54),threshold=.96)
                 or self.find(frame,'edit_obstacle_notice_message',(.27,.37,.73,.54),threshold=.96))):
            return self.find(frame,'edit_okay',(.43,.59,.56,.68),threshold=.96)
        return None

    def editing(self,frame):
        ref=self.templates.get('edit_title')
        if ref is None or not isinstance(frame,np.ndarray):return False
        image=cv2.resize(frame,(1853,1048))[:94,:519]
        def white(value):return cv2.inRange(cv2.cvtColor(value,cv2.COLOR_BGR2HSV),(0,0,205),(180,80,255))
        # The heading is drawn over the village. Compare its lettering, not the
        # changing scenery/buildings behind it; dimmed headings do not qualify.
        reference=white(ref)
        if np.count_nonzero(reference)<30 or reference.std()<1:return False
        return cv2.minMaxLoc(cv2.matchTemplate(white(image),reference,cv2.TM_CCOEFF_NORMED))[1]>=.97

    def idle_editor(self,frame):
        """Positive native no-selection proof before tapping the lower map."""
        if not self.editing(frame):return False
        ref=self.templates.get('edit_idle_instruction')
        if ref is None:return False
        image=cv2.resize(frame,(1853,1048))[730:824,500:1350]
        def white(value):return cv2.inRange(cv2.cvtColor(value,cv2.COLOR_BGR2HSV),(0,0,205),(180,80,255))
        letters=white(ref)
        # Compare every letter and its immediate dark border. An obstacle may
        # appear behind the gaps between words; that background is not part of
        # the instruction. A solid white area cannot match the dark borders.
        mask=cv2.dilate(letters,np.ones((5,5),np.uint8))
        scores=cv2.matchTemplate(white(image),letters,cv2.TM_CCORR_NORMED,mask=mask)
        scores=np.nan_to_num(scores,nan=0,posinf=0,neginf=0)
        return float(scores.max())>=.985

    def editor_chat_close(self,frame):
        # The drawer hides the editor heading. Require two independent native
        # editor controls before using its exact orange close-arrow artwork.
        if (not self.find(frame,'remove_all',(.83,.11,.99,.19),threshold=.97)
            or not self.find(frame,'edit_cancel',(.83,.66,.99,.75),threshold=.97)):
            return None
        return self.find(frame,'editor_chat_close',(.37,.36,.44,.56),threshold=.98)

    def home_editor(self,frame):
        from coc_bot.vision.battle_menu import home_build_control_visible
        if not home_build_control_visible(frame):return None
        return self.find(frame,'home_editor',(.21,.86,.44,.99),threshold=.97)

    def builder_editor(self,frame):
        from coc_bot.upgrades.vision import UpgradeReader
        if UpgradeReader(self.stop).menu_kind(frame) is None:return None
        return self.find(frame,'builder_editor',(.62,.70,.73,.88),threshold=.97)

    def edit_layout(self,frame):
        if self.selected_slot(frame) is None:return None
        from coc_bot.upgrades.vision import crop
        green=cv2.inRange(cv2.cvtColor(crop(frame,(.245,.87,.394,.974)),cv2.COLOR_BGR2HSV),
                          (30,70,140),(90,255,255)).mean()/255
        if green<.35:return None
        return self.find(frame,'edit_layout',(.25,.895,.39,.945),threshold=.97)

    def thumbnail(self,frame,slot):
        if type(slot) is not int or not 0<=slot<3 or self.selected_slot(frame)!=slot:return None
        image=cv2.resize(frame,(1853,1048));left=(48,627,1206)[slot]
        art=cv2.resize(cv2.cvtColor(image[475:690,left+60:left+530],cv2.COLOR_BGR2GRAY),(64,32),interpolation=cv2.INTER_AREA)
        return art.tolist() if art.std()>8 else None

    def draft_button(self,frame):
        if not self.editing(frame):return None
        # The native editor explicitly offers Finish later for an incomplete
        # layout. Do not translate that into a ready/active village.
        point=self.find(frame,'finish_later',(.83,.57,.99,.65),threshold=.96)
        return point if point and self.find(frame,'edit_cancel',(.84,.66,.98,.75),threshold=.96) else None

    def collapsed_tools(self,frame):
        if not self.editing(frame) or self.find(frame,'edit_cancel',(.84,.66,.98,.75),threshold=.96):return None
        return self.find(frame,'collapsed_tools',(.90,.35,1,.65),threshold=.97)

    def remove_all_button(self,frame):
        if not self.editing(frame) or not self.find(frame,'edit_cancel',(.84,.66,.98,.75),threshold=.96):return None
        from coc_bot.upgrades.vision import crop
        green=cv2.inRange(cv2.cvtColor(crop(frame,(.825,.12,.985,.18)),cv2.COLOR_BGR2HSV),
                          (30,70,140),(90,255,255)).mean()/255
        if green<.35:return None
        return self.find(frame,'remove_all',(.85,.12,.98,.18),threshold=.97)

    def collect_all_confirmation(self,frame):
        if (self.find(frame,'collect_all_title',(.40,.26,.60,.35),threshold=.97)
            and self.find(frame,'collect_all_message',(.28,.42,.72,.50),threshold=.97)):
            return self.find(frame,'collect_all_okay',(.55,.60,.66,.69),threshold=.97)
        return None

    def collect_all_cancel(self,frame):
        if self.collect_all_confirmation(frame) is None:return None
        return self.find(frame,'collect_all_cancel',(.29,.57,.49,.73),threshold=.97)

    def active_slot(self,frame):
        if not (self.find(frame,'editor_title',(.33,.015,.67,.14),threshold=.96)
                and self.find(frame,'home_tab',(.25,.17,.46,.25),threshold=.96)):
            return None
        if self.find(frame,'import_prompt',(.29,.76,.72,.85),threshold=.96):
            # Import arrows can cover the Active Village lettering. Only this
            # verified import chooser permits its independent continuous rim
            # as the active-slot receipt; normal chooser checks use lettering.
            image=cv2.resize(frame,(1853,1048))
            mask=cv2.inRange(cv2.cvtColor(image,cv2.COLOR_BGR2HSV),(30,70,190),(90,255,255))>0
            found=[]
            for index,left in enumerate((48,627,1206)):
                right=left+590
                if (mask[338:355,left+20:right-20].mean(axis=1).max()>.90
                    and mask[380:700,left:left+12].mean(axis=0).max()>.90):
                    found.append(index)
            return found[0] if len(found)==1 else None
        from coc_bot.upgrades.vision import crop
        references=[self.templates.get(name) for name in ('active_village','active_village_selected','active_village_ranked','active_village_ranked_selected')]
        references=[ref for ref in references if ref is not None]
        if not references:return None
        def letters(image):return cv2.inRange(cv2.cvtColor(image,cv2.COLOR_BGR2HSV),(30,150,200),(90,255,255))
        found=[]
        image=cv2.resize(frame,(1853,1048))
        for i,(a,b) in enumerate(((.03,.34),(.357,.64),(.67,.95))):
            # Selecting the active Ranked Defense card enlarges its thumbnail
            # and raises Active Village above the ordinary caption position.
            region=letters(crop(image,(a,.33,b,.44)))
            for reference in references:
                ref=letters(reference)
                if region.shape[0]>=ref.shape[0] and region.shape[1]>=ref.shape[1]:
                    if cv2.minMaxLoc(cv2.matchTemplate(region,ref,cv2.TM_CCOEFF_NORMED))[1]>=.97:
                        found.append(i);break
        return found[0] if len(found)==1 else None

    def discard_confirmation(self,frame):
        if (self.find(frame,'discard_title',(.36,.25,.65,.34),threshold=.97)
            and self.find(frame,'discard_message',(.28,.41,.72,.50),threshold=.97)):
            from coc_bot.upgrades.vision import crop
            green=cv2.inRange(cv2.cvtColor(crop(frame,(.52,.58,.70,.70)),cv2.COLOR_BGR2HSV),
                              (30,70,140),(90,255,255)).mean()/255
            if green>.35:return self.find(frame,'discard_okay',(.56,.61,.65,.69),threshold=.97)
        return None

    def ready_save(self,frame):
        from coc_bot.upgrades.vision import crop
        if not self.editing(frame) or not self.find(frame,'edit_cancel',(.84,.66,.98,.75),threshold=.96):return None
        green=cv2.inRange(cv2.cvtColor(crop(frame,(.83,.58,.98,.64)),cv2.COLOR_BGR2HSV),
                          (30,70,140),(90,255,255)).mean()/255
        label=compact(self.white_text(crop(frame,(.86,.59,.97,.63))))
        return (round(frame.shape[1]*.91),round(frame.shape[0]*.61)) if green>.40 and label=='save' else None

    def selected_slot(self,frame):
        if self.active_slot(frame) is None:return None
        image=cv2.resize(frame,(1853,1048))
        white=cv2.inRange(cv2.cvtColor(image,cv2.COLOR_BGR2HSV),(0,0,190),(180,50,255))>0
        selected=[]
        for i,left in enumerate((80,627,1238)):
            right=left+590 if i==1 else left+520
            if white[338:363,left+20:right-20].mean(axis=1).max()>.90:
                selected.append(i)
        return selected[0] if len(selected)==1 else None

    def set_active(self,frame):
        from coc_bot.upgrades.vision import crop
        if self.selected_slot(frame) is None:return None
        green=cv2.inRange(cv2.cvtColor(crop(frame,(.607,.87,.756,.974)),cv2.COLOR_BGR2HSV),
                          (30,70,140),(90,255,255)).mean()/255
        label=compact(self.white_text(crop(frame,(.61,.895,.754,.945))))
        return (round(frame.shape[1]*.68),round(frame.shape[0]*.92)) if green>.35 and label=='setasactive' else None


def same_saved_layout(observed, expected):
    """Compare saved map art, excluding native status badges along its bottom.

    Obstacle badges can appear after a reload without any building moving.
    Keep the existing strict similarity and error limits on the upper 75%.
    """
    try:
        a=np.asarray(observed,dtype=float);b=np.asarray(expected,dtype=float)
    except (TypeError,ValueError):return False
    if a.shape!=(32,64) or b.shape!=(32,64):return False
    if not np.isfinite(a).all() or not np.isfinite(b).all():return False
    if (a<0).any() or (a>255).any() or (b<0).any() or (b>255).any():return False
    a=a[:24];b=b[:24]
    return bool(a.std()>8 and b.std()>8 and np.mean(np.abs(a-b))<=3
                and cv2.matchTemplate(a.astype(np.uint8),b.astype(np.uint8),cv2.TM_CCOEFF_NORMED)[0,0]>=.995)


class LayoutImporter:
    def __init__(self,session,stop=lambda:False):
        self.s=session;self.stop=stop;self.reader=LayoutReader(stop)
        self.path=session.config.data_dir/'layouts/state.json'

    def dismiss_editor_chat(self):
        from coc_bot.stop import interrupted_sleep
        if self.stop():return False
        point=self.reader.editor_chat_close(self.s.capture.screenshot())
        if not isinstance(point,tuple) or len(point)!=2:return True
        if self.stop() or self.reader.editor_chat_close(self.s.capture.screenshot())!=point:return False
        self.s.input.tap(*point,jitter=0)
        if interrupted_sleep(.4,self.stop):return False
        return self.reader.editing(self.s.capture.screenshot()) is True

    def show_tools(self):
        from coc_bot.stop import interrupted_sleep
        if self.stop():return False
        if not self.dismiss_editor_chat():return False
        point=self.reader.collapsed_tools(self.s.capture.screenshot())
        if not isinstance(point,tuple) or len(point)!=2:return True
        if self.stop() or self.reader.collapsed_tools(self.s.capture.screenshot())!=point:return False
        self.s.input.tap(*point,jitter=0)
        return not interrupted_sleep(.4,self.stop)

    def open_editor(self):
        """Open the native chooser without importing or replacing any slot."""
        from coc_bot.accounts.navigation import verify_session
        from coc_bot.progression.home import ensure_home
        from coc_bot.stop import interrupted_sleep
        if read(self.path,{}).get('pending'):
            raise ValueError('An unfinished native layout operation must be recovered first')
        if self.stop():return False
        verify_owner(self.s,self.stop)
        if not ensure_home(self.s.navigator) or self.stop():return False
        # Use the current native Builder Menu hand button first. The legacy
        # Home shortcut can leave an orange loading overlay on this game UI.
        from coc_bot.upgrades.runner import UpgradeRunner
        r=UpgradeRunner(self.s.config,self.s.capture,self.s.input,self.s.navigator,self.stop)
        frame=r.open_menu('buildings')
        if frame is None:return False
        first=self.reader.builder_editor(frame)
        if (first is None or self.stop()
            or self.reader.builder_editor(self.s.capture.screenshot())!=first):return False
        self.s.input.tap(*first,jitter=0)
        for _ in range(12):
            if self.stop():return False
            frame=self.s.capture.screenshot();active=self.reader.active_slot(frame)
            if active is not None and self.reader.active_slot(self.s.capture.screenshot())==active:return True
            if interrupted_sleep(.4,self.stop):return False
        return False

    def open_survey(self,hall,resources):
        """Edit and discard an inactive native slot without importing a layout."""
        from coc_bot.stop import interrupted_sleep
        if self.stop():return False
        if self.s.config.dry_run or self.s.config.account_town_hall!=hall:
            raise ValueError('Survey requires a live verified account and Hall')
        state=read(self.path,{})
        if state.get('pending'):raise ValueError('Recover the prior layout operation first')
        draft=state.get('draft',{})
        protected=draft.get('slot') if draft.get('account')==self.s.config.account_tag else None
        if not self.open_editor():return False
        frame=self.s.capture.screenshot();original=self.reader.active_slot(frame)
        if original is None or self.reader.active_slot(self.s.capture.screenshot())!=original:return False
        for slot in range(3):
            if slot in (original,protected) or self.stop():continue
            self.s.input.tap(round(frame.shape[1]*(.185,.498,.811)[slot]),round(frame.shape[0]*.53),jitter=0)
            if interrupted_sleep(.5,self.stop):return False
            first=self.s.capture.screenshot();second=self.s.capture.screenshot()
            point=self.reader.edit_layout(first)
            if (not point or self.reader.edit_layout(second)!=point
                or self.reader.selected_slot(first)!=slot or self.reader.selected_slot(second)!=slot
                or self.reader.active_slot(first)!=original or self.reader.active_slot(second)!=original):continue
            snapshot=backup(self.s.config.data_dir.parent)
            state=read(self.path,{})
            state['pending']={'account':self.s.config.account_tag,'hall':hall,'slot':slot,
                'original_slot':original,'phase':'copying_to_empty_slot','backup':str(snapshot),
                'home_resources':resources,'purpose':'clear_build_zone','at':time.time()}
            write(self.path,state)
            if self.stop():return False
            self.s.input.tap(*point,jitter=0)
            if interrupted_sleep(.6,self.stop):return False
            # Existing inactive layouts can also open with the obstacle notice.
            # Its dimmed editor heading must not count as a ready editor.
            for _ in range(12):
                if self.stop():return False
                frame=self.s.capture.screenshot()
                notice=self.reader.inventory_notice(frame)
                if isinstance(notice,tuple) and len(notice)==2:
                    if self.stop() or self.reader.inventory_notice(self.s.capture.screenshot())!=notice:return False
                    self.s.input.tap(*notice,jitter=0)
                elif (self.reader.editing(frame)
                      and self.reader.editing(self.s.capture.screenshot())):return True
                if interrupted_sleep(.4,self.stop):return False
            return False
        self.close()
        return False

    def open_via_spare_copy(self,url,hall,*,protected_slot,replace_inactive=False):
        """Reach the chooser through an expendable copy, retaining a working draft.

        Some native Home entry requests stall while copy links still work. This
        path requires a second inactive slot. It may replace that slot only with
        explicit authorization, then discards its unsaved edit before returning.
        """
        if type(protected_slot) is not int or not 0<=protected_slot<3:
            raise ValueError('A protected draft slot is required')
        if not self.open(url,hall):return False
        if not self.select_empty(replace_inactive=replace_inactive,exclude_slots=(protected_slot,)):return False
        from coc_bot.stop import interrupted_sleep
        point=self.reader.inventory_notice(self.s.capture.screenshot())
        if point:
            if self.stop() or self.reader.inventory_notice(self.s.capture.screenshot())!=point:return False
            self.s.input.tap(*point,jitter=0)
            if interrupted_sleep(.5,self.stop):return False
        if not self.cancel_obstacle_survey():return False
        return self.reader.active_slot(self.s.capture.screenshot()) is not None

    def resume_draft(self,*,chooser_url=None,replace_inactive=False):
        """Reopen the same owned inactive copy; a link import would overwrite it."""
        from coc_bot.stop import interrupted_sleep
        if getattr(self.s.config,'dry_run',False):raise ValueError('Native layout editing is disabled in practice mode')
        state=read(self.path,{});draft=state.get('draft',{})
        slot,original=draft.get('slot'),draft.get('original_slot')
        try:expected=np.asarray(draft.get('thumbnail'),dtype=float)
        except (TypeError,ValueError) as error:raise ValueError('Invalid draft thumbnail') from error
        if (state.get('pending') or draft.get('account')!=self.s.config.account_tag
            or draft.get('hall')!=self.s.config.account_town_hall or not draft.get('backup')
            or type(slot) is not int or type(original) is not int or not 0<=slot<3
            or not 0<=original<3 or slot==original or expected.shape!=(32,64)
            or not np.isfinite(expected).all() or (expected<0).any() or (expected>255).any()
            or (expected!=np.floor(expected)).any()
            or expected.std()<=8 or draft.get('placement') or draft.get('payment')):
            raise ValueError('No verified resumable inactive draft belongs to this account and Hall')
        expected=expected.astype(np.uint8)
        opened=self.open_editor()
        if not opened and chooser_url is not None:
            if not self.open_via_spare_copy(chooser_url,draft['hall'],protected_slot=slot,
                                           replace_inactive=replace_inactive):return False
            # The temporary import/cancel changed last_survey. Preserve its
            # receipt instead of writing this method's old snapshot over it.
            state=read(self.path,{})
            if state.get('draft')!=draft or state.get('pending'):return False
        elif not opened:return False
        frame=self.s.capture.screenshot()
        if self.reader.active_slot(frame)!=original or self.reader.active_slot(self.s.capture.screenshot())!=original:return False
        if self.stop():return False
        # Only select a thumbnail here. Editing requires its independent saved
        # image and enabled native Edit Layout control on two fresh frames.
        self.s.input.tap(round(frame.shape[1]*(.185,.498,.811)[slot]),round(frame.shape[0]*.53),jitter=0)
        if interrupted_sleep(.5,self.stop):return False
        point=None
        for _ in range(2):
            frame=self.s.capture.screenshot();observed=self.reader.thumbnail(frame,slot)
            if (observed is None or self.reader.active_slot(frame)!=original
                or not same_saved_layout(observed,expected)):return False
            current=self.reader.edit_layout(frame)
            if current is None or point is not None and current!=point:return False
            point=current
        if self.stop():return False
        checkpoint=deepcopy({k:v for k,v in draft.items() if k!='resume_checkpoint'})
        state['pending']=dict(draft,phase='resuming_draft',resumed_at=time.time(),resume_checkpoint=checkpoint);write(self.path,state)
        if self.stop():return False
        self.s.input.tap(*point,jitter=0)
        if interrupted_sleep(.6,self.stop):return False
        first=self.s.capture.screenshot();second=self.s.capture.screenshot()
        notice=self.reader.inventory_notice(first)
        if isinstance(notice,tuple) and len(notice)==2:
            # Obstacles can invalidate a saved draft between visits. Preserve
            # its native checkpoint and require a new clearance before placing.
            if self.stop() or self.reader.inventory_notice(second)!=notice:return False
            state.setdefault('automatic',{}).update(stage='clearing',cleared_at=0,
                clearance_pass=True,survey_cursor=0,survey_rejected=[],survey_started_at=0,
                compatibility={},selected_reference=None)
            write(self.path,state)
            self.cancel_obstacle_survey()
            return False
        if not self.reader.editing(first) or not self.reader.editing(second):return False
        state['pending']['phase']='copying_to_empty_slot';state.pop('draft');write(self.path,state)
        return True

    def open(self,url,hall):
        from coc_bot.accounts.navigation import verify_session
        from coc_bot.stop import interrupted_sleep
        if read(self.path,{}).get('pending'):raise ValueError('A layout import is unfinished; inspect it before starting another')
        if self.stop():return False
        if self.s.config.account_town_hall!=hall:raise ValueError('Layout Town Hall differs from the verified saved account')
        url=official_layout(url,hall)
        verify_owner(self.s,self.stop)
        if self.stop():return False
        snapshot=backup(self.s.config.data_dir.parent)
        state=read(self.path,{})
        state['pending']={'phase':'opening','account':self.s.config.account_tag,
                          'link':url,'hall':hall,'backup':str(snapshot),'at':time.time()}
        write(self.path,state)
        self.s.client.run_shell('am start -a android.intent.action.VIEW -d '+shlex.quote(url)+' '+shlex.quote(self.s.config.coc_package))
        interrupted_sleep(2,self.stop)
        return True

    def select_empty(self,*,replace_inactive=False,exclude_slots=()):
        from coc_bot.stop import interrupted_sleep
        state=read(self.path,{})
        pending=state.get('pending',{})
        if pending.get('phase')!='opening' or pending.get('account')!=self.s.config.account_tag:
            raise ValueError('Layout import does not belong to this verified operation')
        second=None
        # Opening a deep link can take longer than the fixed initial pause.
        # Wait for the exact chooser and two matching observations; an early
        # loading frame is not evidence that every inactive slot is occupied.
        for _ in range(12):
            if self.stop():return False
            first=self.reader.empty_slot(self.s.capture.screenshot(),replace_inactive=replace_inactive,exclude_slots=exclude_slots)
            if first is not None:
                fresh=self.reader.empty_slot(self.s.capture.screenshot(),replace_inactive=replace_inactive,exclude_slots=exclude_slots)
                if fresh==first:
                    second=fresh;break
            if interrupted_sleep(.5,self.stop):return False
        if second is None:raise ValueError('No verified inactive Home Village slot; no layout was replaced')
        if self.stop():return False
        pending.update(phase='copying_to_empty_slot',slot=second['slot'],original_slot=second['original_slot'],
                       replaced_inactive=second.get('replacing',False))
        write(self.path,state)
        self.s.input.tap(*second['point'],jitter=0)
        interrupted_sleep(1,self.stop)
        # Activation requires a separate inspection of the editor's saved state.
        return True

    def save_draft(self):
        from coc_bot.stop import interrupted_sleep
        state=read(self.path,{});pending=state.get('pending',{})
        if pending.get('account')!=self.s.config.account_tag or pending.get('phase') not in ('copying_to_empty_slot','saving_draft'):
            raise ValueError('No matching layout copy to save')
        slot,original=pending.get('slot'),pending.get('original_slot')
        if (type(slot) is not int or type(original) is not int or not 0<=slot<3
            or not 0<=original<3 or slot==original or not pending.get('backup')):
            raise ValueError('Draft save requires a backed-up inactive layout')
        if self.stop():return False
        if pending['phase']=='copying_to_empty_slot':
            point=self.reader.inventory_notice(self.s.capture.screenshot())
            if point:
                if self.reader.inventory_notice(self.s.capture.screenshot())!=point:return False
                if self.stop():return False
                pending['unplaced']=True;write(self.path,state)
                if self.stop():return False
                self.s.input.tap(*point,jitter=0)
                if interrupted_sleep(.5,self.stop):return False
            if not self.show_tools():return False
            first=self.reader.draft_button(self.s.capture.screenshot())
            second=self.reader.draft_button(self.s.capture.screenshot())
            if first is None or first!=second:raise ValueError('Native unfinished-layout save control is unverified')
            if self.stop():return False
            pending['phase']='saving_draft';write(self.path,state)
            if self.stop():return False
            self.s.input.tap(*second,jitter=0)
            if interrupted_sleep(1,self.stop):return False
        # The draft never replaces the original active village. A separate,
        # inspected activation is needed after all existing items are placed.
        frame=self.s.capture.screenshot()
        fresh=self.s.capture.screenshot()
        if (self.reader.active_slot(frame)!=pending['original_slot'] or
            self.reader.active_slot(fresh)!=pending['original_slot'] or
            self.reader.selected_slot(frame)!=pending['slot'] or
            self.reader.selected_slot(fresh)!=pending['slot']):
            raise ValueError('Draft save did not return to the Layout Editor; review before retrying')
        first=self.reader.thumbnail(frame,pending['slot']);second=self.reader.thumbnail(fresh,pending['slot'])
        if first is None or first!=second:
            raise ValueError('Inactive draft thumbnail did not settle; keep the checkpoint for review')
        pending['thumbnail']=second
        pending.pop('resume_checkpoint',None)
        pending.update(status='draft_needs_placement',saved_at=time.time())
        state['draft']=state.pop('pending');write(self.path,state)
        return True

    def expose_obstacles(self):
        """Stash buildings in this operation's inactive draft, never demolish them.

        This is a survey only. Obstacle removal needs an independently verified
        resource payment; an emptied editor is not a finished base layout.
        """
        from coc_bot.stop import interrupted_sleep
        state=read(self.path,{});pending=state.get('pending',{})
        slot,original=pending.get('slot'),pending.get('original_slot')
        if (pending.get('account')!=self.s.config.account_tag
            or pending.get('phase')!='copying_to_empty_slot'
            or type(slot) is not int or type(original) is not int
            or not 0<=slot<3 or not 0<=original<3 or slot==original
            or not pending.get('backup')):
            raise ValueError('Obstacle survey requires a backed-up, owned inactive layout')
        if self.stop():return False
        if not self.show_tools():return False
        first=self.reader.remove_all_button(self.s.capture.screenshot())
        if first is None or self.stop():return False
        second=self.reader.remove_all_button(self.s.capture.screenshot())
        if second!=first or self.stop():return False
        pending.update(phase='surveying_obstacles',survey_started_at=time.time())
        write(self.path,state)
        if self.stop():return False
        self.s.input.tap(*second,jitter=0)
        interrupted_sleep(.6,self.stop)
        return True

    def confirm_obstacle_survey(self):
        from coc_bot.stop import interrupted_sleep
        state=read(self.path,{});pending=state.get('pending',{})
        if (pending.get('account')!=self.s.config.account_tag
            or pending.get('phase')!='surveying_obstacles'
            or pending.get('survey_collected_at')
            or type(pending.get('slot')) is not int or type(pending.get('original_slot')) is not int
            or not 0<=pending['slot']<3 or not 0<=pending['original_slot']<3
            or pending['slot']==pending['original_slot'] or not pending.get('backup')):
            raise ValueError('No owned inactive-layout survey awaits confirmation')
        if self.stop():return False
        first=self.reader.collect_all_confirmation(self.s.capture.screenshot())
        if first is None or self.stop():return False
        second=self.reader.collect_all_confirmation(self.s.capture.screenshot())
        if second!=first or self.stop():return False
        pending['phase']='collecting_for_obstacle_survey';write(self.path,state)
        if self.stop():return False
        self.s.input.tap(*second,jitter=0)
        if interrupted_sleep(.6,self.stop):return False
        if not self.reader.editing(self.s.capture.screenshot()):return False
        pending.update(phase='surveying_obstacles',survey_collected_at=time.time());write(self.path,state)
        return True

    def cancel_obstacle_survey(self):
        """Discard the temporary edit; retain the checkpoint until active-slot proof."""
        from coc_bot.stop import interrupted_sleep
        state=read(self.path,{});pending=state.get('pending',{})
        if (pending.get('account')!=self.s.config.account_tag
            or pending.get('phase') not in ('surveying_obstacles','collecting_for_obstacle_survey','cancelling_obstacle_survey','copying_to_empty_slot','resuming_draft','saving_draft','saving_complete')
            or type(pending.get('original_slot')) is not int
            or not 0<=pending['original_slot']<3
            or type(pending.get('slot')) is not int or not 0<=pending['slot']<3
            or pending['slot']==pending['original_slot'] or not pending.get('backup')):
            raise ValueError('No owned inactive obstacle survey can be cancelled')
        if self.stop():return False
        if not self.dismiss_editor_chat():return False
        frame=self.s.capture.screenshot()
        # Stop can interrupt before Collect All or an unplaced-item notice is
        # dismissed. Cancel the collection dialog, or acknowledge the exact
        # informational notice, before touching editor controls behind it.
        for method in (self.reader.collect_all_cancel,self.reader.inventory_notice):
            point=method(frame)
            if isinstance(point,tuple) and len(point)==2:
                if self.stop() or method(self.s.capture.screenshot())!=point:return False
                self.s.input.tap(*point,jitter=0)
                if interrupted_sleep(.4,self.stop):return False
                frame=self.s.capture.screenshot()
        if self.reader.editing(frame):
            if not self.show_tools():return False
            frame=self.s.capture.screenshot()
        if self.reader.editing(frame):
            first=self.reader.find(frame,'edit_cancel',(.84,.66,.98,.75),threshold=.96)
            if first is None or self.stop():return False
            fresh=self.s.capture.screenshot()
            if (not self.reader.editing(fresh) or self.reader.find(fresh,'edit_cancel',(.84,.66,.98,.75),threshold=.96)!=first
                or self.stop()):return False
            pending['phase']='cancelling_obstacle_survey';write(self.path,state)
            if self.stop():return False
            self.s.input.tap(*first,jitter=0)
            if interrupted_sleep(.6,self.stop):return False
        close_attempts=0
        for _ in range(8):
            if self.stop():return False
            frame=self.s.capture.screenshot()
            discard=self.reader.discard_confirmation(frame)
            if isinstance(discard,tuple) and len(discard)==2 and not pending.get('discard_requested'):
                if self.reader.discard_confirmation(self.s.capture.screenshot())!=discard or self.stop():return False
                pending['discard_requested']=True;write(self.path,state)
                if self.stop():return False
                self.s.input.tap(*discard,jitter=0)
                if interrupted_sleep(.6,self.stop):return False
                continue
            # A selected building can consume the first Cancel to clear its
            # selection. Retry only the same verified native editor control;
            # never tap through a modal or resend a discard confirmation.
            if (close_attempts<1 and not pending.get('discard_requested')
                and self.reader.editing(frame) is True):
                point=self.reader.find(frame,'edit_cancel',(.84,.66,.98,.75),threshold=.96)
                fresh=self.s.capture.screenshot()
                if (isinstance(point,tuple) and len(point)==2 and self.reader.editing(fresh) is True
                    and self.reader.find(fresh,'edit_cancel',(.84,.66,.98,.75),threshold=.96)==point):
                    close_attempts+=1
                    if self.stop():return False
                    self.s.input.tap(*point,jitter=0)
                    if interrupted_sleep(.6,self.stop):return False
                    continue
            first=self.reader.active_slot(frame)
            if first==pending['original_slot']:
                if self.stop():return False
                second=self.reader.active_slot(self.s.capture.screenshot())
                if second==first and not self.stop():
                    state['last_survey']=state.pop('pending')|{'status':'cancelled','cancelled_at':time.time()}
                    prior=pending.get('resume_checkpoint')
                    # Cancelling a resumed edit restores the PREVIOUS native
                    # draft, not the unsaved moves made in this visit. Retain
                    # its exact checkpoint only when the thumbnail still agrees.
                    if (isinstance(prior,dict) and prior.get('account')==pending['account']
                        and prior.get('slot')==pending['slot'] and prior.get('original_slot')==pending['original_slot']):
                        expected=np.asarray(prior.get('thumbnail',[]),dtype=float)
                        observed=self.reader.thumbnail(self.s.capture.screenshot(),pending['slot'])
                        fresh=self.reader.thumbnail(self.s.capture.screenshot(),pending['slot'])
                        if (expected.shape==(32,64) and observed is not None and observed==fresh
                            and same_saved_layout(observed,expected)):
                            state['draft']=prior
                    write(self.path,state);return True
            if interrupted_sleep(.4,self.stop):return False
        return False

    def save_complete(self):
        from coc_bot.stop import interrupted_sleep
        state=read(self.path,{});p=state.get('pending',{})
        if (p.get('account')!=self.s.config.account_tag or p.get('phase')!='copying_to_empty_slot'
            or p.get('placement') or p.get('slot')==p.get('original_slot')):
            raise ValueError('Only a verified inactive copy can be saved for activation')
        if self.stop():return False
        if not self.show_tools():return False
        first=self.reader.ready_save(self.s.capture.screenshot())
        if first is None or self.stop() or self.reader.ready_save(self.s.capture.screenshot())!=first:return False
        p['phase']='saving_complete';write(self.path,state)
        if self.stop():return False
        self.s.input.tap(*first,jitter=0)
        if interrupted_sleep(.7,self.stop):return False
        for _ in range(10):
            if self.stop():return False
            f=self.s.capture.screenshot()
            if self.reader.active_slot(f)==p['original_slot'] and self.reader.selected_slot(f)==p['slot']:
                if self.reader.selected_slot(self.s.capture.screenshot())==p['slot']:
                    p.update(phase='ready_to_activate',saved_at=time.time());write(self.path,state);return True
            if interrupted_sleep(.5,self.stop):return False
        return False

    def activate(self):
        from coc_bot.stop import interrupted_sleep
        state=read(self.path,{});p=state.get('pending',{})
        if (p.get('account')!=self.s.config.account_tag or p.get('phase') not in ('ready_to_activate','activating')
            or type(p.get('slot')) is not int or not 0<=p['slot']<3 or p['slot']==p.get('original_slot')
            or not p.get('saved_at') or p.get('placement')):
            raise ValueError('The native layout has not been confirmed complete')
        if self.stop():return False
        f=self.s.capture.screenshot()
        if p['phase']=='activating' and self.reader.active_slot(f)==p['slot']:
            if self.reader.active_slot(self.s.capture.screenshot())==p['slot']:
                state['completed']=state.pop('pending')|{'status':'active','activated_at':time.time()}
                if state.get('draft',{}).get('slot')==p['slot']:state.pop('draft')
                write(self.path,state);return True
        if self.reader.active_slot(f)!=p['original_slot'] or self.reader.selected_slot(f)!=p['slot']:return False
        button=self.reader.set_active(f)
        second=self.s.capture.screenshot()
        if (button is None or self.stop() or self.reader.active_slot(second)!=p['original_slot']
            or self.reader.selected_slot(second)!=p['slot'] or self.reader.set_active(second)!=button):return False
        p['phase']='activating';write(self.path,state)
        if self.stop():return False
        self.s.input.tap(*button,jitter=0)
        if interrupted_sleep(.7,self.stop):return False
        for _ in range(10):
            if self.stop():return False
            if self.reader.active_slot(self.s.capture.screenshot())==p['slot']:
                if self.reader.active_slot(self.s.capture.screenshot())==p['slot']:
                    state['completed']=state.pop('pending')|{'status':'active','activated_at':time.time()}
                    if state.get('draft',{}).get('slot')==p['slot']:state.pop('draft')
                    write(self.path,state);return True
            if interrupted_sleep(.5,self.stop):return False
        return False

    def close(self):
        from coc_bot.stop import interrupted_sleep
        def button(frame):
            return self.reader.find(frame,'editor_close',(.92,.01,.99,.13),threshold=.96) if self.reader.find(
                frame,'editor_title',(.33,.015,.67,.14),threshold=.96) else None
        first=button(self.s.capture.screenshot());second=button(self.s.capture.screenshot())
        if first is None or first!=second:raise ValueError('Layout Editor close control is unverified')
        if self.stop():return False
        self.s.input.tap(*second,jitter=0);interrupted_sleep(.6,self.stop)
        return True
