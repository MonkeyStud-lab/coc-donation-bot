"""Recognized first-visit dialog steps; unknown tutorial prompts stay paused."""
import time
import hashlib
import cv2
from coc_bot.accounts.store import read,write,backup
from coc_bot.upgrades.vision import crop,resource_amount


DIALOGS={
    'sail_ready':('setup_sail_ready',(.20,.40,.60,.70)),
    'first_sail':('setup_sail_way_back',(.20,.40,.60,.70)),
    'first_travel':('setup_sail_way_back',(.20,.40,.60,.70)),
    'select_ruined_hall':('setup_shelter',(.20,.40,.60,.70)),
    'inspect_hall_repair':('setup_shelter',(.20,.40,.60,.70)),
    'select_star_lab':('setup_favorite_lab',(.47,.37,.80,.65)),
    'inspect_star_research':('setup_favorite_lab',(.47,.37,.80,.65)),
    'inspect_first_barbarian':('setup_choose_research',(.32,.15,.79,.28)),
}


class BuilderOnboarding:
    def __init__(self, runner):
        self.r=runner
        self.path=runner.config.data_dir/'builder_base/setup.json'

    def state(self):return read(self.path,{})

    def select_setup_boat(self,frame):
        """Select the inspected tutorial boat; its actions prove rebuild/travel."""
        state=self.state()
        if state and (state.get('account')!=self.r.config.account_tag or state.get('phase') not in ('selecting_boat','first_sail_requested')):
            return False
        if not self.r.config.account_tag or not self.r.home_village(frame):return False
        first=self.r.reader.setup_boat_target(frame)
        if first is None:return False
        fresh=self.r.frame();second=self.r.reader.setup_boat_target(fresh)
        if (second is None or ((second[0]-first[0])**2+(second[1]-first[1])**2)**.5>max(4,fresh.shape[1]*.004)
            or not self.r.home_village(fresh)):return False
        if state.get('boat_selection_attempts',0)>=2:raise ValueError('The boat selection did not advance; inspect the saved screen')
        if not state:
            state={'account':self.r.config.account_tag,'at':time.time(),'source':'visible_uninitialized_boat',
                   'backup':str(backup(self.r.config.data_dir.parent))}
        state.update(phase='selecting_boat',boat_selection_attempts=state.get('boat_selection_attempts',0)+1)
        write(self.path,state)
        self.r.tap(second);self.r.wait(1)
        return True

    def rebuild_free_boat(self):
        point=self.r.reader.free_boat_confirmation(self.r.frame())
        if point is None or self.r.reader.free_boat_confirmation(self.r.frame())!=point:
            raise ValueError('Free Boat rebuild confirmation was not verified')
        state=self.state()
        if state and state.get('account')!=self.r.config.account_tag:raise ValueError('Boat setup belongs to another account')
        if state.get('phase')=='rebuilding_free_boat':raise ValueError('Review the recorded free rebuild before sending another confirmation')
        if not state:state={'account':self.r.config.account_tag,'at':time.time(),'backup':str(backup(self.r.config.data_dir.parent))}
        state['phase']='rebuilding_free_boat';write(self.path,state)
        self.r.tap(point);self.r.wait(6)
        frame=self.r.frame()
        if self.r.reader.free_boat_confirmation(frame):raise ValueError('Boat rebuild did not complete; no repeat input sent')
        from coc_bot.progression.reader import ProgressionReader
        if ProgressionReader(self.r.stop).menu_kind(frame)=='buildings':
            self.r.tap((round(frame.shape[1]*.984),round(frame.shape[0]*.032)));self.r.wait()
        state['phase']='boat_rebuilt';write(self.path,state)
        return True

    def prepare(self):
        """Find the named FREE Boat rebuild; never substitute a paid shop item."""
        from coc_bot.progression.reader import ProgressionReader,same_row_observation
        from coc_bot.progression.runner import ProgressionRunner
        from coc_bot.upgrades.vision import compact
        from coc_bot.vision.battle_menu import home_build_control_visible
        state=self.state()
        if state:
            if state.get('account')!=self.r.config.account_tag:raise ValueError('Builder setup belongs to another account')
            if state.get('phase')=='complete':return False
            if state.get('phase') not in ('selecting_boat','first_sail_requested'):return True
        frame=self.r.frame()
        if not self.r.config.account_tag or not self.r.home_village(frame) or not home_build_control_visible(frame):return False
        h,w=frame.shape[:2];reader=ProgressionReader(self.r.stop)
        self.r.tap((round(w*.931),round(h*.896)));self.r.wait()
        frame=self.r.frame()
        if reader.menu_kind(frame)!='buildings':raise ValueError('Boat setup requires the verified Home Build menu')
        navigation=ProgressionRunner(self.r.config,self.r.capture,self.r.input,self.r.nav,self.r.stop)
        frame=navigation.clear_filters(frame)
        if frame is None:raise ValueError('Stopped before finding the free Boat')
        def boat(image):return [r for r in reader.rows(image) if compact(r['name'])=='boat'
                               and r.get('cost')==0 and r.get('currency')=='free']
        rows=[]
        for page in range(20):
            if reader.menu_kind(frame)!='buildings':raise ValueError('Build menu changed while finding the Boat')
            rows=boat(frame)
            if rows:break
            if page==19:break
            before=cv2.resize(crop(frame,(.735,.11,1,.89)),(180,400))
            self.r.input.swipe(round(w*.87),round(h*.82),round(w*.87),round(h*.40),duration_ms=350)
            self.r.wait(.4);fresh=self.r.frame()
            if reader.menu_kind(fresh)!='buildings':raise ValueError('Build menu changed while finding the Boat')
            after=cv2.resize(crop(fresh,(.735,.11,1,.89)),(180,400))
            frame=fresh
            if abs(before.astype(float)-after).mean()<1.8:break
        if not rows:
            self.r.tap((round(w*.984),round(h*.032)));self.r.wait();return False
        again=boat(self.r.frame())
        if len(rows)!=1 or len(again)!=1 or not same_row_observation(rows[0],again[0],frame.shape):
            raise ValueError('Free Boat row moved; no rebuild input sent')
        self.r.tap(tuple(again[0]['point']));self.r.wait()
        return self.rebuild_free_boat()

    def drive(self):
        """Run the inspected introduction under the existing device lease."""
        from coc_bot.vision.battle_menu import home_build_control_visible
        state=self.state()
        if state.get('account')!=self.r.config.account_tag:raise ValueError('Builder setup account is unverified')
        deadline=time.monotonic()+480
        unknown_since=None
        while time.monotonic()<deadline:
            self.r.check()
            if self.state().get('pending_payment'):raise ValueError('Builder setup payment requires review before continuing')
            if self.step():
                unknown_since=None
                continue
            frame=self.r.frame();state=self.state()
            ready=(state.get('phase')=='first_battle_returned' and self.dialog(frame) is None
                   and self.r.reader.home(frame) and home_build_control_visible(frame))
            if ready:
                second=self.r.frame()
                if self.r.reader.home(second) and home_build_control_visible(second) and self.dialog(second) is None:
                    state.update(phase='complete',completed_at=time.time());write(self.path,state)
                    self.r.phase('builder_home');return
            if state.get('phase') in ('first_battle_matchmaking','first_battle_deploying'):
                self.r.wait(2);continue
            # The first sea trip and tutorial camera moves briefly cover every
            # known control. Observe without input before declaring a new UI.
            now=time.monotonic()
            if unknown_since is None:unknown_since=now
            if now-unknown_since<12:
                self.r.wait(2);continue
            self.r.evidence(frame,'unknown-first-visit')
            raise ValueError('Unrecognized Builder Base introduction step; no guessed input sent')
        raise ValueError('Builder Base introduction timed out; review its saved screen')

    def dialog(self, frame):
        found=[]
        for key,(asset,box) in DIALOGS.items():
            point=self.r.reader.find(frame,asset,box,threshold=.94)
            if point and key=='first_sail':
                point=self.r.reader.find(frame,'setup_first_sail_boat',(.14,.12,.90,.80),threshold=.94)
            if point and key=='first_travel':
                info=self.r.reader.find(frame,'setup_travel_info',(.38,.75,.50,.90),threshold=.94)
                point=self.r.reader.find(frame,'setup_first_travel',(.50,.75,.63,.91),threshold=.94) if info else None
            if point and key=='select_ruined_hall':
                selected=self.r.reader.find(frame,'setup_hall_level_one',(.58,.15,.76,.28),threshold=.94)
                point=None if selected else self.r.reader.find(frame,'setup_ruined_hall',(.58,.20,.76,.43),threshold=.94)
            if point and key=='inspect_hall_repair':
                selected=self.r.reader.find(frame,'setup_hall_level_one',(.58,.15,.76,.28),threshold=.94)
                point=self.r.reader.find(frame,'setup_upgrade_word',(.50,.75,.63,.91),threshold=.94) if selected else None
            if point and key=='select_star_lab':
                selected=self.r.reader.find(frame,'setup_lab_research',(.48,.77,.63,.89),threshold=.94)
                point=None if selected else self.r.reader.find(frame,'setup_lab_globe',(.40,.40,.51,.57),threshold=.94)
            if point and key=='inspect_star_research':
                point=self.r.reader.find(frame,'setup_lab_research',(.48,.77,.63,.89),threshold=.94)
            if point and key=='inspect_first_barbarian':
                point=self.r.reader.find(frame,'setup_first_barbarian',(.17,.51,.27,.69),threshold=.96)
            if point:found.append((key,point))
        if found:return found[0] if len(found)==1 else None
        return self.speech(frame)

    def speech(self, frame):
        """A tutorial speech bubble is a non-purchase navigation target.

        Both ornate corners, white interior, dark caption and absence of a green
        action in the bubble must agree. It runs only inside this account's
        recorded first-visit setup; repeated unchanged captions stop after two
        taps so instructions requiring a separate target cannot loop forever.
        """
        left=(self.r.reader.find(frame,'setup_speech_corner',(.15,.2,.8,.85),threshold=.96)
              or self.r.reader.find(frame,'setup_speech_master_corner',(.15,.2,.8,.85),threshold=.96))
        right=self.r.reader.find(frame,'setup_speech_bottom',(.25,.35,.9,.95),threshold=.96)
        if left is None or right is None:return None
        w,h=frame.shape[1],frame.shape[0];scale=w/1853
        x0,y0=round(left[0]-26*scale),round(left[1]-19*scale)
        x1,y1=round(right[0]+24*scale),round(right[1]+22*scale)
        if not w*.20<x1-x0<w*.40 or not h*.12<y1-y0<h*.28:return None
        inner=frame[y0+round(38*scale):y1-round(35*scale),x0+round(25*scale):x1-round(25*scale)]
        hsv=cv2.cvtColor(inner,cv2.COLOR_BGR2HSV)
        white=cv2.inRange(hsv,(0,0,190),(180,45,255)).mean()/255
        green=cv2.inRange(hsv,(30,90,120),(90,255,255)).mean()/255
        gray=cv2.cvtColor(inner,cv2.COLOR_BGR2GRAY)
        if white<.55 or green>.03 or (gray<100).mean()<.005:return None
        key='speech_'+hashlib.sha256(cv2.resize((gray<100).astype('uint8'),(220,70)).tobytes()).hexdigest()[:16]
        return key,((x0+x1)//2,(y0+y1)//2)

    def advance_dialog(self):
        state=self.state()
        if state.get('account')!=self.r.config.account_tag:return False
        first=self.dialog(self.r.frame())
        if first is None:return False
        fresh=self.r.frame();second=self.dialog(fresh)
        if first!=second:
            if (second is None or first[0]!=second[0] or first[0]!='first_sail'
                or ((first[1][0]-second[1][0])**2+(first[1][1]-second[1][1])**2)**.5>max(5,fresh.shape[1]*.008)):
                return False
        key,point=second
        attempts=state.setdefault('dialog_attempts',{})
        if attempts.get(key,0)>=2:raise ValueError('Builder Base introduction did not advance; inspect the saved screen')
        attempts[key]=attempts.get(key,0)+1
        state.update(last_dialog=key,updated_at=time.time())
        if key in ('first_sail','first_travel'):state['phase']=key+'_requested'
        write(self.path,state)
        self.r.tap(point);self.r.wait(.8)
        return True

    def hall_repair_confirmation(self, frame):
        reader=self.r.reader
        if (reader.find(frame,'setup_hall_two_title',(.29,.015,.65,.115),threshold=.96)
            and reader.find(frame,'setup_hall_name',(.19,.13,.40,.20),threshold=.96)
            and (reader.find(frame,'setup_hall_five_seconds',(.16,.37,.30,.49),threshold=.96)
                 or reader.find(frame,'setup_hall_three_seconds',(.16,.37,.30,.49),threshold=.96))
            and reader.find(frame,'confirm_gold',(.546,.83,.597,.92),threshold=.90)
            and resource_amount(crop(frame,(.415,.842,.543,.925)),reader.stop)==3500):
            green=cv2.inRange(cv2.cvtColor(crop(frame,(.418,.83,.59,.93)),cv2.COLOR_BGR2HSV),
                              (30,70,140),(90,255,255)).mean()/255
            if green>.4:return round(frame.shape[1]*.504),round(frame.shape[0]*.875)
        return None

    def resume_first_sail(self, frame, state):
        """Recover the rebuilt boat even after its Chief dialogue is gone."""
        if (state.get('account')!=self.r.config.account_tag or state.get('pending_payment')
            or state.get('phase') not in ('boat_rebuilt','first_sail_requested')):return False
        from coc_bot.progression.reader import ProgressionReader
        reader=ProgressionReader(self.r.stop)
        if reader.menu_kind(frame)=='buildings':
            if reader.menu_kind(self.r.frame())!='buildings':return False
            self.r.tap((round(frame.shape[1]*.984),round(frame.shape[0]*.032)))
            self.r.wait();return True
        if not self.r.home_village(frame) or self.dialog(frame) is not None:return False
        point=self.r.reader.find(frame,'setup_first_sail_boat',(.14,.12,.90,.80),threshold=.94)
        if point is None:return False
        second=self.r.frame()
        again=self.r.reader.find(second,'setup_first_sail_boat',(.14,.12,.90,.80),threshold=.94)
        if (again is None or not self.r.home_village(second) or self.dialog(second) is not None
            or ((point[0]-again[0])**2+(point[1]-again[1])**2)**.5>max(5,second.shape[1]*.008)):return False
        attempts=state.get('travel_attempts',0)
        if attempts>=2:raise ValueError('First boat journey did not advance; inspect its saved screen')
        state.update(phase='first_sail_requested',travel_attempts=attempts+1,updated_at=time.time())
        write(self.path,state)
        self.r.tap(again);self.r.wait(2)
        return True

    def step(self):
        state=self.state()
        if state.get('account')!=self.r.config.account_tag:return False
        if state.get('phase')=='complete':return False
        frame=self.r.frame()
        if state.get('phase')=='inspecting_free_boat_rebuild' and self.r.reader.free_boat_confirmation(frame):
            return self.rebuild_free_boat()
        if state.get('phase')=='selecting_boat' and self.select_setup_boat(frame):return True
        if state.get('phase') in ('selecting_boat','first_sail_requested'):
            point=self.r.reader.selected_boat_rebuild(frame)
            if point:
                if self.r.reader.selected_boat_rebuild(self.r.frame())!=point:return False
                state.update(phase='inspecting_free_boat_rebuild',source='visible_uninitialized_boat');write(self.path,state)
                self.r.tap(point);self.r.wait()
                return self.rebuild_free_boat()
        if self.resume_first_sail(frame,state):return True
        from coc_bot.vision.battle_menu import home_build_control_visible
        if (state.get('phase')=='first_research_complete' and self.r.reader.home(frame)
            and self.dialog(frame) is None and not home_build_control_visible(frame)):
            second=self.r.frame()
            if self.r.reader.home(second) and self.dialog(second) is None and not home_build_control_visible(second):
                self.r.tap((round(second.shape[1]*.065),round(second.shape[0]*.89)));self.r.wait();return True
        if state.get('phase') in ('first_battle_matchmaking','first_battle_deploying'):
            result=self.r.reader.result_button(frame)
            if result and self.r.reader.result_button(self.r.frame())==result:
                state['phase']='first_battle_returned';write(self.path,state)
                self.r.tap(result);self.r.wait(2)
                return True
            if self.first_battle(frame):
                second=self.r.frame()
                count=self.first_battle(second)
                if count and count==self.first_battle(frame):
                    sent=state.get('deployed',0)
                    if sent>=3:raise ValueError('Starter troops did not deploy; no further input sent')
                    if count!=3-sent:raise ValueError('Starter troop count did not change as expected; deployment paused')
                    state.update(phase='first_battle_deploying',deployed=sent+1)
                    write(self.path,state)
                    # Inspected tutorial arena only. This is outside its red
                    # boundary, well above the cards and without any HUD there.
                    self.r.tap((round(second.shape[1]*.115),round(second.shape[0]*.90)))
                    self.r.tap((round(second.shape[1]*.32),round(second.shape[0]*.61)))
                    self.r.wait(1)
                    return True
        if (state.get('phase')=='first_research_complete' and self.r.reader.attack_menu(frame)
            and self.r.reader.find(frame,'setup_army_barbarian',(.16,.38,.24,.50),threshold=.96)):
            second=self.r.frame()
            if not (self.r.reader.attack_menu(second) and
                self.r.reader.find(second,'setup_army_barbarian',(.16,.38,.24,.50),threshold=.96)):return False
            point=self.r.reader.find(second,'find_now',(.65,.60,.84,.72))
            if point:
                state['phase']='first_battle_matchmaking';write(self.path,state)
                self.r.phase('matchmaking');self.r.tap(point);self.r.wait(3)
                return True
        payment=self.payment(frame)
        if payment is None:return self.advance_dialog()
        if state.get('pending_payment'):
            raise ValueError('Builder Base setup payment needs reconciliation; no retry will be sent')
        if state.get('last_dialog')!=payment['requires']:
            raise ValueError('The upgrade was not selected by this setup operation')
        second=self.r.frame()
        if self.payment(second)!=payment:return False
        def balances(image):return {key:resource_amount(crop(image,box),self.r.stop) for key,box in {
            payment['currency']:(.87,.034,.958,.071) if payment['currency']=='gold' else (.87,.10,.958,.14),
            'gems':(.91,.174,.953,.208)}.items()}
        before,again=balances(frame),balances(second)
        resource=payment['currency'];price=payment['cost']
        if before!=again or type(before[resource]) is not int or before[resource]<price or type(before['gems']) is not int:
            raise ValueError('Builder Base setup resource balances are unverified')
        state['pending_payment']=payment|{'from_level':1,'to_level':2,'before':before,'at':time.time()}
        write(self.path,state)
        self.r.tap(payment['point']);self.r.wait(payment['seconds']+2)
        after=balances(self.r.frame())
        if after!={resource:before[resource]-price,'gems':before['gems']}:
            raise ValueError('Builder Base setup payment was sent but its result needs review; no repeat')
        state['last_payment']=state.pop('pending_payment')|{'after':after}
        state['phase']=payment['phase'];write(self.path,state)
        return True

    def first_battle(self, frame):
        reader=self.r.reader
        if not (reader.find(frame,'setup_master_jimmy',(.045,.04,.21,.095),threshold=.96)
                and reader.find(frame,'defender',(.045,.012,.145,.06),threshold=.94)
                and reader.find(frame,'attacker',(.875,.012,.97,.06),threshold=.94)
                and reader.find(frame,'setup_battle_barbarian',(.07,.85,.155,.98),threshold=.94)):
            return None
        count=resource_amount(crop(frame,(.121,.812,.136,.842)),reader.stop)
        return count if count in (1,2,3) else None

    def payment(self, frame):
        point=self.hall_repair_confirmation(frame)
        if point:return {'point':point,'requires':'inspect_hall_repair','name':'Builder Hall',
                         'cost':3500,'currency':'gold','seconds':5,'phase':'hall_repaired'}
        reader=self.r.reader
        if (reader.find(frame,'setup_research_two',(.35,.02,.65,.11),threshold=.96)
            and reader.find(frame,'setup_barbarian_rage',(.57,.24,.82,.31),threshold=.96)
            and (reader.find(frame,'setup_research_thirty',(.62,.70,.73,.79),threshold=.96)
                 or reader.find(frame,'setup_research_fifteen',(.62,.70,.73,.79),threshold=.96))
            and reader.find(frame,'research_elixir',(.788,.825,.824,.90),threshold=.90)
            and resource_amount(crop(frame,(.68,.845,.787,.89)),reader.stop)==3500):
            green=cv2.inRange(cv2.cvtColor(crop(frame,(.675,.81,.832,.925)),cv2.COLOR_BGR2HSV),
                              (30,70,140),(90,255,255)).mean()/255
            if green>.3:return {'point':(round(frame.shape[1]*.751),round(frame.shape[0]*.87)),
                'requires':'inspect_first_barbarian','name':'Raged Barbarian','cost':3500,
                'currency':'elixir','seconds':30,'phase':'first_research_complete'}
        return None
