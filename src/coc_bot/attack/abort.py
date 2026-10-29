"""Leave an unstarted opponent using verified combat controls, never a timer."""
from coc_bot.attack.army import check_stop
from coc_bot.attack.recovery import AttackCheckpoint, RecoveryRequired
from coc_bot.vision.battle_menu import battlefield_ready, home_build_control_visible, _white_label


def end_button(frame, stop=None):
    if not battlefield_ready(frame, stop_check=stop):
        return None
    if _white_label(frame, (.015, .715, .13, .775), stop) not in ('endbattle','endbattie'):
        return None
    return round(frame.shape[1]*.075), round(frame.shape[0]*.745)


def leave_unstarted_opponent(session):
    checkpoint = AttackCheckpoint(session.config)
    state = checkpoint.load()
    if not state or state.get('deployment_possible'):
        raise RecoveryRequired('Cannot abandon an opponent after a possible deployment')
    checkpoint.update('aborting_unstarted')
    for _ in range(8):
        check_stop(session.client.stop_check)
        frame = session.capture.screenshot()
        if home_build_control_visible(frame):
            return True
        if session.attack_nav.battle_completion.detect(frame) is not None:
            return session.attack_nav.return_home_from_attack()
        point = end_button(frame, session.client.stop_check)
        if point is not None and checkpoint.load().get('abort_end_taps', 0) < 2:
            fresh = session.capture.screenshot()
            if end_button(fresh, session.client.stop_check) == point:
                check_stop(session.client.stop_check)
                checkpoint.update(abort_end_taps=checkpoint.load().get('abort_end_taps', 0)+1)
                session.input.tap(*point, jitter=0)
                session._sleep(1.)
        session._sleep(.5)
    raise RecoveryRequired('Could not verify leaving the unstarted opponent; deployment remains blocked')
