"""Home confirmation for accounts which cannot or should not open clan chat."""
import time
import numpy as np
from coc_bot.stop import interrupted_sleep
from coc_bot.vision.battle_menu import home_build_control_visible
from coc_bot.auxiliary_recovery import AuxiliaryRecovery
from coc_bot.vision.battle_menu import _white_label


def recover_home_overlay(nav, frame):
    """Only non-spending reload and Welcome Back controls qualify."""
    if not isinstance(frame,np.ndarray):return False
    reload = nav.classifier.find_reload_game_button(frame)
    if isinstance(reload, tuple) and len(reload)==2:
        return nav._dismiss_popup(frame) is not False
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
