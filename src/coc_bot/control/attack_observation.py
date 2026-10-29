"""Private, review-only army/map reports. Never edit calibration or execute taps."""
import hashlib
import json
from pathlib import Path
import re
import time
import uuid

import cv2

from coc_bot.attack.army import ArmyCard, read_army, agree_cards, correct_cards, check_stop
from coc_bot.attack.mapping import observe_boundary, draw_observation
from coc_bot.vision.battle_menu import army_confirmation_button, battlefield_ready


def reports_root(data_dir):
    return Path(data_dir)/'debug'/'attack-observations'


def report_folder(data_dir, ident):
    if not isinstance(ident,str) or not re.fullmatch('[a-f0-9]{32}',ident):
        raise ValueError('Unknown attack observation')
    folder=reports_root(data_dir)/ident
    if not (folder/'report.json').is_file():
        raise ValueError('Unknown attack observation')
    return folder


def revision(report):
    return hashlib.sha256(json.dumps({k:v for k,v in report.items() if k!='revision'},sort_keys=True).encode()).hexdigest()


def write_report(folder, report):
    report['revision']=revision(report)
    temporary=folder/(uuid.uuid4().hex+'.tmp')
    try:
        temporary.write_text(json.dumps(report,indent=2),encoding='utf-8')
        temporary.replace(folder/'report.json')
    finally:
        temporary.unlink(missing_ok=True)


def read_report(data_dir, ident):
    report=json.loads((report_folder(data_dir,ident)/'report.json').read_text(encoding='utf-8'))
    return report


def review_army(data_dir, ident, expected, corrections):
    folder=report_folder(data_dir,ident)
    report=read_report(data_dir,ident)
    if expected != report['revision']:
        raise ValueError('Observation review changed; reload it before saving')
    cards=[ArmyCard(**card) for card in report['cards']]
    report['cards']=[card.to_dict() for card in correct_cards(cards,corrections)]
    report.pop('plan',None)
    # Human confirmation cannot promote a partial map or old image to readiness.
    report['ready_for_execution']=False
    write_report(folder,report)
    return report


def observation_asset(data_dir, ident, asset):
    if asset not in ('overlay.png','frame.png','mosaic.png','map-reference.png') and not re.fullmatch(r'card-\d{1,2}\.png',asset):
        raise ValueError('Unknown observation image')
    path=report_folder(data_dir,ident)/asset
    if not path.is_file():
        raise ValueError('Unknown observation image')
    return path


def page_for(frame, stop_check=None):
    check_stop(stop_check)
    if army_confirmation_button(frame,stop_check=stop_check) is not None:
        return 'army_confirmation'
    if battlefield_ready(frame,stop_check=stop_check):
        return 'battle'
    raise ValueError('Open the My Army confirmation screen or a real opponent before inspecting the army')


def load_recent_references(data_dir, catalog, device, *, max_age=900):
    root=reports_root(data_dir)
    if not root.exists():
        return
    candidates=[]
    for folder in root.iterdir():
        if not (folder/'report.json').is_file():
            continue
        try:
            report=json.loads((folder/'report.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):
            continue
        if (report.get('page')!='army_confirmation' or report.get('device')!=device or
                not 0<=time.time()-report.get('captured_at',0)<=max_age):
            continue
        candidates.append((report['captured_at'],folder,report))
    for _,folder,report in sorted(candidates,reverse=True):
        frame=cv2.imread(str(folder/'frame.png'))
        if frame is not None:
            catalog.add_references(frame,[ArmyCard(**card) for card in report['cards']])
        return


def inspect_attack(session, *, surveyed_frames=None):
    """Caller holds the diagnostic lease. Two captures precede expensive OCR."""
    stop=session.client.stop_check
    if surveyed_frames is None:
        first=session.capture.screenshot()
        try: page=page_for(first,stop)
        except ValueError:
            session._sleep(.2);first=session.capture.screenshot();page=page_for(first,stop)
        session._sleep(.35)
        second=session.capture.screenshot()
        captured=time.time()
        same_page=page_for(second,stop)==page
    else:
        # The survey already positively gated the battle and measured these two
        # frames. Reuse them for a review, never as execution authorization.
        first,second,captured=surveyed_frames;page='battle';same_page=True
    if first.shape != second.shape or not same_page:
        raise ValueError('The game screen changed during observation; try again once it settles')
    from coc_bot.control.attack_planner import learned_catalog
    catalog=learned_catalog(session.config)
    cards=agree_cards(read_army(first,page,catalog,stop_check=stop),
                      read_army(second,page,catalog,stop_check=stop))
    check_stop(stop)
    mapping=observe_boundary(second,first,battle_confirmed=True,stop_check=stop) if page=='battle' else None
    if mapping:
        mapping.captured_at=captured
    ident=uuid.uuid4().hex
    folder=reports_root(session.config.data_dir)/ident
    folder.mkdir(parents=True)
    cv2.imwrite(str(folder/'frame.png'),second)
    cv2.imwrite(str(folder/'overlay.png'),draw_observation(second,mapping,cards))
    for card in cards:
        x,y,w,h=card.box
        cv2.imwrite(str(folder/(card.slot+'.png')),second[y:y+h,x:x+w])
    report={'attack_observation':True,'observation_id':ident,'captured_at':captured,
            'device':session.config.adb_device,'page':page,'coverage':'visible_cards_only',
            'cards':[card.to_dict() for card in cards],
            'map':mapping.to_dict() if mapping else None,'ready_for_execution':False,
            'message':'Review only. Hidden cards, hero identity and availability may need correction.'}
    check_stop(stop)
    write_report(folder,report)
    return report
