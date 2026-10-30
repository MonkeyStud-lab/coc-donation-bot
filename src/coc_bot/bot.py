from __future__ import annotations

from coc_bot.runtime.device_lease import exclusive_device

import random
import time
from datetime import datetime

import cv2
from loguru import logger

from coc_bot.adb.app import AppController
from coc_bot.adb.capture import ScreenCapture
from coc_bot.adb.client import AdbClient, AdbError, AdbStopped
from coc_bot.adb.input import InputController
from coc_bot.attack.farmer import AttackFarmer
from coc_bot.config import load_config
from coc_bot.donation.chat_monitor import ChatMonitor, DonateRequest
from coc_bot.donation.executor import DonationExecutor
from coc_bot.donation.navigator import Navigator
from coc_bot.donation.request_parser import RequestKind
from coc_bot.runtime.game_state import GameState, GameStateMachine
from coc_bot.runtime.tracker import RuntimeTracker
from coc_bot.stop import interrupted_sleep
from coc_bot.vision.matcher import TemplateMatcher
from coc_bot.vision.screens import BotMode, ScreenClassifier, ScreenType, MODE_LABELS


class DonationBot:
    """Main donation loop orchestrator."""

    def __init__(
        self,
        dry_run: bool = False,
        debug_save_frames: bool = False,
        debug: bool = False,
        record: bool = False,
        record_every: int = 10,
    ) -> None:
        self.config = load_config()
        self.config.dry_run = dry_run
        self.config.debug_save_frames = debug_save_frames
        self._debug = debug
        self._record = record
        self._record_every = max(1, int(record_every))

        if not self.config.calibrated:
            # Raise (not sys.exit) so the GUI worker thread can show an error dialog.
            raise RuntimeError(
                "Calibration not found. Run Setup in the app or: python scripts/calibrate.py"
            )

        self.client = AdbClient(device=self.config.adb_device)
        self.capture = ScreenCapture(self.client)
        # Navigation must always tap (even in dry-run) so the bot can reach clan chat.
        self.nav_input = InputController(
            self.client,
            jitter_px=self.config.tap_jitter_px,
            delay_ms=self.config.action_delay_ms,
            dry_run=False,
        )
        self.donation_input = InputController(
            self.client,
            jitter_px=self.config.tap_jitter_px,
            delay_ms=self.config.action_delay_ms,
            dry_run=dry_run,
        )
        self.capture.bind_input(self.nav_input)
        self.capture.bind_input(self.donation_input)
        self.app = AppController(self.client, self.config, self.capture)
        self.matcher = TemplateMatcher(
            threshold=self.config.template_threshold,
            scale_range=self.config.scale_range,
        )
        self.navigator = Navigator(self.config, self.capture, self.nav_input, self.matcher)
        self.chat_monitor = ChatMonitor(
            self.config, self.capture, self.donation_input, self.matcher, debug=debug
        )
        self.executor = DonationExecutor(self.config, self.capture, self.donation_input, self.matcher)
        self.tracker = RuntimeTracker(self.config)
        self.game_state = GameStateMachine(GameState.BOOT)
        self.farmer = AttackFarmer(
            self.config,
            self.capture,
            self.nav_input,
            self.matcher,
            self.navigator,
            game_state=self.game_state,
        )
        self._state = "boot"
        self._state_entered = time.monotonic()
        self._frame_count = 0
        self._last_anti_idle = time.monotonic()
        self._stop_requested = False
        self._farm_requested = False
        self._farm_fail_cooldown_until = 0.0
        self._next_upgrade_check = 0.0
        self._visit_repeat=False;self._visit_reason=None;self._visit_retry_at=None
        self.last_screen: str = "unknown"
        self.mode = BotMode.DONATE
        self._unknown_streak = 0
        self.navigator.mode = BotMode.DONATE
        self.farmer.attack_nav.mode = BotMode.ATTACK
        self.farmer._on_mode = self.set_mode
        self.farmer.tracker = self.tracker
        from coc_bot.runtime.visits import Visit
        self._visit = Visit(self.config)
        self._visit_chat_pending=True
        self._farm_chat_check_due=False

        # Stop button interrupts long waits (chat navigation, farming, and donations).
        stop = self.should_stop
        self.client.stop_check = stop
        self.app.stop_check = stop
        self.navigator.stop_check = stop
        self.farmer.stop_check = stop
        self.farmer.attack_nav.stop_check = stop
        self.farmer.deployer.stop_check = stop
        self.executor.stop_check = stop

    def set_mode(self, mode: BotMode) -> None:
        """Switch flow context so classify() only considers relevant screens."""
        if mode != self.mode:
            logger.info(
                "Bot mode: {} → {}",
                MODE_LABELS.get(self.mode.value, self.mode.value),
                MODE_LABELS.get(mode.value, mode.value),
            )
        self.mode = mode
        self.navigator.mode = mode
        # Attack navigator stays ATTACK during farm; leave_chat overrides locally.
        if mode in (BotMode.ATTACK, BotMode.HOME, BotMode.ANY):
            self.farmer.attack_nav.mode = mode
        elif mode == BotMode.DONATE:
            self.farmer.attack_nav.mode = BotMode.ATTACK
        self._unknown_streak = 0

    def should_stop(self) -> bool:
        return self._stop_requested

    def request_stop(self) -> None:
        """Ask the bot to stop ASAP (leaves Clash running)."""
        self._stop_requested = True
        logger.info("Stop requested — interrupting current action")

    def request_stop_after_action(self) -> None:
        self._finish_action_requested = True
        logger.info("Settings update queued — finishing current action before stopping")

    def _settings_stop_ready(self) -> bool:
        return (getattr(self, "_finish_action_requested", False)
                and self._state not in ("open_donation", "donate", "farm", "builder_base", "layouts"))

    def request_farm_attack(self) -> None:
        """Queue one farm attack as soon as the loop is not mid-donation."""
        if self.config.account_tag and 'farming' not in self.config.account_roles:
            raise ValueError('This account does not have the farming role')
        self._farm_requested = True
        logger.info("Farm attack requested — will run when not mid-donation")

    @property
    def farm_queued(self) -> bool:
        """True when a manual/auto farm attack is queued for the next safe tick."""
        return bool(self._farm_requested)

    def farm_status_line(self) -> str:
        """Short status for the GUI (next auto farm / cooldown)."""
        if not self.config.farm_enabled:
            return "Farm: disabled"
        if not self.config.farm_calibrated:
            return "Farm: needs calibration (Setup → Farm)"
        from coc_bot.config import normalize_farm_deploy_sequence

        if self.config.farm_engine=='sequence' and not normalize_farm_deploy_sequence(self.config.farm_deploy_sequence).get("taps"):
            return "Farm: needs deploy sequence (Setup → Farm → Deploy tap sequence)"
        if self._farm_requested:
            return "Farm: manual attack queued"
        now = time.monotonic()
        if now < self._farm_fail_cooldown_until:
            left = int(self._farm_fail_cooldown_until - now)
            return f"Farm: retry cooldown {left // 60}m {left % 60}s"
        return (f'Farm: refill below {self.config.farm_resource_start_percent}% '
                f'to {self.config.farm_resource_target_percent}%')


    def screen_status_line(self) -> str:
        """Short screen label for the GUI."""
        from coc_bot.vision.screens import screen_display_name

        return f"Screen: {screen_display_name(self.last_screen)}"

    def _start_recorder(self) -> None:
        """Phase-0 perception data collection (see vision/recorder.py)."""
        from coc_bot.vision import recorder
        from coc_bot.vision.recorder import FrameRecorder, config_fingerprint

        options = recorder.smart_options()
        if options is None and self.config.collection_enabled:
            from coc_bot.vision.collection import CollectionOptions
            try:
                options = CollectionOptions(daily_limit=self.config.collection_daily_limit,
                                            storage_bytes=int(self.config.collection_storage_gb * 1024**3))
            except (ValueError, OverflowError) as exc:
                logger.warning("Invalid screenshot collection limits; bot continues without collection: {}", exc)
                return
        if options is not None:
            from coc_bot.vision.collection import SmartFrameRecorder

            try:
                recorder.start(SmartFrameRecorder(
                    self.config.data_dir / "collection", options=options,
                    seed_export=self.config.data_dir / "labelstudio/review/curated/tasks_curated_screens_v2.json",
                    data_dir=self.config.data_dir,
                    extra_meta={"git_commit": recorder._git_commit(),
                                "calib_frame": [self.config.frame_width, self.config.frame_height],
                                "calib_fingerprint": config_fingerprint(self.config),
                                "dry_run": self.config.dry_run},
                ))
            except Exception as exc:
                logger.warning("Smart collection unavailable; bot continues normally: {}", exc)
            return
        if not self._record:
            return

        recorder.start(
            FrameRecorder(
                self.config.data_dir / "frames",
                every_n=self._record_every,
                extra_meta={
                    "calib_frame": [self.config.frame_width, self.config.frame_height],
                    "calib_fingerprint": config_fingerprint(self.config),
                    "adb_device": self.config.adb_device,
                    "dry_run": self.config.dry_run,
                },
            )
        )

    @exclusive_device
    def run(self) -> None:
        self.run_owned()

    def run_owned(self) -> None:
        """Run under an existing controller lease, including fleet handoffs."""
        logger.info("CoC Donation Bot starting (dry_run={})", self.config.dry_run)
        if self.should_stop():
            return
        from coc_bot.accounts.store import read
        layout=read(self.config.data_dir/'layouts/state.json',{})
        if layout.get('pending') or layout.get('last_survey',{}).get('payment'):
            self.__dict__.pop('_verified_handoff',None)
            if not self._layout_runner().recover():
                raise RuntimeError('Interrupted layout edit could not be safely recovered')
        from coc_bot.accounts.navigation import verify_session
        verify_session(self, self.should_stop)
        self._start_recorder()
        try:
            self._run_inner()
        finally:
            from coc_bot.vision import recorder

            recorder.stop()

    def _run_inner(self) -> None:
        try:
            self.client.health_check()
        except AdbError as exc:
            logger.error("ADB health check failed: {}", exc)
            raise

        from coc_bot.builder_base.runner import BuilderBaseRunner, pending as builder_pending
        if builder_pending(self.config):
            BuilderBaseRunner(self.config,self.capture,self.nav_input,self.navigator,
                              self.client,self.should_stop).recover()
        from coc_bot.attack.planned_farmer import context
        from coc_bot.attack.recovery import recover_attack, pending
        from coc_bot.runtime.screenshot_retention import prune_attack_diagnostics
        if pending(self.config):
            self.game_state.transition(GameState.RECOVERING, reason='resume interrupted attack')
        recover_attack(context(self.farmer), tracker=self.tracker)
        prune_attack_diagnostics(self.config.data_dir)
        self.tracker.start_loop_timing()

        self.set_mode(BotMode.DONATE)
        try:
            if not self.navigator.ensure_clan_chat(has_donate_request=self._has_donate_request):
                if self._stop_requested:
                    logger.info("Bot stopped")
                    return
                logger.error("Could not reach clan chat on startup")
                raise RuntimeError("Could not reach clan chat on startup")

            self.set_mode(BotMode.DONATE)
            self.game_state.transition(GameState.CLAN_CHAT if getattr(self.config,'donation_enabled',True) else GameState.HOME, reason="startup")
            self._set_state("scan_chat")
            self._last_anti_idle = time.monotonic()

            handed_off=False
            while not self._stop_requested:
                if self._settings_stop_ready():
                    break
                try:
                    # A fleet checkpoint performs fresh navigation/OCR too.
                    # Keep it inside the same recoverable boundary as a tick.
                    if (self._state in ('scan_chat','scroll_chat') and
                        getattr(self,'_fleet_should_yield',lambda:False)()):
                        handed_off=not self.should_stop()
                        break
                    self._loop_tick()
                except KeyboardInterrupt:
                    logger.info("Shutting down...")
                    self.tracker.tick()
                    break
                except AdbError as exc:
                    if self._stop_requested:
                        break
                    logger.error("ADB error: {} — reconnecting...", exc)
                    if interrupted_sleep(3, self.should_stop):
                        break
                    try:
                        self.client.ensure_connected()
                    except AdbStopped:
                        break
                except Exception as exc:
                    if self._stop_requested:
                        break
                    logger.exception("Unexpected error: {}", exc)
                    self._recover()
                    if interrupted_sleep(2, self.should_stop):
                        break

            self.tracker.tick()
            logger.info('Account visit complete — handing off' if handed_off else 'Bot stopped')
        finally:
            # Keep active runtime frozen while the controller is stopped.
            self.tracker.pause()

    def _loop_tick(self) -> None:
        if self._stop_requested or self._settings_stop_ready():
            return
        from coc_bot.attack.recovery import pending
        from coc_bot.builder_base.runner import pending as builder_pending
        if pending(self.config) or builder_pending(self.config):
            self._recover()
            return
        if (getattr(self,'_farm_chat_check_due',False) is True
            and not callable(getattr(self,'_fleet_should_yield',None))):
            from coc_bot.accounts.store import read
            layout=read(self.config.data_dir/'layouts/state.json',{})
            blocked=(read(self.config.data_dir/'upgrades/state.json',{}).get('pending')
                     or layout.get('pending') or layout.get('last_survey',{}).get('payment'))
            if not blocked and self._check_chat_between_attacks():
                self.tracker.tick();return
        self._check_watchdog()
        if self._stop_requested or self._settings_stop_ready():
            return
        self._maybe_anti_idle()
        if self._stop_requested:
            return


        # Farm between donation states only — never mid open_donation / donate.
        if self._settings_stop_ready():
            return
        work={'requests':self._maybe_request_reinforcements,'upgrades':self._maybe_run_upgrades,'farm':self._maybe_run_farm,'layouts':self._maybe_run_layouts,
              'builder_base':self._maybe_run_builder_base}
        visit=getattr(self,'_visit',None)
        from coc_bot.accounts.store import read
        if (visit and getattr(self,'_visit_chat_pending',False)
            and getattr(self.config,'donation_enabled',True)
            and not read(self.config.data_dir/'upgrades/state.json',{}).get('pending')
            and not read(self.config.data_dir/'layouts/state.json',{}).get('pending')
            and not read(self.config.data_dir/'layouts/state.json',{}).get('last_survey',{}).get('payment')):
            if self._state in ('scan_chat','scroll_chat'):
                self._do_scan_chat()
                # Continue existing donation states before maintenance work.
                self._visit_chat_pending=self._state in ('open_donation','donate')
            elif self._state=='open_donation':self._do_open_donation()
            elif self._state=='donate':self._do_donate()
            self.tracker.tick();return
        order=getattr(self,'_fleet_work_order',lambda:visit.order() if visit else tuple(work))()
        if visit and self._state in ('open_donation','donate'):order=()
        from coc_bot.accounts.store import read
        layout=read(self.config.data_dir/'layouts/state.json',{})
        from coc_bot.layouts.runner import REVISION
        automatic=layout.get('automatic',{})
        hall=getattr(self.config,'account_town_hall',None)
        new_layout=(automatic.get('hall')!=hall or automatic.get('revision')!=REVISION)
        needs_layout=(new_layout or automatic.get('stage')!='active'
                      or automatic.get('dirty') or not layout.get('completed',{}).get('home_verified'))
        if (getattr(self.config,'layouts_enabled',False) and type(hall) is int and hall>=4
            and needs_layout and (new_layout or time.time()>=automatic.get('next_check_at',0))):
            # First setup / Hall changes must not keep losing whole visits to
            # due farm attacks. LayoutRunner is bounded, and its existing fresh
            # donation-request check still gives visible requests priority.
            order=('layouts',)+tuple(name for name in order if name!='layouts')
        if layout.get('pending') or layout.get('last_survey',{}).get('payment'):
            order=('layouts',)
        # An explicit Farm now request keeps its usual priority over scheduled
        # work. Each method still enforces its own permissions and due time.
        if self._farm_requested and order!=('layouts',):order=('farm',)+tuple(name for name in order if name!='farm')
        from coc_bot.upgrades.runner import UpgradeRunner
        upgrade_pending=UpgradeRunner(self.config,self.capture,self.nav_input,self.navigator).state().get('pending')
        if upgrade_pending and order!=('layouts',):
            # A saved payment outcome must be resolved before another feature
            # can leave this village, including a rotated/manual farm turn.
            order=('upgrades',)
        for name in order:
            if self.should_stop():return
            self._visit_repeat=False;self._visit_reason=None;self._visit_retry_at=None
            urgent=(name=='upgrades' and upgrade_pending or name=='layouts' and
                    (layout.get('pending') or layout.get('last_survey',{}).get('payment')))
            deferred=visit.deferred(name) if visit and not urgent else None
            if deferred:
                self._visit_reason=deferred.get('reason');self._visit_retry_at=deferred['retry_at']
                attempted=False
            else:
                if visit and name=='upgrades':self._next_upgrade_check=0
                attempted=work[name]()
            pending_after=UpgradeRunner(self.config,self.capture,self.nav_input,self.navigator).state().get('pending') if visit else None
            unresolved=(pending_after or builder_pending(self.config) or pending(self.config)) if visit else None
            if visit and not unresolved and self._state in ('scan_chat','scroll_chat') and not self.should_stop():
                visit.finish_step(name,repeat=self._visit_repeat,reason=self._visit_reason,retry_at=self._visit_retry_at)
                self._visit_chat_pending=True
                getattr(self,'_fleet_after_step',lambda:None)()
            if attempted:
                getattr(self,'_fleet_work_attempted',lambda _:None)(name)
                self.tracker.tick()
                if name=='farm':
                    lo,hi=self.config.scan_interval_ms
                    interrupted_sleep(random.uniform(lo,hi)/1000.0,self.should_stop)
                return
            if visit:
                self.tracker.tick()
                return

        if not getattr(self.config,'donation_enabled',True):
            self.tracker.tick()
            self._state_entered = time.monotonic()
            interrupted_sleep(2, self.should_stop)
            return

        if self._state == "scan_chat":
            self._do_scan_chat()
        elif self._state == "scroll_chat":
            self._do_scroll_chat()
        elif self._state == "open_donation":
            self._do_open_donation()
        elif self._state == "donate":
            self._do_donate()
        else:
            self._set_state("scan_chat")

        if self._stop_requested:
            return

        self.tracker.tick()
        lo, hi = self.config.scan_interval_ms
        interrupted_sleep(random.uniform(lo, hi) / 1000.0, self.should_stop)

    def _layout_runner(self):
        from types import SimpleNamespace
        from coc_bot.layouts.runner import LayoutRunner
        return LayoutRunner(SimpleNamespace(config=self.config,capture=self.capture,input=self.nav_input,
                            client=self.client,navigator=self.navigator),self.should_stop)

    def _maybe_run_layouts(self):
        from coc_bot.accounts.store import read
        from coc_bot.layouts.runner import REVISION
        state=read(self.config.data_dir/'layouts/state.json',{})
        unresolved=state.get('pending') or state.get('last_survey',{}).get('payment')
        if not unresolved and (not getattr(self.config,'layouts_enabled',False) or self.config.dry_run):return False
        if self._state not in ('scan_chat','scroll_chat') or self.should_stop():return False
        automatic=state.get('automatic',{})
        if (not unresolved and automatic.get('hall')==self.config.account_town_hall
            and automatic.get('revision')==REVISION
            and time.time()<automatic.get('next_check_at',0)):return False
        if not unresolved and self._has_donate_request(self.capture.screenshot()):
            self._visit_repeat=True;return False
        runner=self._layout_runner()
        self.set_mode(BotMode.HOME)
        self._set_state('layouts')
        try:
            result=runner.run(seconds=90)
            logger.info('Automatic layout: {} — {}',result.get('status'),result.get('message',''))
            if result.get('status') in ('unavailable','current','disabled'):
                runner.record(next_check_at=time.time()+3600)
            remaining=read(runner.i.path,{})
            if remaining.get('pending') or remaining.get('last_survey',{}).get('payment'):
                raise RuntimeError('Automatic layout retained an unresolved edit or payment')
        finally:
            self.set_mode(BotMode.DONATE)
            remaining=read(runner.i.path,{})
            if not self.should_stop() and not (remaining.get('pending') or remaining.get('last_survey',{}).get('payment')):
                self._set_state('scan_chat')
            self._state_entered=time.monotonic()
        return True

    def _maybe_run_builder_base(self) -> bool:
        hall=getattr(self.config,'account_town_hall',None)
        if type(hall) is int and hall<6:
            return False  # Builder Base is not unlocked; do not start a boat journal.
        if (self._state not in ('scan_chat','scroll_chat') or self.should_stop()
                or self.config.dry_run or not (self.config.builder_base_attacks_enabled
                                               or self.config.builder_base_upgrades_enabled
                                               or getattr(self.config, 'builder_base_research_enabled', False)
                                               or getattr(self.config, 'builder_base_collect_resources', False))):
            return False
        from coc_bot.builder_base.runner import BuilderBaseRunner, state
        from coc_bot.builder_base.verification import deferred
        if deferred(self.config):
            self._visit_retry_at=time.time()+3600
            self._visit_reason='Builder upgrades paused for receipt review'
            return False
        visit = state(self.config)
        if not getattr(self,'_visit',None) and time.time() < visit.get('next_visit_at',0):
            return False
        if self._has_donate_request(self.capture.screenshot()):
            self._visit_repeat=True
            return False
        self._set_state('builder_base')
        self.game_state.transition(GameState.BUILDER_BASE,reason='scheduled visit')
        runner = BuilderBaseRunner(self.config,self.capture,self.nav_input,self.navigator,
                                   self.client,self.should_stop)
        try:
            result = runner.run(refill=True) if getattr(self,'_visit',None) else runner.run()
        except ValueError as exc:
            if not getattr(self,'_visit',None) or self.should_stop():raise
            # Recover/close the journal before deferring this step. An uncertain
            # payment or battle that cannot recover still raises and owns input.
            runner.recover()
            from coc_bot.builder_base.runner import pending as builder_pending
            if builder_pending(self.config):raise
            result={'retry_at':time.time()+900,'message':str(exc),'status':'deferred'}
        self._visit_repeat=result.get('visit_repeat',False)
        if result.get('retry_at'):
            self._visit_retry_at=result['retry_at'];self._visit_reason=result.get('message')
        logger.info('Builder Base visit completed: {}',result)
        self.set_mode(BotMode.DONATE)
        self.game_state.transition(GameState.CLAN_CHAT,reason='Builder Base return verified')
        self._set_state('scan_chat')
        self._state_entered = time.monotonic()
        return True

    def _maybe_request_reinforcements(self) -> bool:
        if self._state not in ('scan_chat','scroll_chat') or self.should_stop():return False
        from coc_bot.donation.reinforcements import request_if_empty,eligible
        if not eligible(self.config):return False
        from coc_bot.attack.planned_farmer import context
        try:
            result=request_if_empty(context(self.farmer))
            if result:logger.info('Clan Castle request check finished')
            return result
        finally:
            self._state_entered=time.monotonic()

    def _maybe_run_upgrades(self) -> bool:
        if self._state not in ('scan_chat','scroll_chat') or self._stop_requested or self.config.dry_run:
            return False
        kinds=[kind for kind,enabled in (
            ('buildings',self.config.upgrade_buildings_enabled),
            ('research',self.config.upgrade_research_enabled),
            ('pets',getattr(self.config,'upgrade_pets_enabled',False))) if enabled]
        if not kinds or time.monotonic()<self._next_upgrade_check:
            return False
        frame=self.capture.screenshot()
        if self._has_donate_request(frame):
            self._visit_repeat=True
            return False
        self._next_upgrade_check=time.monotonic()+self.config.upgrade_interval_seconds
        from coc_bot.upgrades.runner import UpgradeRunner
        try:
            self.set_mode(BotMode.HOME)
            self.game_state.transition(GameState.HOME,reason='leave chat for upgrade check')
            self.game_state.transition(GameState.UPGRADING,reason='Suggested upgrades')
            if getattr(self.config,'progression_enabled',False):
                from coc_bot.progression.runner import ProgressionRunner
                runner=ProgressionRunner(self.config,self.capture,self.nav_input,self.navigator,self.should_stop)
            else:
                runner=UpgradeRunner(self.config,self.capture,self.nav_input,self.navigator,self.should_stop)
            # Give each single-slot category a turn before filling remaining
            # builders. Each successful payment is independently verified by
            # the runner; an uncertain outcome stops the entire pass.
            from coc_bot.accounts.store import read, write
            visit=getattr(self,'_visit',None)
            maintenance_path=self.config.data_dir/'upgrades/maintenance.json'
            maintenance=read(maintenance_path,{})
            visit_id=visit.load()['started_at'] if visit else None
            saved=maintenance.get('remaining')
            queue=(list(saved) if visit and maintenance.get('visit')==visit_id
                   and isinstance(saved,list) and saved and all(k in kinds for k in saved) else list(kinds))
            attempts=0
            # Each paid transaction is followed by the ordinary chat checkpoint.
            # Persist the remaining categories so a donor detour cannot starve lab/pets.
            while queue and attempts<(1 if visit else 10):
                kind=queue.pop(0)
                if self._stop_requested: break
                result=runner.run(kind,execute=True)
                from coc_bot.runtime.verification import log_result
                log_result(self.config,'home.'+kind,result,pending=runner.state().get('pending'))
                attempts+=1
                logger.info('Upgrade check ({}): {} — {}',kind,result.get('status'),
                            result.get('message','No resource spending requested'))
                maintenance.setdefault('categories',{})[kind]={
                    'at':time.time(),'status':result.get('status'),'message':result.get('message'),
                    'availability':result.get('availability')}
                if result.get('status') in ('needs_review','stopped','blocked','changed','no_room'):
                    if not result.get('retry_other_candidates'):
                        self._visit_retry_at=time.time()+300
                        self._visit_reason=result.get('message',result['status'])
                    if result.get('status') in ('needs_review','stopped') or runner.state().get('pending'):break
                    if result.get('retry_other_candidates') and kind=='buildings':queue.append(kind)
                    continue  # A pre-payment building issue must not starve lab/pets.
                if kind=='buildings' and result.get('status') in ('started','built','recovered'):
                    # Rescan after construction/upgrade; never reuse the old
                    # balance, builder count, price, or selected row.
                    queue.append(kind)
                    if self._has_donate_request(self.capture.screenshot()): break
            maintenance.update(account=getattr(self.config,'account_tag',None),visit=visit_id,
                               remaining=queue,checked_at=time.time(),next_check_at=time.time()+300)
            write(maintenance_path,maintenance)
            self._visit_repeat=bool(queue) and not getattr(self,'_visit_retry_at',None)
            if self._visit_repeat:self._next_upgrade_check=0
        finally:
            # Long inventory reads must not make the next check overdue before
            # this one finishes, starving farming and donation scans.
            self._next_upgrade_check=time.monotonic()+self.config.upgrade_interval_seconds
            self._state_entered=time.monotonic()
            self.set_mode(BotMode.DONATE)
            if not self._stop_requested:
                frame=self.capture.screenshot()
                verified=self.navigator.classifier._clan_chat_anchor_visible(frame)
                self.game_state.transition(GameState.HOME if not getattr(self.config,'donation_enabled',True) else GameState.CLAN_CHAT if verified else GameState.RECOVERING,
                                           reason='upgrade check finished')
        return True

    def _resource_state(self):
        from coc_bot.accounts.store import read
        state=read(self.config.data_dir/'resources/home.json',{})
        if state and state.get('account',self.config.account_tag)!=self.config.account_tag:
            raise ValueError('Resource observations belong to a different account')
        return state

    def _save_resource_state(self, state):
        from coc_bot.accounts.store import write
        write(self.config.data_dir/'resources/home.json',state|{'account':self.config.account_tag})

    def _observe_resources(self):
        from coc_bot.progression.resources import HomeResources
        return HomeResources(self.navigator).observe(self.config)

    def _resource_farm_due(self):
        from coc_bot.runtime.resource_farming import decide
        state=self._resource_state()
        if time.time()<state.get('retry_at',0):
            self._visit_reason=state.get('message','Resource farming paused')
            self._visit_retry_at=state['retry_at'];return False
        observation=self._observe_resources()
        decision=decide(observation,state,start=self.config.farm_resource_start_percent,
                        stop=self.config.farm_resource_target_percent)
        state.update(observation=observation,observed_at=time.time(),status=decision.status,message=decision.message)
        self._visit_reason=decision.message
        if decision.status=='unverified':
            state['retry_at']=time.time()+300;self._visit_retry_at=state['retry_at']
        if decision.attack and state.get('no_progress',0)>=3:
            state.update(retry_at=time.time()+900,message='Three attacks produced no verified resource gain',no_progress=0)
            self._visit_retry_at=state['retry_at'];self._visit_reason=state['message']
            self._save_resource_state(state);return False
        self._save_resource_state(state)
        logger.info('Resource farming: {}',decision.message)
        self._refill_before=observation;self._refill_resources=decision.resources
        return decision.attack

    def _farm_due(self) -> bool:
        if self._farm_requested:
            return True
        if not self.config.farm_enabled:
            return False
        if not self.config.farm_calibrated:
            return False
        if time.monotonic() < self._farm_fail_cooldown_until:
            self._visit_retry_at=time.time()+self._farm_fail_cooldown_until-time.monotonic()
            self._visit_reason='Attack retry cooldown'
            return False
        if self.config.dry_run:return False
        return self._resource_farm_due()

    def _check_chat_between_attacks(self):
        from coc_bot.donation.chat_check import peek_requests
        if not getattr(self.config,'donation_enabled',True):
            logger.info('Between attacks: no donating role or account rotation is enabled')
            self._farm_chat_check_due=False
            return False
        logger.info('Between attacks: checking clan chat before another refill battle')
        request=peek_requests(self.capture,self.navigator,self.chat_monitor,self.should_stop)
        if self.should_stop():return True
        self._farm_chat_check_due=False
        if request is not None and self._should_handle_request(request):
            self._pending_request=request;self._visit_chat_pending=True
            self._set_state('open_donation')
            return True
        logger.info('Between attacks: clan chat check complete')
        return False

    def _maybe_run_farm(self) -> bool:
        """Run one farm cycle if due. Returns True if farm work was attempted."""
        if self._state in ("donate", "open_donation"):
            return False
        if not self._farm_due():
            return False

        manual = self._farm_requested
        self._farm_requested = False
        if not self.config.farm_calibrated:
            logger.warning("Farm requested but calibration incomplete — skipping")
            return True
        from coc_bot.config import normalize_farm_deploy_sequence

        if self.config.farm_engine=='sequence' and not normalize_farm_deploy_sequence(self.config.farm_deploy_sequence).get("taps"):
            logger.warning(
                "Farm requested but no deploy tap sequence is programmed — skipping "
                "(Setup → Farm → Deploy tap sequence)"
            )
            return True
        if not manual and not self.config.farm_enabled:
            return False

        logger.info('Pausing donations for resource refill attack (manual={})',manual)
        self._set_state("farm")
        self.game_state.transition(GameState.HOME, reason="farm start")
        self.set_mode(BotMode.HOME)
        result = self.farmer.run_one_attack()
        from coc_bot.vision import recorder

        if not self._stop_requested:
            recorder.note_event("action_confirmed" if result.success else "farm_failed",
                                action="farm", reason=result.reason)
        if self._stop_requested:
            self.set_mode(BotMode.DONATE)
            self.game_state.transition(GameState.CLAN_CHAT, reason="farm stopped")
            self._set_state("scan_chat")
            return True
        # Interval clock advances after a fought battle even if leave/chat fails.
        # Otherwise leave bugs retry every farm_retry_cooldown_seconds (~minutes).
        from coc_bot.attack.recovery import pending
        if result.success or result.counts_toward_interval:
            if not result.interval_recorded and not pending(self.config):
                self.tracker.mark_farm_success()
            self._farm_fail_cooldown_until = 0.0
            if not result.success:
                logger.warning('Farm attempt did not complete ({}) — recovery is required',result.reason)
        else:
            cooldown = max(60, int(self.config.farm_retry_cooldown_seconds))
            self._farm_fail_cooldown_until = time.monotonic() + cooldown
            logger.warning(
                "Farm failed before deploy ({}) — retry cooldown {}s",
                result.reason,
                cooldown,
            )
        from coc_bot.attack.recovery import pending
        if pending(self.config):
            self._recover()
            self._visit_retry_at=time.time()+300
            self._visit_reason='Attack recovery must finish before another refill battle'
            return True
        self.set_mode(BotMode.DONATE)
        if not self._stop_requested:
            self.navigator.ensure_clan_chat(has_donate_request=self._has_donate_request)
        self.game_state.transition(GameState.CLAN_CHAT if getattr(self.config,'donation_enabled',True) else GameState.HOME, reason="farm done")
        self._set_state("scan_chat")
        self._last_anti_idle = time.monotonic()
        if not manual and not self._stop_requested:
            state=self._resource_state()
            if result.success:
                from coc_bot.runtime.resource_farming import record_outcome,decide
                after=self._observe_resources()
                resources=getattr(self,'_refill_resources',())
                record_outcome(state,getattr(self,'_refill_before',{}).get('balances',{}),
                               after.get('balances',{}),resources)
                decision=decide(after,state,start=self.config.farm_resource_start_percent,
                                stop=self.config.farm_resource_target_percent)
                state.update(observation=after,observed_at=time.time(),status=decision.status,message=decision.message)
                self._visit_reason=decision.message
                if decision.status=='unverified':
                    state['retry_at']=time.time()+300
                    self._visit_retry_at=state['retry_at'];self._visit_reason='Post-battle resources are unreadable'
                else:self._visit_repeat=decision.attack
            else:
                state['retry_at']=time.time()+max(60,self.config.farm_retry_cooldown_seconds)
                self._visit_retry_at=state['retry_at'];self._visit_reason=result.reason
            self._save_resource_state(state)
        self._farm_chat_check_due=True
        self._visit_chat_pending=True
        getattr(self,'_fleet_after_step',lambda:None)()
        return True

    def _maybe_anti_idle(self) -> None:
        """Tiny chat-panel swipe so CoC does not disconnect for inactivity."""
        if not getattr(self.config,'donation_enabled',True):
            return
        interval = max(20, int(self.config.anti_idle_seconds))
        # Jitter so the nudge is not perfectly metronomic.
        due = interval + random.uniform(-8, 8)
        if time.monotonic() - self._last_anti_idle < due:
            return
        # Don't interrupt donation taps / panel opens.
        if self._state in ("donate", "open_donation"):
            return

        from coc_bot.accounts.store import read
        from coc_bot.upgrades.runner import UpgradeRunner
        layout=read(self.config.data_dir/'layouts/state.json',{})
        if (UpgradeRunner(self.config,self.capture,self.nav_input,self.navigator).state().get('pending')
            or layout.get('pending') or layout.get('last_survey',{}).get('payment')):
            return
        # The loop state alone is not evidence that chat is still on screen.
        self._last_anti_idle=time.monotonic()
        frame=self.capture.screenshot()
        if self.should_stop() or not self.navigator.classifier._clan_chat_anchor_visible(frame):
            return

        w = self.config.frame_width or 1853
        h = self.config.frame_height or 1048
        if "chat_panel" in self.config.rois:
            from coc_bot.vision.rois import ROI, roi_center

            cx, cy = roi_center(ROI(*self.config.rois["chat_panel"]), w, h)
        else:
            cx, cy = int(w * 0.32), int(h * 0.55)

        dist = random.randint(45, 90)
        logger.debug("Anti-idle nudge at ({}, {})", cx, cy)
        self.nav_input.swipe(cx, cy + dist // 2, cx, cy - dist // 2, duration_ms=200)
        if interrupted_sleep(.12,self.should_stop):return
        self.nav_input.swipe(cx, cy - dist // 2, cx, cy + dist // 2, duration_ms=200)
        self._last_anti_idle = time.monotonic()

    def _should_handle_request(self, request: DonateRequest) -> bool:
        if request.kind == RequestKind.SPECIFIC:
            return True
        # Open and hybrid use simple colored-slot fill when enabled.
        return self.config.donate_open_requests

    def _has_donate_request(self, frame) -> bool:
        if not getattr(self.config,'donation_enabled',True):
            return False
        request = self.chat_monitor.find_donate_request(frame)
        return request is not None and self._should_handle_request(request)

    def _ensure_chat_open(self, frame=None) -> bool:
        """
        Re-open clan chat if the user closed it or we drifted to home/unknown.

        The scan/scroll loop alone never calls ensure_clan_chat, so closing chat
        manually used to leave the bot stuck looking for Donate forever.
        """
        if frame is None:
            frame = self.capture.screenshot()
        screen = self.navigator.classify(frame, mode=BotMode.DONATE)
        self.last_screen = screen.value
        global_chat = screen != ScreenType.DONATION_PANEL and self.navigator.classifier.is_global_chat(
            frame, allow_ocr=False)
        if screen in (ScreenType.CLAN_CHAT, ScreenType.DONATION_PANEL) and not global_chat:
            self._unknown_streak = 0
            return True
        if screen in (ScreenType.UNKNOWN, ScreenType.LOADING):
            # LOADING is expected briefly (game boot, returning from battle) but a
            # long streak means the game hung; treat it like UNKNOWN with a longer fuse.
            self._unknown_streak += 1
            limit = 3 if screen == ScreenType.UNKNOWN else 12
            if self._unknown_streak >= limit:
                logger.warning(
                    "Donate mode saw {} x{} — full recovery",
                    screen.value,
                    self._unknown_streak,
                )
                self._recover()
                return False
            if screen == ScreenType.LOADING:
                return False
        else:
            self._unknown_streak = 0

        logger.info("{} — reopening clan chat", "Global chat is open" if global_chat
                    else f"Chat not open (screen={screen.value})")
        ok = self.navigator.ensure_clan_chat(has_donate_request=self._has_donate_request)
        self.set_mode(BotMode.DONATE)
        if not ok:
            logger.warning("Could not reopen clan chat")
        return ok

    def _do_scan_chat(self) -> None:
        frame = self.capture.screenshot()
        self._maybe_save_debug(frame, "scan")

        if not self._ensure_chat_open(frame):
            self._set_state("scan_chat")
            return

        # Re-capture after a possible reopen so Donate search uses a fresh frame.
        frame = self.capture.screenshot()
        request = self.chat_monitor.find_donate_request(frame)
        if request is None:
            self._set_state("scroll_chat")
            return

        if not self._should_handle_request(request):
            logger.info(
                "Skipping {} request — only specific requests are enabled",
                request.kind.value,
            )
            self.chat_monitor.mark_handled(request)
            return

        self._pending_request = request
        self._set_state("open_donation")

    def _do_scroll_chat(self) -> None:
        frame = self.capture.screenshot()
        if not self._ensure_chat_open(frame):
            self._set_state("scan_chat")
            return

        frame = self.capture.screenshot()
        request = self.chat_monitor.find_donate_request(frame)
        if request is not None:
            if not self._should_handle_request(request):
                logger.info(
                    "Skipping {} request — only specific requests are enabled",
                    request.kind.value,
                )
                self.chat_monitor.mark_handled(request)
            else:
                self._pending_request = request
                self._set_state("open_donation")
            return
        self.navigator.seek_donation_requests_step(frame, self._has_donate_request)
        self._set_state("scan_chat")

    def _do_open_donation(self) -> None:
        if not hasattr(self, "_pending_request"):
            self._set_state("scan_chat")
            return
        if self.config.dry_run:
            m = self._pending_request.button_match
            logger.info(
                "[DRY-RUN] Would tap Donate at ({}, {}), conf={:.2f}",
                m.center[0],
                m.center[1],
                m.confidence,
            )
            self._set_state("donate")
            return

        classifier = ScreenClassifier(self.config, self.matcher)
        opened = False
        for attempt in range(2):
            if self._stop_requested:
                return
            self.chat_monitor.open_donation(self._pending_request)
            if classifier.wait_for_donation_panel(
                self.capture,
                timeout_seconds=self.config.donation_panel_wait_seconds,
                should_stop=self.should_stop,
            ):
                opened = True
                break
            if self._stop_requested:
                return
            logger.warning(
                "Donation panel did not appear after tapping Donate (attempt {})",
                attempt + 1,
            )
            from coc_bot.vision import recorder

            recorder.note_event("donation_open_failed", attempt=attempt + 1)
            if interrupted_sleep(0.4, self.should_stop):
                return

        if self._stop_requested:
            return

        if not opened:
            logger.warning(
                "Donation panel still not detected — leaving request unmarked so it can retry. "
                "If this keeps happening, recalibrate donation_troop_bar (and donation_spell_bar "
                "when present) or capture a donation_panel template. Troop-only clan castles "
                "have no spell/siege strip — that is supported."
            )
            self._pending_request = None
            self._set_state("scroll_chat")
            return
        if interrupted_sleep(0.3, self.should_stop):
            return
        from coc_bot.vision import recorder

        recorder.note_event("action_confirmed", action="donation_open", source="existing_rules")
        self._set_state("donate")

    def _do_donate(self) -> None:
        if self._stop_requested:
            return
        request = getattr(self, "_pending_request", None)
        if request is None:
            self._set_state("scan_chat")
            return
        if self.config.dry_run:
            frame = self.capture.screenshot()
            self._maybe_save_debug(frame, "donate_dry_run")
            logger.info(
                "[DRY-RUN] Would execute donation kind={} (open fill=colored slots)",
                request.kind.value,
            )
            self._pending_request = None
            self._set_state("scan_chat")
            return

        donated = self.executor.donate_for_request(
            is_specific=request.is_specific,
            kind=request.kind,
            capacity=request.capacity,
        )
        logger.info("Donation round complete (donated={})", donated)
        from coc_bot.vision import recorder

        recorder.note_event("action_confirmed", action="donation_round", donated=donated)
        if not donated:
            logger.info(
                "No donation made — marking request handled to avoid reopening "
                "(likely open/generic misclassified or already filled)"
            )
            self.chat_monitor.mark_handled(request)
        self._pending_request = None
        self._set_state("scan_chat")

    def _recover(self) -> None:
        """Desync recovery: full screen scan first, then BACK only if safe, then reopen clan chat."""
        logger.info("Running recovery sequence (full classify)")
        from coc_bot.vision import recorder

        recorder.note_event("recovery", state=self._state)
        self.game_state.transition(GameState.RECOVERING, reason="watchdog/desync")
        from coc_bot.upgrades.runner import UpgradeRunner
        upgrade=UpgradeRunner(self.config,self.capture,self.nav_input,self.navigator).state().get('pending')
        if upgrade:
            from coc_bot.runtime.verification import record_failure
            record_failure(self.config,'home.recovery','Unresolved upgrade blocks generic navigation',pending=upgrade)
            raise RuntimeError('Unresolved Home upgrade receipt; generic recovery navigation is blocked')
        from coc_bot.accounts.store import read
        layout=read(self.config.data_dir/'layouts/state.json',{})
        if layout.get('pending') or layout.get('last_survey',{}).get('payment'):
            if not self._layout_runner().recover():
                raise RuntimeError('Layout recovery is uncertain; automatic navigation stopped')
            if not self.navigator.ensure_clan_chat():
                raise RuntimeError('Home could not be verified after layout recovery')
            self._set_state('scan_chat');self._state_entered=time.monotonic()
            return
        from coc_bot.builder_base.runner import BuilderBaseRunner, pending as builder_pending
        if builder_pending(self.config):
            BuilderBaseRunner(self.config,self.capture,self.nav_input,self.navigator,
                              self.client,self.should_stop).recover()
            self.set_mode(BotMode.DONATE)
            self.game_state.transition(GameState.CLAN_CHAT,reason='Builder Base return verified')
            self._set_state('scan_chat')
            self._state_entered = time.monotonic()
            return
        from coc_bot.attack.recovery import pending, recover_attack
        from coc_bot.attack.planned_farmer import context
        if pending(self.config):
            # Let failure reach the controller: no repeated generic BACK/chat
            # loop when attack recovery is blocked or checkpoint is corrupt.
            recover_attack(context(self.farmer), tracker=self.tracker)
            self._farm_chat_check_due=True
            self.set_mode(BotMode.DONATE)
            self.game_state.transition(GameState.CLAN_CHAT, reason='interrupted attack recovered')
            self._set_state('scan_chat')
            self._state_entered = time.monotonic()
            return
        self.set_mode(BotMode.ANY)
        frame = self.capture.screenshot()
        screen = self.navigator.classify(frame, mode=BotMode.ANY)
        self.last_screen = screen.value
        logger.info("Recovery saw screen={}", screen.value)
        if screen in (
            ScreenType.ATTACK_MENU,
            ScreenType.MATCHMAKING,
            ScreenType.BATTLE,
            ScreenType.BATTLE_RESULTS,
        ):
            # Never send BACK here: in a live battle it opens the Surrender dialog.
            try:
                self.farmer.attack_nav.return_home_from_attack()
            except Exception:  # noqa: BLE001
                logger.exception("return_home during recovery failed")
        elif screen in (ScreenType.SHOP, ScreenType.CLASH_PASS, ScreenType.BUILD_MENU):
            # ensure_clan_chat closes these using a verified X and fresh frames.
            # Do not send a generic BACK or assume the village is already ready.
            pass
        elif self.navigator.classifier.find_reload_game_button(frame) is not None:
            # Reload is the only action that clears Android's inactivity dialog.
            if self.navigator._dismiss_popup(frame) is False:
                return
        elif screen not in (ScreenType.HOME, ScreenType.CLAN_CHAT, ScreenType.LOADING):
            # Unknown overlay/popup — BACK is the generic dismiss.
            self.nav_input.back()
            if interrupted_sleep(0.5, self.should_stop):
                return
        if self._stop_requested:
            return
        self.set_mode(BotMode.DONATE)
        chat_ready = self.navigator.ensure_clan_chat(has_donate_request=self._has_donate_request)
        if chat_ready:
            self.game_state.transition(GameState.CLAN_CHAT, reason="recovery done")
        else:
            logger.warning("Recovery has not confirmed clan chat")
        self._set_state("scan_chat")
        # Recovery always restarts the watchdog clock, even if we were already in scan_chat.
        self._state_entered = time.monotonic()
        self._unknown_streak = 0

    def _check_watchdog(self) -> None:
        # Farm battles routinely exceed state_watchdog_seconds.
        if self._state == "farm":
            return
        elapsed = time.monotonic() - self._state_entered
        if elapsed > self.config.state_watchdog_seconds:
            logger.warning(
                "Watchdog timeout in loop '{}' / GameState '{}' ({:.0f}s)",
                self._state,
                self.game_state.state.value,
                elapsed,
            )
            self._recover()

    def _set_state(self, state: str) -> None:
        if state == self._state:
            # Re-entering the same state must NOT reset the watchdog timer,
            # otherwise a state that loops on itself (scan_chat on a stuck
            # loading screen) can never trip the watchdog.
            return
        logger.debug("Loop state: {} -> {}", self._state, state)
        # Coarse "farm" is expanded by AttackFarmer into finer GameState steps.
        if state in ('scan_chat','scroll_chat') and not getattr(self.config,'donation_enabled',True):
            self.game_state.transition(GameState.HOME, reason='watching village')
        elif state != "farm":
            self.game_state.note_loop_state(state)
        self._state = state
        self._state_entered = time.monotonic()

    def _maybe_save_debug(self, frame, label: str) -> None:
        if not self.config.debug_save_frames:
            return
        self._frame_count += 1
        debug_dir = self.config.data_dir / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = debug_dir / f"{ts}_{label}_{self._frame_count:04d}.png"
        cv2.imwrite(str(path), frame)
