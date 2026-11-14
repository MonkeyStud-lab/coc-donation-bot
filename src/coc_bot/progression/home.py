"""Home confirmation for accounts which cannot or should not open clan chat."""
import time
import numpy as np
from loguru import logger
from coc_bot.stop import interrupted_sleep
from coc_bot.vision.battle_menu import home_build_control_visible
from coc_bot.auxiliary_recovery import AuxiliaryRecovery
from coc_bot.vision.battle_menu import _white_label


def recover_home_bonus(nav,frame):
    from coc_bot.vision.notices import home_star_bonus_button
    point=home_star_bonus_button(frame)
    if point is None:
        nav.__dict__.pop('_home_bonus_taps',None)
        return False
    if nav.__dict__.get('_home_bonus_taps',0)>=2 or nav._stopping():return False
    if home_star_bonus_button(nav.capture.screenshot())!=point or nav._stopping():return False
    nav._home_bonus_taps=nav.__dict__.get('_home_bonus_taps',0)+1
    logger.info('Home Star Bonus received — acknowledging delivered loot')
    nav.input.tap(*point,jitter=0)
    return True


def recover_home_announcement(nav,frame):
    from coc_bot.vision.notices import (
        hammer_jam_close_button, gold_pass_offer_close_button, mass_mommas_close_button,
        town_hall_19_close_button,
    )
    def close(image):
        return (hammer_jam_close_button(image) or gold_pass_offer_close_button(image)
                or mass_mommas_close_button(image) or town_hall_19_close_button(image))
    point=close(frame)
    if point is None:
        nav.__dict__.pop('_hammer_jam_taps',None)
        return False
    if nav._stopping() or nav.__dict__.get('_hammer_jam_taps',0)>=2:return False
    if close(nav.capture.screenshot())!=point or nav._stopping():return False
    nav._hammer_jam_taps=nav.__dict__.get('_hammer_jam_taps',0)+1
    logger.info('Verified announcement — closing before village verification')
    nav.input.tap(*point,jitter=0)
    return True


def recover_free_chest(nav,frame):
    from coc_bot.vision.notices import free_chest_tap_point
    point=free_chest_tap_point(frame,nav._stopping)
    if point is None or nav._stopping() or nav.__dict__.get('_free_chest_taps',0)>=60:return False
    if free_chest_tap_point(nav.capture.screenshot(),nav._stopping)!=point or nav._stopping():return False
    nav._free_chest_taps=nav.__dict__.get('_free_chest_taps',0)+1
    logger.info('Free reward chest — following verified Tap prompt')
    nav.input.tap(*point,jitter=0)
    return True


def recover_reward_summary(nav,frame):
    from coc_bot.vision.battle_menu import reward_continue_button
    from coc_bot.vision.notices import free_reward_skip_button,free_reward_skip_confirm_button,free_chest_skip_button
    def button(image):
        return (free_reward_skip_confirm_button(image) or free_reward_skip_button(image)
                or free_chest_skip_button(image,nav._stopping)
                or reward_continue_button(image,stop_check=nav._stopping))
    point=button(frame)
    if point is None or nav._stopping() or nav.__dict__.get('_resource_reward_taps',0)>=60:return False
    if button(nav.capture.screenshot())!=point or nav._stopping():return False
    nav._resource_reward_taps=nav.__dict__.get('_resource_reward_taps',0)+1
    logger.info('Delivered reward summary — advancing before village verification')
    nav.input.tap(*point,jitter=0)
    return True


def recover_home_overlay(nav, frame):
    """Recover independently recognized, non-spending notices and summaries."""
    if not isinstance(frame,np.ndarray):return False
    from coc_bot.vision.connection_dialog import recover_connection_error
    if recover_connection_error(nav,frame):return True
    reload = nav.classifier.find_reload_game_button(frame)
    if isinstance(reload, tuple) and len(reload)==2:
        return nav._dismiss_popup(frame) is not False
    if recover_home_announcement(nav,frame):return True
    if recover_reward_summary(nav,frame):return True
    if recover_free_chest(nav,frame):return True
    if recover_home_bonus(nav,frame):return True
    # This same mandatory free calendar can appear while loading a saved
    # account. Dismiss it before identity verification, without treating the
    # source account's tag/settings as proof of the destination's identity.
    from coc_bot.builder_base.vision import BuilderReader
    calendar=nav.__dict__.get('_calendar_reader')
    if calendar is None:
        calendar=BuilderReader(nav._stopping);nav._calendar_reader=calendar
    close=calendar.daily_reward_close(frame)
    if close:
        claim=calendar.daily_reward_claim(frame);point=claim or close
        key='claim' if claim else 'close'
        counts=nav.__dict__.setdefault('_calendar_taps',{})
        if nav._stopping() or counts.get(key,0)>=2:return False
        fresh=nav.capture.screenshot()
        if (calendar.daily_reward_close(fresh)!=close or calendar.daily_reward_claim(fresh)!=claim
            or nav._stopping()):return False
        counts[key]=counts.get(key,0)+1
        logger.info('Free daily calendar — {}', 'claiming available reward' if claim else 'closing claimed calendar')
        nav.input.tap(*point,jitter=0)
        return True
    nav.__dict__.pop('_calendar_taps',None)
    from coc_bot.vision.notices import event_ended_button,story_dialogue,welcome_back_button,battle_menu_tip_button,defense_results_return_button
    result=defense_results_return_button(frame)
    if result:
        if (nav._stopping() or nav.__dict__.get('_defense_results_taps',0)>=2
            or defense_results_return_button(nav.capture.screenshot())!=result or nav._stopping()):return False
        nav._defense_results_taps=nav.__dict__.get('_defense_results_taps',0)+1
        logger.info('Completed defense summary — returning to village before account verification')
        nav.input.tap(*result,jitter=0)
        return True
    nav.__dict__.pop('_defense_results_taps',None)
    welcome=welcome_back_button(frame)
    if welcome:
        if welcome_back_button(nav.capture.screenshot())==welcome and not nav._stopping():
            nav.input.tap(*welcome,jitter=0)
            return True
        return False
    event=event_ended_button(frame)
    if event:
        fresh=nav.capture.screenshot()
        second=event_ended_button(fresh)
        if second==event and not nav._stopping():
            nav.input.tap(*second,jitter=0)
            return True
        return False
    tip=battle_menu_tip_button(frame)
    if tip:
        if (battle_menu_tip_button(nav.capture.screenshot())!=tip or nav._stopping()
            or nav.__dict__.get('_battle_tip_taps',0)>=2):return False
        nav._battle_tip_taps=nav.__dict__.get('_battle_tip_taps',0)+1
        nav.input.tap(*tip,jitter=0)
        return True
    story=story_dialogue(frame)
    if story:
        second=story_dialogue(nav.capture.screenshot())
        if second!=story or nav._stopping():return False
        counts=nav.__dict__.setdefault('_story_counts',{})
        key=story['signature']
        if counts.get(key,0)>=2:return False
        counts[key]=counts.get(key,0)+1
        nav.input.tap(*story['point'],jitter=0)
        return True
    title=_white_label(frame,(.30,.075,.70,.155),nav._stopping)
    okay=_white_label(frame,(.45,.80,.57,.88),nav._stopping)
    if title=='welcomebackchief' and okay=='okay' and not nav._stopping():
        nav.input.tap(round(frame.shape[1]*.511),round(frame.shape[0]*.835),jitter=0)
        return True
    return False


def ensure_home(nav, timeout=15):
    deadline = time.monotonic() + timeout
    recovery = AuxiliaryRecovery(nav.classifier, nav.input, nav._stopping)
    observations = 0
    while time.monotonic() < deadline and not nav._stopping():
        frame = nav.capture.screenshot()
        if nav._stopping():
            return False
        if recover_home_overlay(nav,frame):
            observations = 0
        elif nav.classifier._clan_chat_anchor_visible(frame):
            nav.close_clan_chat(frame)
            observations = 0
        elif nav.classifier.auxiliary_page(frame) is not None:
            if not recovery.close(frame):
                return False
            observations = 0
        elif home_build_control_visible(frame) and not nav.classifier.looks_like_blocking_popup(frame):
            observations += 1
            if observations >= 2:
                return True
        else:
            observations = 0
        if interrupted_sleep(.4, nav._stopping):
            return False
    return False
