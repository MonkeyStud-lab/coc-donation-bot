"""Attack templates and supervised previews, separate from old calibration."""
from dataclasses import asdict
import json
import hashlib
import time

import cv2

from coc_bot.attack.army import ArmyCard, UnitCatalog, check_stop
from coc_bot.attack.plans import AttackPlan, ArmyEntry, MapPoint, mass_edrag_plan
from coc_bot.attack.projection import Projection, validate_geometry
from coc_bot.control.attack_observation import (inspect_attack, report_folder, read_report,
                                               write_report, load_recent_references)


def template_path(config):
    return config.data_dir/'attack-planner'/'routine.json'


def load_template(config, *, require_live=False):
    path=template_path(config)
    if not path.is_file(): raise ValueError('Save an attack plan before selecting the new engine')
    try:
        value=json.loads(path.read_text(encoding='utf-8'))
        plan=AttackPlan.from_dict(value['plan'])
        if value.get('device')!=config.adb_device:
            raise ValueError('Review the army on this device before using its plan')
        if require_live and value.get('live_verified') is not True:
            raise ValueError('Complete a supervised attack with this saved routine before scheduling it')
        return value,plan
    except (KeyError,TypeError,json.JSONDecodeError) as exc:
        raise ValueError('Attack plan is damaged; review and save it again') from exc


def learned_catalog(config, *, unit_ids=None, use_saved_routine=True):
    catalog=UnitCatalog(config.data_dir/'icons')
    load_recent_references(config.data_dir,catalog,config.adb_device)
    if use_saved_routine and unit_ids is None and template_path(config).is_file():
        try:
            _,plan=load_template(config)
            unit_ids={entry.unit_id for entry in plan.army}
        except ValueError:
            pass
    root=config.data_dir/'attack-planner'/'units'
    for path in sorted(root.glob('*.json')) if root.exists() else []:
        try:
            value=json.loads(path.read_text(encoding='utf-8'))
            image=cv2.imread(str(path.with_suffix('.png')))
            if (image is None or value['device']!=config.adb_device or
                    unit_ids is not None and value['unit_id'] not in unit_ids): continue
            h,w=image.shape[:2]
            card=ArmyCard('learned',(0,0,w,h),value['unit_id'],value['kind'],1,confirmed=True)
            catalog.add_references(image,[card])
        except (ValueError,KeyError,TypeError,OSError): continue
    if unit_ids is not None:
        # Renaming a reviewed hero must not leave two names competing for the
        # same portrait. Keep old files for recovery, but use this plan's names.
        catalog.references=[r for r in catalog.references if r[0] in unit_ids]
    return catalog


def survey_opponent(session):
    from coc_bot.attack.survey import survey
    from coc_bot.attack.mapping import draw_observation
    # Persist the prior HOME reference only when available; a camera marker
    # from an earlier planner run is never silently replaced.
    root=session.config.data_dir/'attack-planner'
    if not (root/'camera-pending.json').exists():
        from coc_bot.attack.planned_farmer import remember_camera
        home=session.config.data_dir/'debug'/'attack_pre_tap.png'
        image=cv2.imread(str(home)) if home.is_file() else None
        from coc_bot.vision.battle_menu import home_build_control_visible
        if image is not None and home_build_control_visible(image): remember_camera(session,image)
        else:
            # Mapping an already-open opponent cannot invent a previous zoom.
            raise ValueError('Open home, use Prepare opponent, then map it so your camera can be restored')
    result=survey(session,full_map=True)
    report=inspect_attack(session,surveyed_frames=(result['previous'],result['current'],result['captured_at']))
    folder=report_folder(session.config.data_dir,report['observation_id'])
    cv2.imwrite(str(folder/'map-reference.png'),result['reference'])
    cv2.imwrite(str(folder/'mosaic.png'),result['mosaic'])
    report['survey']={'views':result['views'],'captured_at':result['captured_at'],
                      'mosaic_offset':result['mosaic_offset'],
                      'mosaic_bounds':result['mosaic_bounds'],
                      'reference_size':[result['reference'].shape[1],result['reference'].shape[0]],
                      'segments':result['segments']}
    report['projection']=result['projection'].to_dict() if result['projection'] else None
    report['message']='Review the army and four village corners, then preview the attack.'
    write_report(folder,report)
    return report


def default_plan(report):
    army=tuple(ArmyEntry(c['unit_id'],c['kind'],c['quantity'],True) for c in report['cards']
               if c['confirmed'] and c['quantity'] and c['unit_id'])
    spells={}
    for entry in army:
        # Recall, freeze and every other spell need explicit user-created steps.
        if entry.unit_id=='rage_spell' or entry.unit_id=='rage':
            spells[entry.unit_id]=tuple(MapPoint(.27,.22+i*.56/max(1,entry.quantity-1))
                                        for i in range(entry.quantity))
    return mass_edrag_plan(army,(MapPoint(.055,.22),MapPoint(.055,.78)),spell_targets=spells).to_dict()


def save_preview(config, ident, expected, plan_value, corners, *, save_routine=False):
    report=read_report(config.data_dir,ident)
    if report.get('device')!=config.adb_device:
        raise ValueError('Observation belongs to a different device; inspect this device again')
    if report['revision']!=expected: raise ValueError('Observation changed; reload before saving the plan')
    if report.get('page')!='battle' or not report.get('survey'):
        raise ValueError('Map an opponent before creating an attack preview')
    projection=Projection(tuple(tuple(p) for p in corners),'reviewed',True).validate()
    width,height=report['survey'].get('reference_size',[1000,600])
    if any(not -width<=x<=width*2 or not -height<=y<=height*2 for x,y in corners):
        raise ValueError('Mark corners within the surveyed image')
    plan=AttackPlan.from_dict(plan_value)
    reviewed={c['unit_id']:c for c in report['cards'] if c['confirmed'] and c['unit_id']}
    for entry in plan.army:
        card=reviewed.get(entry.unit_id)
        if sum(c['unit_id']==entry.unit_id for c in report['cards'])!=1:
            raise ValueError('Repeated army identity; review the duplicate cards before planning')
        if not card or card['kind']!=entry.kind or card['quantity']<entry.quantity:
            raise ValueError('Check each used army card before saving the plan')
    validate_geometry(plan,projection)
    report['projection']=projection.to_dict();report['plan']=plan.to_dict()
    report['ready_for_execution']=False
    folder=report_folder(config.data_dir,ident)
    write_report(folder,report)
    if save_routine:
        root=template_path(config).parent;root.mkdir(parents=True,exist_ok=True)
        units=root/'units';units.mkdir(exist_ok=True)
        frame=cv2.imread(str(folder/'frame.png'))
        if frame is None: raise ValueError('Army reference image is missing')
        # Capture-based artwork stays private and survives report cleanup.
        for entry in plan.army:
            card=reviewed[entry.unit_id];x,y,w,h=card['box']
            key=hashlib.sha256((config.adb_device+'\0'+entry.unit_id).encode()).hexdigest()
            cv2.imwrite(str(units/(key+'.png')),frame[y:y+h,x:x+w])
            (units/(key+'.json')).write_text(json.dumps({'device':config.adb_device,
                               'unit_id':entry.unit_id,'kind':entry.kind}),encoding='utf-8')
        path=template_path(config)
        old={}
        if path.is_file():
            try:old=json.loads(path.read_text(encoding='utf-8'))
            except (OSError,ValueError):pass
        value={'version':1,'device':config.adb_device,'saved_at':time.time(),'plan':plan.to_dict(),
               'live_verified':old.get('live_verified') is True and old.get('plan')==plan.to_dict()
                               and old.get('device')==config.adb_device}
        temporary=path.with_suffix('.tmp')
        temporary.write_text(json.dumps(value,indent=2),encoding='utf-8');temporary.replace(path)
    return report


def execute_preview(session, ident, expected):
    from coc_bot.attack.executor import VerifiedExecutor
    from coc_bot.attack.recovery import AttackCheckpoint, finish_attack
    checkpoint=AttackCheckpoint(session.config)
    if checkpoint.load() is not None:
        raise ValueError('Recover the unfinished attack before executing another preview')
    report=read_report(session.config.data_dir,ident)
    if report.get('device')!=session.config.adb_device:
        raise ValueError('Observation belongs to a different device; inspect this device again')
    if report['revision']!=expected or not report.get('plan') or not report.get('projection'):
        raise ValueError('Preview and save the reviewed plan before running it')
    if report.get('executed'):
        raise ValueError('This preview has already been used; inspect a new opponent')
    age=time.time()-report['survey']['captured_at']
    if not 0<=age<=600: raise ValueError('Opponent preview expired; map the current opponent again')
    projection=Projection(**report['projection']);plan=AttackPlan.from_dict(report['plan'])
    folder=report_folder(session.config.data_dir,ident)
    reference=cv2.imread(str(folder/'map-reference.png'))
    if reference is None: raise ValueError('Map reference is missing')
    catalog=learned_catalog(session.config,unit_ids={entry.unit_id for entry in plan.army})
    frame=cv2.imread(str(folder/'frame.png'))
    catalog.add_references(frame,[ArmyCard(**c) for c in report['cards']])
    check_stop(session.client.stop_check)
    # Reserve before sending input. A failed or interrupted attempt is never replayable.
    report['executed']=True;write_report(folder,report)
    checkpoint.begin('opponent')
    checkpoint.update(entered_opponent=True)
    executor=VerifiedExecutor(session,plan,projection,reference,catalog)
    try:
        result=executor.run()
    finally:
        report['execution']=asdict(executor.result);write_report(folder,report)
        if executor.result.first_deploy_at or executor.result.uncertain_tap:
            from coc_bot.runtime.tracker import RuntimeTracker
            tracker=RuntimeTracker(session.config)
            tracker.mark_farm_success(attack_id=checkpoint.load()['id']);tracker.pause_farm_clock()
    # Even a preflight failure can leave the game in an opponent. Finish that
    # match before returning control to donations, unless Stop was requested.
    try:
        check_stop(session.client.stop_check)
        started=result.first_deploy_at or result.first_attempt_at
        timeout=None if started else max(225.,session.config.farm_battle_timeout_seconds)
        session.attack_nav.wait_for_battle_end(timeout=timeout,since=started or report['survey']['captured_at'])
        check_stop(session.client.stop_check)
        home=session.attack_nav.return_home_from_attack()
        report['returned_home']=bool(home)
        if home:
            fresh=session.capture.screenshot()
            if session.classifier._clan_chat_anchor_visible(fresh):
                session.navigator.close_clan_chat(fresh);session._sleep(.3)
            from coc_bot.attack.planned_farmer import restore_camera
            restore_camera(session)
            report['camera_restored']=True
            report['chat_confirmed']=bool(session.navigator.ensure_clan_chat())
            if report['chat_confirmed']:
                check_stop(session.client.stop_check)
                checkpoint.update('home_confirmed')
                finish_attack(session)
            if result.success and report['chat_confirmed']:
                path=template_path(session.config)
                if path.is_file():
                    value=json.loads(path.read_text(encoding='utf-8'))
                    if value.get('plan')==plan.to_dict() and value.get('device')==session.config.adb_device:
                        value['live_verified']=True
                        temporary=path.with_suffix('.tmp')
                        temporary.write_text(json.dumps(value,indent=2),encoding='utf-8');temporary.replace(path)
    finally:
        write_report(folder,report)
    return report


def prepare_opponent(session):
    from coc_bot.attack.planned_farmer import remember_camera, restore_camera
    from coc_bot.attack.recovery import recover_attack
    if recover_attack(session):
        raise ValueError('Interrupted attack recovered; prepare a new opponent when ready')
    if not session.attack_nav.leave_chat_for_home(): raise ValueError('Could not reach home')
    restore_camera(session)
    home=session.capture.screenshot()
    if not session.attack_nav.open_attack_menu(): raise ValueError('Could not open Attack menu')
    if not session.attack_nav.start_unranked_battle() or not session.attack_nav.wait_for_battle():
        raise ValueError('Could not confirm an unranked opponent')
    remember_camera(session,home)
    try:
        return survey_opponent(session)
    except ValueError as exc:
        # A failed map must not hand an active opponent back to donations.
        # Stop remains authoritative throughout the wait and cleanup.
        check_stop(session.client.stop_check)
        state=json.loads((session.config.data_dir/'attack-planner/camera-pending.json').read_text(encoding='utf-8'))
        session.attack_nav.wait_for_battle_end(timeout=max(225.,session.config.farm_battle_timeout_seconds),since=state['at'])
        check_stop(session.client.stop_check)
        if session.attack_nav.return_home_from_attack():
            fresh=session.capture.screenshot()
            if session.classifier._clan_chat_anchor_visible(fresh):
                session.navigator.close_clan_chat(fresh);session._sleep(.3)
            restore_camera(session)
            session.navigator.ensure_clan_chat()
        raise ValueError('Opponent mapping stopped: '+str(exc)) from exc
