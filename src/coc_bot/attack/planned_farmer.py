"""Opt-in semantic farming. The old tap sequence is never replayed as fallback."""
from types import SimpleNamespace
import json
import time
from loguru import logger

import cv2

from coc_bot.adb.client import AdbStopped
from coc_bot.attack.army import check_stop
from coc_bot.attack.camera import compare_camera,compare_zoom
from coc_bot.attack.executor import VerifiedExecutor
from coc_bot.attack.survey import survey
from coc_bot.control.attack_planner import load_template, learned_catalog
from coc_bot.vision.screens import BotMode, ScreenType
from coc_bot.runtime.game_state import GameState


def context(farmer):
    def sleep(seconds):
        if farmer._sleep(seconds): raise AdbStopped('Attack stopped')
    return SimpleNamespace(config=farmer.config,capture=farmer.capture,input=farmer.input,
                           client=farmer.input.client,attack_nav=farmer.attack_nav,_sleep=sleep)


def remember_camera(session, home):
    root=session.config.data_dir/'attack-planner';root.mkdir(parents=True,exist_ok=True)
    path=root/'camera-before.png'
    if (root/'camera-pending.json').exists():
        raise ValueError('Restore the previous camera before changing zoom again')
    cv2.imwrite(str(path),home)
    (root/'camera-pending.json').write_text(json.dumps({'at':time.time(),'device':session.config.adb_device}),encoding='utf-8')


def restore_camera(session):
    """Only a positively identified home can restore a persisted zoom change."""
    root=session.config.data_dir/'attack-planner';pending=root/'camera-pending.json'
    if not pending.exists(): return True
    state=json.loads(pending.read_text(encoding='utf-8'))
    if state.get('device')!=session.config.adb_device:
        raise ValueError('Camera reference belongs to a different device')
    from coc_bot.vision.battle_menu import home_build_control_visible
    from coc_bot.adb.multitouch import Multitouch
    original=cv2.imread(str(root/'camera-before.png'))
    if original is None: raise ValueError('Original camera reference is missing')
    for attempt in range(5):
        check_stop(session.client.stop_check)
        frame=session.capture.screenshot()
        if frame.shape!=original.shape:
            raise ValueError('Display size changed; restore the original resolution before restoring the camera')
        if not home_build_control_visible(frame): raise ValueError('Open home village and close clan chat to restore the camera')
        evidence=compare_camera(original,frame)
        if not evidence['verified']:
            zoom=compare_zoom(original,frame)
            if not zoom.get('verified_zoom'):
                hint=state.get('measured_scale')
                if attempt==0 and type(hint) in (float,int) and .2<hint<.97:
                    # Repeated decorations can defeat matching at extreme zoom.
                    # Use the measured battle zoom for ONE approach gesture;
                    # a subsequent home image must still prove restoration.
                    with Multitouch(session.client,(frame.shape[1],frame.shape[0])) as touch:
                        touch.pinch(start_span=.22,end_span=min(.70,.22/hint))
                    session._sleep(.4)
                    continue
                raise ValueError('Could not match the original camera; restore it manually before using the old sequence')
            evidence=zoom
        scale=evidence['scale']
        # Tiny gestures are below the game's touch slop. A measured 3% scale
        # tolerance prevents endless correction of a sub-gesture difference.
        if abs(scale-1)<.03:
            pending.unlink();return True
        gain=max(.4,min(2.5,1/scale))
        start=.22 if gain>1 else .60
        end=max(.06,min(.70,start*gain))
        with Multitouch(session.client,(frame.shape[1],frame.shape[0])) as touch:
            touch.pinch(start_span=start,end_span=end)
        session._sleep(.4)
    raise ValueError('Camera restoration did not converge; old sequence remains blocked')


def run_planned_attack(farmer, *, automatic=False):
    from coc_bot.attack.farmer import FarmResult
    session=context(farmer)
    plan = None
    if not automatic:
        try: _,plan=load_template(farmer.config,require_live=True)
        except ValueError as exc:return FarmResult(False,str(exc))
    executor=None
    farmer._set_mode(BotMode.HOME);farmer._gs(GameState.HOME,'prepare planned attack')
    if not farmer.attack_nav.leave_chat_for_home(): return FarmResult(False,'could not reach home')
    restore_camera(session)
    home=farmer.capture.screenshot()
    farmer._set_mode(BotMode.ATTACK)
    farmer._gs(GameState.ATTACK_MENU,'open unranked attack')
    if not farmer.attack_nav.open_attack_menu(): return FarmResult(False,'could not open Attack menu')
    farmer._gs(GameState.MATCHMAKING,'start unranked Battle')
    if not farmer.attack_nav.start_unranked_battle() or not farmer.attack_nav.wait_for_battle():
        return FarmResult(False,'could not confirm opponent')
    farmer._gs(GameState.IN_BATTLE,'survey opponent')
    opponent_at=time.time()
    remember_camera(session,home)
    failure=None
    try:
        observed=survey(session)
        if observed['projection'] is None:
            raise ValueError('Four observed map edges were not found; no deployment sent')
        if automatic:
            from coc_bot.attack.automatic import automatic_plan, scan_army
            catalog=learned_catalog(farmer.config,use_saved_routine=False)
            cards=scan_army(session,catalog)
            plan=automatic_plan(cards)
            # The current readings supply only this attack's artwork and counts.
            # Neither a saved routine nor manually confirmed corners are needed.
            catalog.references=[r for r in catalog.references if r[0] in {e.unit_id for e in plan.army}]
            logger.info('Automatic attack: built {} steps from {} army cards',len(plan.steps),len(plan.army))
        else:
            catalog=learned_catalog(farmer.config)
        executor=VerifiedExecutor(session,plan,observed['projection'],observed['reference'],catalog)
        result=executor.run()
    except ValueError as exc:
        failure=str(exc)
        logger.warning('Attack preparation stopped: {}',failure)
        result=executor.result if executor else None
    except AdbStopped:
        return FarmResult(False,'stopped',True)
    try:
        # A failed survey still entered an opponent. Wait for the match to end
        # and restore the camera instead of handing a battle back to donations.
        started=(result.first_deploy_at or result.first_attempt_at) if result else None
        timeout=None if started else max(225.,farmer.config.farm_battle_timeout_seconds)
        farmer.attack_nav.wait_for_battle_end(timeout=timeout,since=started or opponent_at)
        check_stop(session.client.stop_check)
        farmer._gs(GameState.RETURNING_HOME,'finish planned attack')
        returned=farmer.attack_nav.return_home_from_attack()
        if not returned: return FarmResult(False,'home could not be confirmed',True)
        if farmer.donation_nav is not None and farmer.attack_nav.classifier._clan_chat_anchor_visible(farmer.capture.screenshot()):
            farmer.donation_nav.close_clan_chat(farmer.capture.screenshot())
            session._sleep(.3)
        restore_camera(session)
        farmer._set_mode(BotMode.DONATE)
        chat=farmer.donation_nav.ensure_clan_chat() if farmer.donation_nav else True
        farmer._gs(GameState.CLAN_CHAT,'planned attack completed')
        return FarmResult(bool(result and result.success and chat),
                          failure or (result.reason if result else 'attack was not executed'),True)
    except ValueError as exc:
        # No blind Back, old recipe, or whole-plan replay after uncertainty.
        return FarmResult(False,str(exc),True)
    except AdbStopped:
        return FarmResult(False,'stopped',True)
