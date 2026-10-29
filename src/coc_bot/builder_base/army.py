"""Repair one missing BH2 Barbarian camp without clearing a player's army."""
import time
import math


def empty_attack(reader,frame):
    return bool(reader.attack_menu(frame) and reader.find(frame,'empty_army_prompt',(.22,.40,.55,.46),threshold=.97))


def editor_close(reader,frame):
    if not (reader.find(frame,'army_choose_title',(.38,.10,.62,.18),threshold=.97)
            and reader.find(frame,'army_locked_reinforcements',(.71,.36,.87,.44),threshold=.97)):
        return None
    return reader.find(frame,'army_choose_close',(.87,.10,.93,.20),threshold=.97)


def editor(reader,frame):
    if editor_close(reader,frame) is None:return None
    ready=bool(reader.find(frame,'army_start_ready',(.085,.215,.12,.27),threshold=.98))
    missing=bool(reader.find(frame,'army_start_missing',(.085,.215,.12,.27),threshold=.98))
    if ready==missing:return None
    # This reader intentionally covers the inspected two-camp early village.
    # Later camps, heroes, reinforcements and other troops need another executor.
    for index in range(2,6):
        x=(274+index*152)/1853
        if not reader.find(frame,'army_locked_camp',(x-.004,.28,x+.077,.47),threshold=.98):return None
    groups=0;empty=[]
    for index in range(2):
        shift=index*152/1853
        portrait=reader.find(frame,'army_chosen_barbarian',(.15+shift,.33,.22+shift,.42),threshold=.97)
        count=reader.find(frame,'army_camp_three',(.19+shift,.285,.22+shift,.33),threshold=.97)
        if portrait and count:groups+=1
        elif index==1 and reader.find(frame,'army_empty_camp',(.22,.28,.31,.47),threshold=.98):empty.append(index)
        else:return None
    if (ready and (groups!=2 or empty)) or (missing and (groups!=1 or empty!=[1])):return None
    return {'family':'raged_barbarian','groups':groups,'units':groups*3,'missing':empty,'ready':ready}


def permitted(r):
    proof=r.record.get('resource_demand',{})
    at=proof.get('inventory_at')
    if type(at) not in (int,float) or not math.isfinite(at):return False
    age=time.time()-at
    return (getattr(r.config,'builder_base_progression_enabled',False) is True
            and bool(r.config.account_tag) and proof.get('account')==r.config.account_tag and proof.get('hall')==2
            and proof.get('hall_verified') is True and 0<=age<=180
            and proof.get('attack') is True)


def close(r):
    first=editor_close(r.reader,r.frame())
    if first is None or editor_close(r.reader,r.frame())!=first:return False
    r.tap(first);r.wait(.5)
    return True


def repair(r):
    if not permitted(r):return False
    first=r.frame();second=r.frame()
    if not empty_attack(r.reader,first) or not empty_attack(r.reader,second):return False
    point=r.reader.find(second,'edit_army_word',(.31,.74,.40,.83),threshold=.97)
    if point is None or r.reader.find(r.frame(),'edit_army_word',(.31,.74,.40,.83),threshold=.97)!=point:return False
    r.record['army_restore']={'account':r.config.account_tag,'phase':'opening','at':time.time(),'adds':0}
    r.phase('editing_army');r.tap(point);r.wait(.5)
    before=editor(r.reader,r.frame())
    if before is None or before!=editor(r.reader,r.frame()):
        if not close(r):raise ValueError('Unknown Builder army editor; no troop input sent')
        r.phase('opening_attack');return False
    if not before['ready']:
        frame=r.frame();point=r.reader.find(frame,'army_picker_barbarian',(.18,.62,.26,.76),threshold=.97)
        fresh=r.frame()
        if (point is None or editor(r.reader,fresh)!=before or
            r.reader.find(fresh,'army_picker_barbarian',(.18,.62,.26,.76),threshold=.97)!=point):
            raise ValueError('Builder Barbarian choice changed; no troop input sent')
        # Persist possible selection before input. Restart only closes this
        # editor; it never blindly repeats a roster tap.
        r.record['army_restore'].update(phase='adding',adds=1)
        r.phase('editing_army');r.tap(point);r.wait(.4)
    after=editor(r.reader,r.frame())
    if after is None or not after['ready'] or after!=editor(r.reader,r.frame()):
        raise ValueError('Builder army selection receipt is uncertain; no battle started')
    r.record['army_restore'].update(phase='confirmed',groups=after['groups'],units=after['units'])
    r.phase('editing_army')
    if not close(r):raise ValueError('Builder army editor did not close')
    r.phase('opening_attack')
    return True
