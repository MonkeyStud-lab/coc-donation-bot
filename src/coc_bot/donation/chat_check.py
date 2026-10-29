"""One bounded, verified chat check, including an off-screen request jump."""
from coc_bot.stop import interrupted_sleep


class ChatCheckUnverified(ValueError):
    """No clear-chat result was established; do not switch or start an attack."""


def peek_requests(capture, navigator, monitor, stop):
    if stop():return None
    frame=capture.screenshot()
    if not navigator.classifier._clan_chat_anchor_visible(frame):
        from coc_bot.vision.battle_menu import home_build_control_visible
        if not home_build_control_visible(frame):
            raise ChatCheckUnverified('Home not verified before clan chat check')
        if stop():return None
        navigator._open_clan_chat(frame)
        if interrupted_sleep(.5,stop):return None
        frame=capture.screenshot()
    if stop():return None
    if not navigator.classifier._clan_chat_anchor_visible(frame):
        raise ChatCheckUnverified('Clan chat could not be verified before checking requests')
    request=monitor.find_donate_request(frame)
    if request is not None or stop():return request
    # Do not infer "no requests" from an old chat scroll position. The native
    # exclamation can jump to an outstanding request above/below the viewport.
    action=navigator.seek_donation_requests_step(frame,lambda image:monitor.find_donate_request(image) is not None)
    if stop():return None
    if action in ('jump','donate_visible'):
        frame=capture.screenshot()
        if stop():return None
        if not navigator.classifier._clan_chat_anchor_visible(frame):
            raise ChatCheckUnverified('Clan chat changed after the request jump')
        request=monitor.find_donate_request(frame)
    return request
