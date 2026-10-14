"""Readable anchors for multiplayer selection, army confirmation and battle."""
import cv2
from coc_bot.vision.ocr import read_short_label


def _white_label(frame, bounds, stop_check=None):
    h, w = frame.shape[:2]
    left, top, right, bottom = bounds
    crop = frame[int(h*top):int(h*bottom), int(w*left):int(w*right)]
    if not crop.size:
        return ""
    white = cv2.inRange(cv2.cvtColor(crop, cv2.COLOR_BGR2HSV),
                        (0, 0, 160), (180, 70, 255))
    return read_short_label(white, stop_check=stop_check) or ""


def army_confirmation_button(frame, *, stop_check=None):
    """Authorize Attack only with the army-page headers and green Attack CTA."""
    h, w = frame.shape[:2]
    button = frame[int(h*.85):int(h*.94), int(w*.78):int(w*.98)]
    if not button.size:
        return None
    green = cv2.inRange(cv2.cvtColor(button, cv2.COLOR_BGR2HSV),
                        (30, 70, 100), (90, 255, 255))
    if float(green.mean())/255 < .25:
        return None
    if "myarmy" not in _white_label(frame, (.13,.075,.29,.13), stop_check):
        return None
    if "cookbook" not in _white_label(frame, (.71,.075,.87,.13), stop_check):
        return None
    if "attack" not in _white_label(frame, (.84,.86,.96,.92), stop_check):
        return None
    return int(w*.884), int(h*.890)


def battlefield_ready(frame, *, stop_check=None):
    """Require readable scout controls, rather than scenery/card colors.

    This gate is specifically for BEFORE deployment: the opponent must show
    End Battle/Surrender and either Next or the battle countdown label.
    Unknown/OCR failures never authorize taps.
    """
    end = _white_label(frame, (.015,.715,.13,.775), stop_check)
    # The game's heavy font commonly reads the final lowercase l as i.
    if not any(word in end for word in ("endbattle", "endbattie", "surrender")):
        return False
    next_label = _white_label(frame, (.89,.66,.985,.715), stop_check)
    if "next" in next_label:
        return True
    timer = _white_label(frame, (.43,.01,.57,.05), stop_check)
    return "battlestartsin" in timer or "battleendsin" in timer


def reward_continue_button(frame, *, stop_check=None):
    """Recognize resource reveals by their backdrop, title and Continue button."""
    h, w = frame.shape[:2]
    # The full-screen reward hall is warm brown on both sides. A resource
    # heading over the home village or a shop card is not a reward reveal.
    for left, right in ((.02, .22), (.78, .98)):
        side = frame[int(h*.20):int(h*.80), int(w*left):int(w*right)]
        if not side.size:
            return None
        warm = cv2.inRange(cv2.cvtColor(side, cv2.COLOR_BGR2HSV),
                           (5, 65, 25), (35, 255, 255))
        if float(warm.mean())/255 < .55:
            return None
    crop = frame[int(h*.86):int(h*.95), int(w*.43):int(w*.59)]
    if not crop.size:
        return None
    green = cv2.inRange(cv2.cvtColor(crop, cv2.COLOR_BGR2HSV),
                        (30, 70, 100), (90, 255, 255))
    if float(green.mean())/255 < .25:
        return None
    title = _white_label(frame, (.40,.27,.62,.32), stop_check)
    resources = {"capitalgold", "gold", "elixir", "darkelixir", "raidmedals",
                 "gems", "buildergold", "builderelixir"}
    # Bold lettering can turn Dark Elixir into 'ddrkelixir'. Allow one
    # substituted letter in long titles, still requiring backdrop + Continue.
    readable = title in resources or any(
        len(title) == len(name) and len(name) >= 5
        and sum(a != b for a, b in zip(title, name)) <= 1
        for name in resources
    )
    if not readable:
        return None
    if "continue" not in _white_label(frame, (.455,.875,.565,.925), stop_check):
        return None
    return int(w*.508), int(h*.902)


def home_build_control_visible(frame):
    """The village Build control is absent from defense/live replay screens."""
    h,w=frame.shape[:2]
    button=frame[int(h*.80):int(h*.99),int(w*.88):int(w*.99)]
    if not button.size:
        return False
    hsv=cv2.cvtColor(button,cv2.COLOR_BGR2HSV)
    gold=cv2.inRange(hsv,(5,85,90),(35,255,255))
    if float(gold.mean())/255 < .25:
        return False
    label=frame[int(h*.93):int(h*.985),int(w*.88):int(w*.99)]
    white=cv2.inRange(cv2.cvtColor(label,cv2.COLOR_BGR2HSV),(0,0,160),(180,60,255))
    return 'build' in (read_short_label(white) or '')


def direct_match_button(frame, *, stop_check=None):
    """Return the verified left Find a Match CTA, never the ranked action.

    Both the Multiplayer tab and the CTA text must agree. Color only limits OCR
    work; it never authorizes matchmaking on its own. Coordinates scale with
    the frame and are derived from the visible button, not old calibration.
    """
    h, w = frame.shape[:2]
    x0, y0 = int(w*.035), int(h*.675)
    crop = frame[y0:int(h*.86), x0:int(w*.31)]
    if not crop.size:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (5, 85, 100), (35, 255, 255))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9)))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in sorted(contours, key=cv2.contourArea, reverse=True):
        x, y, width, height = cv2.boundingRect(contour)
        if not (width > w*.16 and height > h*.07 and 2 < width/height < 5):
            continue
        tab = frame[int(h*.045):int(h*.105), int(w*.073):int(w*.205)]
        if "multiplayer" not in (read_short_label(tab, stop_check=stop_check) or ""):
            return None
        label = crop[y+int(height*.12):y+int(height*.55), x:x+width]
        # The gold fill is bright enough to defeat the old white-on-green OCR
        # preprocessing. Isolate low-saturation white lettering first.
        white = cv2.inRange(cv2.cvtColor(label, cv2.COLOR_BGR2HSV), (0, 0, 190), (180, 60, 255))
        text = read_short_label(white, stop_check=stop_check) or ""
        if "findamatch" in text or "findmatch" in text:
            return x0+x+width//2, y0+y+height//2
    return None
