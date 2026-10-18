"""Durable attack ownership and conservative recovery. Never replay deployment.

All callers must already own DeviceLease. A checkpoint write is mandatory before
input: unlike optional diagnostics, an unwritable checkpoint blocks the action.
"""
import json
import math
import os
from pathlib import Path
import tempfile
import time
import uuid

import cv2
from loguru import logger

from coc_bot.attack.army import check_stop
from coc_bot.vision.screens import BotMode, ScreenType


class RecoveryRequired(ValueError):
    pass


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix=path.name+'.', suffix='.tmp', delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        # Persist the rename on Linux as well as the file's contents.
        if os.name != 'nt':
            descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try: os.fsync(descriptor)
            finally: os.close(descriptor)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class AttackCheckpoint:
    def __init__(self, config):
        self.config = config
        self.path = config.data_dir / 'attack-planner' / 'attack-pending.json'

    def load(self):
        if not self.path.exists():
            return None
        try:
            value = json.loads(self.path.read_text(encoding='utf-8'))
            if (not isinstance(value, dict) or value.get('version') != 1 or
                    not isinstance(value.get('id'), str) or
                    not isinstance(value.get('phase'), str) or
                    not isinstance(value.get('attempts'), int) or value['attempts'] < 0 or
                    not isinstance(value.get('at'), (int, float)) or not math.isfinite(value['at'])):
                raise ValueError('invalid checkpoint fields')
            if value.get('device') != self.config.adb_device:
                raise ValueError('checkpoint belongs to another Android device')
            return value
        except (OSError, ValueError, TypeError) as exc:
            raise RecoveryRequired('Attack checkpoint cannot be read safely. Preserve '
                                   'attack-pending.json and inspect it before restarting: '+str(exc)) from exc

    def begin(self, phase='attack_menu'):
        if self.load() is not None:
            raise RecoveryRequired('An unfinished attack must be recovered before starting another')
        atomic_json(self.path, dict(version=1, id=uuid.uuid4().hex, device=self.config.adb_device,
                                   phase=phase, at=time.time(), attempts=0, deployment_possible=False))

    def update(self, phase=None, **fields):
        value = self.load()
        if value is None:
            return
        value.update(fields)
        if phase is not None:
            value['phase'] = phase
        value['updated_at'] = time.time()
        atomic_json(self.path, value)

    def complete(self):
        # Keep one bounded record for diagnostics before clearing ownership.
        value = self.load()
        if value is not None:
            value.update(phase='completed', completed_at=time.time())
            atomic_json(self.path.with_name('last-attack.json'), value)
            self.path.unlink()


def pending(config):
    return ((config.data_dir/'attack-planner/attack-pending.json').exists() or
            (config.data_dir/'attack-planner/camera-pending.json').exists())


def finish_attack(session, *, tracker=None):
    checkpoint = AttackCheckpoint(session.config)
    state = checkpoint.load()
    if state is None or state['phase'] != 'home_confirmed':
        raise RecoveryRequired('Home must be confirmed before clearing the interrupted attack')
    if state.get('deployment_possible') or state.get('entered_opponent'):
        if tracker is None:
            from coc_bot.runtime.tracker import RuntimeTracker
            tracker = RuntimeTracker(session.config)
            tracker.mark_farm_success(attack_id=state['id'])
            tracker.pause_farm_clock()
        else:
            tracker.mark_farm_success(attack_id=state['id'])
    checkpoint.complete()


def accept_home_zoom_limit(session):
    """Automatic mapping can use a verified nearby game zoom endpoint.

    Preserve a separate reference and block legacy pixel recipes. This never
    grants opponent-map permission and never relaxes their geometry thresholds.
    """
    from coc_bot.vision.battle_menu import home_build_control_visible
    from coc_bot.attack.camera import compare_camera, compare_home_zoom
    from coc_bot.adb.multitouch import Multitouch
    root=session.config.data_dir/'attack-planner'
    marker=root/'camera-pending.json'
    if not marker.exists():
        return False
    original=cv2.imread(str(root/'camera-before.png'))
    before=session.capture.screenshot()
    if original is None or before.shape!=original.shape or not home_build_control_visible(before):
        return False
    def measure(a,b):
        evidence=compare_camera(a,b)
        return evidence if evidence.get('verified') else compare_home_zoom(a,b)
    evidence=measure(original,before)
    if (not (evidence.get('verified') or evidence.get('verified_zoom')) or
            not .93<=evidence.get('scale',0)<=1.07):
        return False
    check_stop(session.client.stop_check)
    with Multitouch(session.client,(before.shape[1],before.shape[0])) as touch:
        touch.pinch()  # One strong zoom-out test; an ignored tiny gesture is not proof.
    session._sleep(.7)
    after=session.capture.screenshot()
    check_stop(session.client.stop_check)
    if after.shape!=before.shape or not home_build_control_visible(after):
        return False
    endpoint=measure(before,after)
    final=measure(original,after)
    if (not (endpoint.get('verified') or endpoint.get('verified_zoom')) or
            abs(endpoint.get('scale',0)-1)>=.005 or
            not (final.get('verified') or final.get('verified_zoom')) or
            not .93<=final.get('scale',0)<=1.07):
        return False
    # Retain the first incompatible reference even if later attacks use a new
    # home baseline. No calibration YAML, portraits or routines are changed.
    legacy=root/'camera-legacy-blocked.json'
    if not legacy.exists():
        image=root/'camera-legacy-before.png'
        with image.open('wb') as handle:
            handle.write((root/'camera-before.png').read_bytes());handle.flush();os.fsync(handle.fileno())
        atomic_json(legacy, dict(device=session.config.adb_device,scale=final['scale'],
                                 at=time.time(),reason='verified nearby zoom limit'))
    marker.unlink()
    logger.warning('Home zoom limit verified. Automatic mapping may continue; '
                   'the legacy tap sequence remains blocked until its camera is restored.')
    return True


def recover_attack(session, *, tracker=None):
    """Recover only navigation; no army selection, map inputs or upgrade actions.

    Unknown screens exhaust three observation attempts and fail closed. Starting
    again after manually reaching home can finish a blocked recovery. Stop never
    triggers cleanup taps. Recovery in battle waits up to 240 seconds for two
    matching results frames; there is deliberately no timer-based Return tap.
    """
    if not pending(session.config):
        return False
    checkpoint = AttackCheckpoint(session.config)
    state = checkpoint.load()
    if state is None:
        # Upgrade older releases' persisted camera marker conservatively.
        checkpoint.begin('legacy_camera_recovery')
        checkpoint.update(deployment_possible=True)
        state = checkpoint.load()
    stop = session.client.stop_check
    nav = session.attack_nav
    nav.mode = BotMode.ATTACK
    donation = nav.donation_nav
    from coc_bot.vision.battle_menu import (home_build_control_visible, army_confirmation_button,
                                          battlefield_ready, active_battle_ready, reward_continue_button)
    from coc_bot.attack.planned_farmer import restore_camera
    deadline = time.monotonic()+240
    previous = None
    previous_at = 0.
    returning = state['phase'] in ('returning_home', 'home_confirmed')
    logger.warning('Recovering interrupted attack ({}) — deployment will not be replayed', state['phase'])
    while time.monotonic() < deadline:
        check_stop(stop)
        frame = session.capture.screenshot()
        check_stop(stop)
        if donation is not None and nav.classifier._clan_chat_anchor_visible(frame):
            home = True
            if (session.config.data_dir/'attack-planner/camera-pending.json').exists():
                check_stop(stop)
                donation.close_clan_chat(frame)
                session._sleep(.4)
                home = home_build_control_visible(session.capture.screenshot())
        else:
            # Generic HOME/results labels and green scenery are insufficient.
            home = home_build_control_visible(frame)
        if home:
            check_stop(stop)
            try:
                restore_camera(session)
            except ValueError as exc:
                if (getattr(session.config,'farm_engine','sequence')!='automatic' or
                        'did not converge' not in str(exc) or not accept_home_zoom_limit(session)):
                    raise
            check_stop(stop)
            if donation is None or not donation.ensure_clan_chat():
                raise RecoveryRequired('Attack recovery could not confirm clan chat; automatic actions remain blocked')
            check_stop(stop)
            if not nav.classifier._clan_chat_anchor_visible(session.capture.screenshot()):
                raise RecoveryRequired('Attack recovery did not see the clan-chat anchor; automatic actions remain blocked')
            checkpoint.update('home_confirmed')
            finish_attack(session, tracker=tracker)
            logger.info('Interrupted attack recovered — home, camera and clan chat confirmed')
            return True

        target = nav.battle_completion.detect(frame)
        if target is not None:
            now = time.monotonic()
            stable = (previous is not None and now-previous_at >= 1 and
                      max(abs(target[i]-previous[i]) for i in (0, 1)) < max(frame.shape[:2])*.02)
            previous, previous_at = target, now
            if stable:
                check_stop(stop)
                taps = checkpoint.load().get('return_taps', 0)
                if taps >= 3:
                    break
                checkpoint.update('returning_home', return_taps=taps+1)
                session.input.tap(*target, jitter=0)
                returning = True
                previous = None
            session._sleep(1.2)
            continue
        previous = None
        if battlefield_ready(frame, stop_check=stop) or active_battle_ready(frame, stop_check=stop):
            # Restarting cannot tell whether an intended tap landed. Waiting is
            # safe even when the original executor failed before its first troop.
            checkpoint.update('recovering_battle', deployment_possible=True, entered_opponent=True)
            state['deployment_possible'] = True
            session._sleep(2.)
            continue
        reward = reward_continue_button(frame, stop_check=stop)
        if reward is not None:
            check_stop(stop)
            session.input.tap(*reward, jitter=0)
            session._sleep(1.)
            continue
        if (army_confirmation_button(frame, stop_check=stop) is not None or
                nav.classifier.find_direct_match_button(frame) is not None):
            # Only verified pre-battle controls authorize BACK. Never use the
            # generic BATTLE/MATCHMAKING classification to authorize an input.
            check_stop(stop)
            attempts = checkpoint.load()['attempts']
            if attempts >= 3:
                break
            checkpoint.update(attempts=attempts+1)
            session.input.back()
            session._sleep(1.)
            continue
        if returning:
            # Brief loading/reward transition after a verified results tap.
            returning = False
            session._sleep(2.)
            continue
        attempts = checkpoint.load()['attempts']
        if attempts >= 3:
            break
        checkpoint.update(attempts=attempts+1)
        folder = session.config.data_dir/'debug'
        folder.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(folder/'attack-recovery-unknown.png'), frame)
        session._sleep(2.)
    raise RecoveryRequired('Attack recovery paused: game screen could not be verified. '
                           'Open your home village manually, then press Start. No deployment was replayed.')
