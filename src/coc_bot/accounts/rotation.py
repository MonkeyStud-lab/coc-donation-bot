"""A single-owner account rotation that always returns to the donation account.

Windows end at an idle checkpoint, never in a donation, upgrade payment, or
battle. A persisted switch intent and the ordinary tag verification protect
every handoff. Stop leaves the current village and any pending intent intact.
"""
from dataclasses import asdict
import threading
import time
import random

from loguru import logger

from coc_bot.accounts.store import read, write

VISIT_WORK = ('requests', 'upgrades', 'farm', 'builder_base', 'layouts')


class RotationStore:
    def __init__(self, accounts):
        self.accounts=accounts
        self.path=accounts.root/'data/accounts/rotation.json'

    def load(self):
        value=read(self.path,{})
        return {'enabled':False,'primary_id':None,'watch_seconds':900,'visit_seconds':180,
                'interval_seconds':1800,'visits':{},'paused_at':None}|value

    def configure(self, *, enabled, primary_id, watch_seconds=900, visit_seconds=180, interval_seconds=1800):
        state=self.accounts.load()
        main=next((a for a in state['accounts'] if a['id']==primary_id),None)
        if type(enabled) is not bool or main is None or 'donating' not in main['roles']:
            raise ValueError('Choose a saved account with the Donating role as the main account')
        if any(type(n) is not int for n in (watch_seconds,visit_seconds,interval_seconds)):
            raise ValueError('Account visit times must be whole seconds')
        if not 60<=visit_seconds<=600 or not 300<=watch_seconds<=7200 or watch_seconds<3*visit_seconds:
            raise ValueError('Main-account time must be at least three times each other visit (60–600 seconds)')
        if not 300<=interval_seconds<=86400:
            raise ValueError('Account check interval must be between five minutes and one day')
        value=self.load()|{'enabled':enabled,'primary_id':primary_id,'watch_seconds':watch_seconds,
                          'visit_seconds':visit_seconds,'interval_seconds':interval_seconds}
        if state.get('pending'):raise ValueError('Finish adding or verifying the loaded account first')
        write(self.path,value)
        return value

    def resume(self, now):
        state=self.load()
        paused=state.get('paused_at')
        if type(paused) in (int,float) and 0<=paused<=now:
            duration=now-paused
            for visit in state['visits'].values():
                for key in ('next_visit_at','next_farm_at'):
                    if type(visit.get(key)) in (int,float):visit[key]+=duration
        state['paused_at']=None
        write(self.path,state)

    def pause(self, now):
        state=self.load();state['paused_at']=now;write(self.path,state)

    def farm_remaining(self,ident,now):
        state=self.load();due=state['visits'].get(ident,{}).get('next_farm_at')
        if type(due) not in (int,float):return None
        paused=state.get('paused_at')
        reference=paused if type(paused) in (int,float) and 0<=paused<=now else now
        return max(0,due-reference)

    def next_account(self, now):
        state=self.load()
        eligible=[a for a in self.accounts.load()['accounts'] if a['id']!=state['primary_id'] and
                  set(a['roles']) & {'farming','upgrading','builder_base'} and
                  state['visits'].get(a['id'],{}).get('next_visit_at',0)<=now]
        return min(eligible,key=lambda a:state['visits'].get(a['id'],{}).get('last_finished_at',0),default=None)

    def complete(self, ident, now, elapsed):
        state=self.load();visit=state['visits'].setdefault(ident,{})
        visit.update(last_finished_at=now,seconds=elapsed,next_visit_at=now+state['interval_seconds'])
        # Goal-based visits can legitimately include several battles. Do not
        # turn one long visit into hours of starvation for the remaining queue.
        if ident!=state['primary_id']:state['next_watch_seconds']=state['watch_seconds']
        write(self.path,state)

    def work_order(self, ident):
        state=self.load()
        if ident==state['primary_id']:return VISIT_WORK
        first=state['visits'].get(ident,{}).get('next_work')
        start=VISIT_WORK.index(first) if first in VISIT_WORK else 0
        return VISIT_WORK[start:]+VISIT_WORK[:start]

    def work_attempted(self, ident, kind, now):
        if kind not in VISIT_WORK:raise ValueError('Unknown account visit task')
        state=self.load()
        if ident==state['primary_id']:return
        visit=state['visits'].setdefault(ident,{})
        # Persist immediately, before an idle checkpoint can end this visit.
        # A long upgrade inventory must not win first place on every visit.
        visit.update(last_work=kind,last_work_at=now,
                     next_work=VISIT_WORK[(VISIT_WORK.index(kind)+1)%len(VISIT_WORK)])
        write(self.path,state)


class AccountFleet:
    def __init__(self, store, options, *, factory=None, clock=time.time):
        self.store,self.options,self.clock=store,options,clock
        self.rotation=RotationStore(store)
        self.factory=factory
        self.current=None
        self.cancel=threading.Event()
        self.finish_action=False
        self.activity='Preparing account rotation'
        self._next=None

    def __getattr__(self,name):
        current=self.__dict__.get('current')
        if current is None:raise AttributeError(name)
        return getattr(current,name)

    def request_stop(self):
        self.cancel.set()
        if self.current:self.current.request_stop()

    def request_stop_after_action(self):
        self.finish_action=True
        if self.current:self.current.request_stop_after_action()

    def request_farm_attack(self):
        if self.current is None:raise ValueError('Wait for the selected account to load')
        self.current.request_farm_attack()

    def _new_bot(self):
        if self.factory:return self.factory(self.options)
        from coc_bot.bot import DonationBot
        return DonationBot(**asdict(self.options))

    def _initialize_schedule(self,account):
        visit=getattr(self.current,'_visit',None)
        if visit:visit.order()  # Start the next due checklist, not its old finished marker.
        state=self.rotation.load();visit=state['visits'].setdefault(account['id'],{})
        if 'last_attack_id' not in visit:
            visit['last_attack_id']=self.current.tracker.state.last_completed_attack_id
        write(self.rotation.path,state)

    def _checkpoint(self, account, started):
        if self.cancel.is_set() or self.finish_action:return True
        state=self.rotation.load();now=self.clock()
        if getattr(self.current,'_visit',None):
            from coc_bot.attack.recovery import pending
            from coc_bot.builder_base.runner import pending as builder_pending
            if (pending(self.current.config) or builder_pending(self.current.config)
                or read(self.current.config.data_dir/'upgrades/state.json',{}).get('pending')
                or read(self.current.config.data_dir/'layouts/state.json',{}).get('pending')
                or read(self.current.config.data_dir/'layouts/state.json',{}).get('last_survey',{}).get('payment')):return False
            if not getattr(self,'_clan_checked',False):
                from coc_bot.accounts.clan import ClanIdentity
                self._current_clan=ClanIdentity(self.store,self.current,self.cancel.is_set).learn(account)
                self._clan_checked=True
                detour=state.get('donation_detour')
                if detour and account['id']==detour['donor'] and self._current_clan!=detour.get('clan'):
                    self._next=detour['resume'];state.pop('donation_detour',None)
                    state['last_donation_detour_at']=now;write(self.rotation.path,state)
                    logger.warning('Donation detour cancelled: donor clan membership changed or is unverified')
                    return self._next!=account['id']
            if getattr(self,'_chat_due',False) and not state.get('donation_detour'):
                self._chat_due=False;self._next=account['id']
                self._check_chat_before_switch(account)
                if self._next!=account['id']:return True
        detour=state.get('donation_detour')
        if detour and detour.get('phase')=='returning' and account['id']==detour['resume']:
            state.pop('donation_detour',None);write(self.rotation.path,state);detour=None
        if detour and account['id']!=detour['donor']:
            self._next=detour['donor'];return True
        if detour and account['id']==detour['donor']:
            if now-started<5:return False
            request=self.current._has_donate_request(self.current.capture.screenshot())
            if request and now-started<180:return False
            self._next=detour['resume']
            if detour['resume']==account['id']:state.pop('donation_detour',None)
            else:detour['phase']='returning'
            state['last_donation_detour_at']=now
            write(self.rotation.path,state)
            return detour['resume']!=account['id']
        visit=state['visits'].setdefault(account['id'],{})
        completed=self.current.tracker.state.last_completed_attack_id
        if completed and completed!=visit.get('last_attack_id'):
            visit.update(last_attack_id=completed)
            write(self.rotation.path,state)
        if account['id']==state['primary_id']:
            visit=getattr(self.current,'_visit',None)
            if visit and not visit.complete():return False
            if now-started<state.get('next_watch_seconds',state['watch_seconds']):return False
            target=self.rotation.next_account(now)
            if target is None:return False
            # A fresh visible request earns a further chat pass before leaving.
            if self.current._has_donate_request(self.current.capture.screenshot()):return False
            self._next=target['id']
            return True
        visit=getattr(self.current,'_visit',None)
        if visit and visit.complete():
            self._next=state['primary_id']
            return True
        if not visit and now-started>=state['visit_seconds']:
            self._next=state['primary_id'];return True
        return False

    def _check_chat_before_switch(self,account):
        """Called only after all battle/payment journals pass the idle guard."""
        state=self.rotation.load()
        if state.get('donation_detour'):return
        from coc_bot.accounts.clan import donors_for,membership
        donors=donors_for(self.store,account,self.clock())
        if not donors:return
        nav=self.current.navigator;frame=self.current.capture.screenshot()
        if not nav.classifier._clan_chat_anchor_visible(frame):
            from coc_bot.vision.battle_menu import home_build_control_visible
            if not home_build_control_visible(frame):raise ValueError('Home not verified before rotation chat check')
            nav._open_clan_chat(frame)
            self.current._sleep(.5)
            frame=self.current.capture.screenshot()
        if not nav.classifier._clan_chat_anchor_visible(frame):
            raise ValueError('Clan chat could not be verified before switching accounts')
        request=self.current.chat_monitor.find_donate_request(frame)
        if request is None:return
        if 'donating' in account['roles']:
            self.current._visit_chat_pending=True
            self._next=account['id'];return
        # A request that cannot be filled must not create an endless detour.
        if self.clock()-state.get('last_donation_detour_at',0)<180:return
        donor=random.choice(donors)
        state['donation_detour']={'donor':donor['id'],'resume':self._next,'source':account['id'],
                                  'signature':request.signature,'at':self.clock(),
                                  'clan':membership(self.store,account,self.clock())}
        write(self.rotation.path,state)
        self._next=donor['id']

    @property
    def farm_remaining_seconds(self):
        return None  # Storage demand replaces the attack interval.

    def run(self):
        from coc_bot.accounts.navigation import AccountNavigator
        from coc_bot.control.diagnostics import DebugSession
        from coc_bot.runtime.device_lease import DeviceLease
        self.store.require_ready(allow_layout_recovery=True)
        state=self.rotation.load()
        if not state['enabled']:raise ValueError('Account rotation is disabled')
        main=self.store.account(state['primary_id'])
        if main is None or 'donating' not in main['roles']:raise ValueError('Main donating account is unavailable')
        with self.store.scope():session=DebugSession()
        self.rotation.resume(self.clock())
        try:
            with DeviceLease(session.config.adb_device):
                while not self.cancel.is_set() and not self.finish_action:
                    account=self.store.account()
                    if account is None:raise ValueError('No saved account is selected')
                    with self.store.scope(account['id']):
                        self.store.require_ready(allow_layout_recovery=True)
                        self.current=self._new_bot()
                        if self.cancel.is_set() or self.finish_action:
                            self.current.request_stop()
                            break
                        started=self.clock();self._next=None;self._clan_checked=False;self._chat_due=True
                        self._initialize_schedule(account)
                        self.current._fleet_should_yield=lambda:self._checkpoint(account,started)
                        visit=getattr(self.current,'_visit',None)
                        self.current._fleet_work_order=lambda:visit.order() if visit else self.rotation.work_order(account['id'])
                        self.current._fleet_after_step=lambda:setattr(self,'_chat_due',True)
                        self.current._fleet_work_attempted=lambda kind:self.rotation.work_attempted(account['id'],kind,self.clock())
                        detour=self.rotation.load().get('donation_detour')
                        if detour and account['id']==detour['donor']:
                            self.current._fleet_work_order=lambda:()
                        self.activity=('Watching '+account['nickname'] if account['id']==main['id']
                                       else 'Visiting '+account['nickname'])
                        logger.info('Activity: {}',self.activity)
                        self.current.run_owned()
                        self.rotation.complete(account['id'],self.clock(),self.clock()-started)
                        if self.cancel.is_set() or self.finish_action or self._next is None:break
                        # Never switch away while attack/upgrade/visit recovery
                        # is unresolved, even if its visit time has expired.
                        from coc_bot.attack.recovery import pending
                        from coc_bot.builder_base.runner import pending as builder_pending
                        from coc_bot.upgrades.runner import UpgradeRunner
                        if (pending(self.current.config) or builder_pending(self.current.config) or
                            UpgradeRunner(self.current.config,self.current.capture,self.current.nav_input,
                                          self.current.navigator).state().get('pending')):
                            raise ValueError('Account has an unresolved action; automatic switching paused')
                        self._check_chat_before_switch(account)
                        if self.cancel.is_set() or self.finish_action:break
                        if self._next==account['id']:continue
                        target=self.store.account(self._next)
                        if target is None:raise ValueError('Next saved account disappeared')
                        self.activity='Switching to '+target['nickname']
                        self.store.begin('switch',target['id'])
                        nav=AccountNavigator(self.current,self.cancel.is_set)
                        identity=nav.switch(target)
                        if self.cancel.is_set():break
                        self.store.complete(identity['tag'],hall=identity.get('hall'))
        finally:
            self.rotation.pause(self.clock())
