"""A single-owner account rotation that always returns to the donation account.

Windows end at an idle checkpoint, never in a donation, upgrade payment, or
battle. A persisted switch intent and the ordinary tag verification protect
every handoff. Stop leaves the current village and any pending intent intact.
"""
from dataclasses import asdict
from datetime import datetime
import threading
import time
import random
from zoneinfo import ZoneInfo

from loguru import logger

from coc_bot.accounts.store import read, write
from coc_bot.accounts.watch import DonorWatch

VISIT_WORK = ('requests', 'upgrades', 'farm', 'builder_base', 'layouts')


def daytime_donation_watch(state, now):
    if not state.get('daytime_donation_watch'):
        return False
    local = datetime.fromtimestamp(now, ZoneInfo('America/Chicago'))
    return 7 <= local.hour < 22


class RotationStore:
    def __init__(self, accounts):
        self.accounts=accounts
        self.path=accounts.root/'data/accounts/rotation.json'

    def load(self):
        value=read(self.path,{})
        return {'enabled':False,'primary_id':None,'task_driven':False,'watch_seconds':900,'visit_seconds':180,
                'interval_seconds':1800,'visits':{},'paused_at':None,
                'attack_target_per_hour':0,'finish_after_star':False,'daytime_donation_watch':False}|value

    def configure(self, *, enabled, primary_id, watch_seconds=900, visit_seconds=180, interval_seconds=1800,
                  task_driven=None, attack_target_per_hour=None, finish_after_star=None,
                  daytime_donation_watch=None):
        state=self.accounts.load()
        previous=self.load()
        if daytime_donation_watch is None:
            daytime_donation_watch = previous['daytime_donation_watch']
        if type(daytime_donation_watch) is not bool:
            raise ValueError('Daytime donation watch must be on or off')
        if daytime_donation_watch:
            ZoneInfo('America/Chicago')
        if task_driven is None:task_driven=previous['task_driven']
        if type(task_driven) is not bool:raise ValueError('Choose a valid account scheduling mode')
        if attack_target_per_hour is None:
            attack_target_per_hour = previous['attack_target_per_hour'] if task_driven else 0
        if finish_after_star is None:
            finish_after_star = previous['finish_after_star'] if attack_target_per_hour else False
        if type(attack_target_per_hour) is not int or not 0 <= attack_target_per_hour <= 6:
            raise ValueError('Choose a whole attack target from zero to six per hour')
        if (attack_target_per_hour and not task_driven or type(finish_after_star) is not bool
                or finish_after_star and not attack_target_per_hour):
            raise ValueError('Attack pacing and early finish require task-driven rotation')
        main=next((a for a in state['accounts'] if a['id']==primary_id),None)
        if type(enabled) is not bool or main is None or 'donating' not in main['roles']:
            raise ValueError('Choose a saved account with the Donating role as the main account')
        if any(type(n) is not int for n in (watch_seconds,visit_seconds,interval_seconds)):
            raise ValueError('Account visit times must be whole seconds')
        if not 60<=visit_seconds<=600 or not 300<=watch_seconds<=7200 or (not task_driven and watch_seconds<3*visit_seconds):
            raise ValueError('Main-account time must be at least three times each other visit (60–600 seconds)')
        if not 300<=interval_seconds<=86400:
            raise ValueError('Account check interval must be between five minutes and one day')
        value=previous|{'enabled':enabled,'primary_id':primary_id,'task_driven':task_driven,'watch_seconds':watch_seconds,
                          'visit_seconds':visit_seconds,'interval_seconds':interval_seconds,
                          'attack_target_per_hour':attack_target_per_hour,'finish_after_star':finish_after_star,
                          'daytime_donation_watch':daytime_donation_watch}
        if state.get('pending'):raise ValueError('Finish adding or verifying the loaded account first')
        if task_driven and not previous['task_driven']:
            # Remove old donor-policy scheduling delays, not action cooldowns
            # or persisted checklist/payment state.
            for visit in value['visits'].values():visit['next_visit_at']=0
        if attack_target_per_hour and not previous['attack_target_per_hour']:
            for visit in value['visits'].values():
                visit.pop('next_farm_at', None)
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

    def next_account(self, now, *, current_id=None):
        state=self.load()
        excluded=(current_id or self.accounts.load()['active']) if state['task_driven'] else state['primary_id']
        due = self.next_farming_account(state, now, excluded)
        if due is not None:
            return due
        eligible=[a for a in self.accounts.load()['accounts'] if a['id']!=excluded and
                  set(a['roles']) & {'farming','upgrading','builder_base'} and
                  state['visits'].get(a['id'],{}).get('next_visit_at',0)<=now]
        return min(eligible,key=lambda a:state['visits'].get(a['id'],{}).get('last_checked_at',
                   state['visits'].get(a['id'],{}).get('last_finished_at',0)),default=None)

    @staticmethod
    def farming_due(state, account, now):
        return bool(state['task_driven'] and state['attack_target_per_hour'] and 'farming' in account['roles']
                    and state['visits'].get(account['id'], {}).get('next_farm_at', 0) <= now)

    def next_farming_account(self, state, now, excluded):
        if not state['attack_target_per_hour']:
            return None
        due = (account for account in self.accounts.load()['accounts'] if account['id'] != excluded
               and self.farming_due(state, account, now))
        return min(due, key=lambda a:state['visits'].get(a['id'], {}).get('last_farm_attempt_at', 0), default=None)

    def farm_due_soon(self, now):
        state = self.load()
        return any(self.farming_due(state, a, now+180) for a in self.accounts.load()['accounts'])

    def record_farming(self, account_id, now, *, started=None, completed=False, delay=300):
        state = self.load()
        visit = state['visits'].setdefault(account_id, {})
        visit['last_farm_attempt_at'] = started if started is not None else now
        if completed:
            visit['next_farm_at'] = visit['last_farm_attempt_at'] + 3600 / state['attack_target_per_hour']
            visit['last_verified_farm_at'] = now
        else:
            visit['next_farm_at'] = now + delay
        write(self.path, state)

    def complete(self, ident, now, elapsed, *, suspended=False):
        state=self.load();visit=state['visits'].setdefault(ident,{})
        visit.update(last_checked_at=now,seconds=elapsed,
                     next_visit_at=now+(min(300,state['interval_seconds']) if suspended else state['interval_seconds']))
        account=self.accounts.account(ident)
        if account and ident!=state['primary_id'] and not suspended:
            data=self.accounts.profile(account)/'data'
            checklist=read(data/'visits/state.json',{})
            maintenance=read(data/'upgrades/maintenance.json',{})
            attention=any(v.get('status') in ('blocked','changed','no_room','waiting','needs_review')
                          for v in maintenance.get('categories',{}).values())
            if checklist.get('deferred') or attention:
                visit['next_visit_at']=min(visit['next_visit_at'],now+300)
        if not suspended:visit['last_finished_at']=now
        if state['task_driven']:
            # Unfinished work is eligible on the next fair turn. Finished
            # checklists keep their own short recheck/cooldown, not a donor wait.
            checklist=read(self.accounts.profile(account)/'data/visits/state.json',{}) if account else {}
            visit['next_visit_at']=now if suspended else max(now+60,checklist.get('next_check_at',now+300))
            state.pop('next_watch_seconds',None)
            write(self.path,state)
            return
        # Goal-based visits can legitimately include several battles. Do not
        # turn one long visit into hours of starvation for the remaining queue.
        if ident!=state['primary_id']:state['next_watch_seconds']=state['watch_seconds']
        if suspended:
            state['next_watch_seconds']=min(state['watch_seconds'],max(60,round(elapsed*2)))
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
        self._last_request_until=None
        self._watch=DonorWatch(clock)

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

    def _building_check_due(self):
        config = self.current.config
        if not getattr(config, 'upgrade_buildings_enabled', False) or getattr(config, 'dry_run', False):
            return False
        maintenance = read(config.data_dir / 'upgrades/maintenance.json', {})
        if self.clock() < maintenance.get('navigation_retry_at', 0):
            return False
        last = maintenance.get('categories', {}).get('buildings', {})
        checks = getattr(self.current, '_fleet_building_checks', 0)
        if checks:
            # Keep each visit bounded, even when several builders are free.
            # An unpaid rejected preview can give another candidate a turn.
            if checks >= 3:
                return False
            if last.get('retry_other_candidates') is True:
                return True
            available = last.get('availability')
            if last.get('status') == 'started' and available:
                free, total = available
                if free > config.upgrade_builders_reserved and free * 2 >= total:
                    return True
        # Recheck promptly after a confirmed start so another free builder
        # can take a job on the next rotation. Give quiet villages longer.
        interval = 300 if last.get('status') in ('started', 'built', 'recovered') else 1200
        checked_at = last.get('at')
        return checked_at is None or self.clock() >= checked_at + interval

    def _research_check_due(self):
        config = self.current.config
        if not getattr(config, 'upgrade_research_enabled', False) or getattr(config, 'dry_run', False):
            return False
        maintenance = read(config.data_dir / 'upgrades/maintenance.json', {})
        if self.clock() < maintenance.get('navigation_retry_at', 0):
            return False
        last = maintenance.get('categories', {}).get('research', {}).get('at')
        return last is None or self.clock() >= last + 1800

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
            if daytime_donation_watch(state, now):
                if account['id'] == state['primary_id']:
                    return False
                self._next = state['primary_id']
                self._visit_suspended = not self.current._visit.complete()
                logger.info('Daytime donation watch: returning to the primary donor')
                return True
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
            between_attacks=getattr(self.current,'_farm_chat_check_due',False) is True
            if between_attacks:self._chat_due=True
            if getattr(self,'_chat_due',False) and not state.get('donation_detour'):
                self._next=account['id']
                if between_attacks:logger.info('Between attacks: checking clan chat before another refill battle')
                if self._check_chat_before_switch(account):
                    self._chat_due=False;self.current._farm_chat_check_due=False
                if self._next!=account['id']:return True
        detour=state.get('donation_detour')
        if detour and detour.get('phase')=='returning' and account['id']==detour['resume']:
            state.pop('donation_detour',None);write(self.rotation.path,state);detour=None
        if detour and account['id']!=detour['donor']:
            self._next=detour['donor'];return True
        if detour and account['id']==detour['donor']:
            if state['task_driven']:
                if getattr(self.current,'_visit_chat_pending',False) is True:return False
            else:
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
        if state['task_driven']:
            visit=getattr(self.current,'_visit',None)
            # Finish the one request pass discovered at the task boundary.
            # Open donation states never enter this checkpoint.
            if ('donating' in account['roles'] and
                    getattr(self.current,'_visit_chat_pending',False) is True):return False
            if state['attack_target_per_hour']:
                if self._research_check_due() or self._building_check_due():
                    return False
                if self.rotation.farming_due(state, account, now):
                    return False
                target = self.rotation.next_farming_account(state, now, account['id'])
                if target is not None:
                    self._visit_suspended = bool(visit and not visit.complete())
                    self._next = target['id']
                    logger.info('Attack pacing: handing off to {} at a safe checkpoint', target['nickname'])
                    return True
            complete=bool(visit and visit.complete())
            if not complete and now-started<state['visit_seconds']:return False
            target=self.rotation.next_account(now,current_id=account['id'])
            if target is None:return False
            self._visit_suspended=not complete
            self._next=target['id']
            logger.info('Task rotation: handing off to {} at a safe checkpoint',target.get('nickname',target['id']))
            return True
        if account['id']==state['primary_id']:
            visit=getattr(self.current,'_visit',None)
            window=state.get('next_watch_seconds',state['watch_seconds'])
            # OCR, travel and donor maintenance cannot earn verified chat time.
            # Keep that accounting for maintenance, but cap how long a due
            # village can wait *at this donor visit's safe checkpoints*.
            if now-started < 1.5*window and not self._watch.ready(window):return False
            target=self.rotation.next_account(now)
            if target is None:return False
            # Give visible requests one grace period per handoff. Repeated
            # sightings of the same unfillable request must not renew it.
            if self._last_request_until is None or now < self._last_request_until:
                if self.current._has_donate_request(self.current.capture.screenshot()):
                    if self._last_request_until is None:self._last_request_until=now+30
                    return False
            if visit and not visit.complete():
                # A large refill can span many battles. At this receipt-free
                # checkpoint, preserve its cursor and give due accounts a turn
                # after the full donor window rather than starving their work.
                self._visit_suspended=True
                logger.info('Donor visit yielding to {} — unfinished checklist will resume on return',target.get('nickname',target['id']))
            self._next=target['id']
            return True
        visit=getattr(self.current,'_visit',None)
        if visit and visit.complete():
            self._next=state['primary_id']
            return True
        if visit and now-started>=120:
            # A receipt-free checkpoint after an action, never a mid-action timeout.
            # Resume the same checklist later; do not call a partial visit complete.
            self._visit_suspended=True
            self._next=state['primary_id']
            return True
        if not visit and now-started>=state['visit_seconds']:
            self._next=state['primary_id'];return True
        return False

    def _check_chat_before_switch(self,account):
        """Called only after all battle/payment journals pass the idle guard."""
        if self.cancel.is_set() or self.finish_action:return False
        state=self.rotation.load()
        if state.get('donation_detour'):return False
        from coc_bot.accounts.clan import donors_for,membership
        donors=donors_for(self.store,account,self.clock())
        if not donors:
            logger.info('Clan chat check skipped: no verified same-clan donor is available')
            return True
        from coc_bot.donation.chat_check import peek_requests
        from coc_bot.runtime.task_timing import measure_task
        stop=lambda:self.cancel.is_set() or self.finish_action
        try:
            with measure_task(account['tag'], 'chat_check') as timing:
                request=peek_requests(self.current.capture,self.current.navigator,self.current.chat_monitor,stop)
                timing['outcome'] = ('stopped' if stop() else
                                     'request_found' if request is not None else 'no_request')
        except ValueError as exc:
            from coc_bot.runtime.verification import record_failure
            record_failure(self.current.config,'accounts.chat_check',str(exc))
            raise  # The bot's loop recovery must prove Home before any work resumes.
        if stop():return False
        if request is None:
            logger.info('Clan chat check complete: no donation request found')
            return True
        if 'donating' in account['roles']:
            if (state['task_driven'] or account['id']==state['primary_id']) and self._next not in (None,account['id']):
                # The donor has already offered its final request pass. Keep
                # the scheduled target even if the final chat peek finds more.
                return True
            self.current._visit_chat_pending=True
            self._next=account['id'];return True
        # A request that cannot be filled must not create an endless detour.
        if self.clock()-state.get('last_donation_detour_at',0)<180:return True
        donor=random.choice(donors)
        state['donation_detour']={'donor':donor['id'],'resume':self._next,'source':account['id'],
                                  'signature':request.signature,'at':self.clock(),
                                  'clan':membership(self.store,account,self.clock())}
        write(self.rotation.path,state)
        self._next=donor['id']
        logger.info('Clan chat request found: detouring to a verified same-clan donor; this visit will resume afterward')
        return True

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
        self._watch=DonorWatch(self.clock)
        try:
            with DeviceLease(session.config.adb_device) as lease:
                from coc_bot.accounts.startup import recognize_loaded
                verified_handoff=recognize_loaded(self.store,session,lease,self.cancel.is_set)
                while not self.cancel.is_set() and not self.finish_action:
                    account=self.store.account()
                    if account is None:raise ValueError('No saved account is selected')
                    with self.store.scope(account['id']):
                        self.store.require_ready(allow_layout_recovery=True)
                        self.current=self._new_bot()
                        if verified_handoff is not None:
                            self.current._verified_handoff=verified_handoff
                            verified_handoff=None
                        if self.cancel.is_set() or self.finish_action:
                            self.current.request_stop()
                            break
                        started=self.clock();self._next=None;self._clan_checked=False;self._chat_due=True;self._visit_suspended=False
                        self._last_request_until=None
                        self._initialize_schedule(account)
                        self.current._fleet_should_yield=lambda:self._checkpoint(account,started)
                        visit=getattr(self.current,'_visit',None)
                        self._watch.begin_visit()
                        primary=account['id']==main['id']
                        if primary and state['daytime_donation_watch']:
                            self.current._fleet_donation_watch = lambda: daytime_donation_watch(state, self.clock())
                        # Maintenance and account travel incur chat time debt.
                        # Repay it at idle checkpoints; never interrupt actions.
                        self.current._fleet_task_driven=state['task_driven']
                        self.current._fleet_work_order=lambda: (() if primary and not state['task_driven'] and not self._watch.funded() else
                            visit.order(farm_first=state['task_driven']) if visit else self.rotation.work_order(account['id']))
                        if primary and not state['task_driven']:self.current._fleet_chat_seconds=self._watch.credit
                        self.current._fleet_after_step=lambda:setattr(self,'_chat_due',True)
                        self.current._fleet_work_attempted=lambda kind:self.rotation.work_attempted(account['id'],kind,self.clock())
                        detour=self.rotation.load().get('donation_detour')
                        if detour and account['id']==detour['donor']:
                            self.current._fleet_work_order=lambda:()
                        elif state['task_driven'] and state['attack_target_per_hour']:
                            self.current._fleet_building_check_due = self._building_check_due
                            self.current._fleet_research_check_due = self._research_check_due
                        if (not (detour and account['id']==detour['donor'])
                                and state['task_driven'] and state['attack_target_per_hour']
                                and 'farming' in account['roles']):
                            self.current._fleet_farm_due_soon = lambda: self.rotation.farm_due_soon(self.clock())
                            if (self.current.config.farm_enabled and self.current.config.farm_calibrated
                                    and self.current.config.farm_engine == 'automatic' and not self.current.config.dry_run):
                                self.current._fleet_farm_due = lambda: self.rotation.farming_due(
                                    self.rotation.load(), account, self.clock())
                                self.current._fleet_record_farm = lambda **fields: self.rotation.record_farming(
                                    account['id'], self.clock(), **fields)
                                self.current.farmer.finish_after_star = state['finish_after_star']
                            else:
                                self.rotation.record_farming(account['id'], self.clock(), delay=1200)
                        self.activity=('Watching '+account['nickname'] if account['id']==main['id'] and not state['task_driven']
                                       else 'Visiting '+account['nickname'])
                        logger.info('Activity: {}',self.activity)
                        self.current.run_owned()
                        self.rotation.complete(account['id'],self.clock(),self.clock()-started,
                                               suspended=getattr(self,'_visit_suspended',False))
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
                        from coc_bot.donation.chat_check import ChatCheckUnverified
                        try:
                            if not (self._next == main['id'] and daytime_donation_watch(state, self.clock())):
                                self._check_chat_before_switch(account)
                        except ChatCheckUnverified:
                            # This check runs after the visit's bot loop exits.
                            # Retry this account through normal verified startup;
                            # an unreadable chat must never become a switch intent.
                            logger.warning('Account handoff deferred — clan chat is unverified; recovering the current account')
                            from coc_bot.stop import interrupted_sleep
                            if interrupted_sleep(2,self.cancel.is_set):break
                            continue
                        if self.cancel.is_set() or self.finish_action:break
                        if self._next==account['id']:continue
                        target=self.store.account(self._next)
                        if target is None:raise ValueError('Next saved account disappeared')
                        self.activity='Switching to '+target['nickname']
                        from coc_bot.runtime.task_timing import measure_task
                        with measure_task(account['tag'], 'account_switch') as timing:
                            self.store.begin('switch',target['id'])
                            nav=AccountNavigator(self.current,self.cancel.is_set)
                            identity=nav.switch(target)
                            if self.cancel.is_set():
                                timing['outcome'] = 'stopped'
                                break
                            self.store.complete(identity['tag'],hall=identity.get('hall'))
                            timing['outcome'] = 'verified'
                        from coc_bot.accounts.handoff import VerifiedHandoff
                        verified_handoff=VerifiedHandoff(identity['tag'],self.store.profile(target)/'data',
                                                         session.config.adb_device,lease)
        finally:
            self.rotation.pause(self.clock())
