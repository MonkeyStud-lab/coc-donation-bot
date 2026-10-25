"""Offline screen-label evidence for experiments; never authorizes game actions.

This deliberately supports only English anchors. Missing or contradictory
evidence returns None. Explicit conflicts set ``uncertain=True`` and should be
reported as unknown, not replaced with the visual guess. No training
labels, filenames, or expected predictions are inputs to recognition.
"""
from __future__ import annotations

import csv
import io
import re
import shutil
import subprocess

import cv2


def compact(text: str) -> str:
    return re.sub(r"[^a-z]", "", text.lower())


def parse_tsv(raw: str, width: int, height: int) -> list[dict]:
    # Tesseract's TSV is not CSV-quoted: a recognized quote is literal text.
    tokens = []
    for row in csv.DictReader(io.StringIO(raw), delimiter="\t", quoting=csv.QUOTE_NONE):
        if not row.get("text", "").strip():
            continue
        try:
            confidence = float(row["conf"])
            if confidence < 40:
                continue
            tokens.append({"text": row["text"], "confidence": confidence,
                           "x": (int(row["left"]) + int(row["width"])/2)/width,
                           "y": (int(row["top"]) + int(row["height"])/2)/height})
        except (ValueError, KeyError, TypeError):
            continue
    return tokens


def ocr(image, psm=11, timeout=3.0) -> list[dict]:
    if image is None or image.size == 0 or shutil.which("tesseract") is None:
        return []
    ok, png = cv2.imencode(".png", image)
    if not ok:
        return []
    try:
        process = subprocess.run(["tesseract", "stdin", "stdout", "--psm", str(psm),
                                  "-l", "eng", "tsv"], input=png.tobytes(),
                                 capture_output=True, timeout=timeout, check=False)
        if process.returncode:
            return []
    except (OSError, subprocess.TimeoutExpired):
        return []
    return parse_tsv(process.stdout.decode("utf-8", errors="replace"), image.shape[1], image.shape[0])


def decide(tokens: list[dict], footer_labels: list[str], loading_label: str) -> tuple[str, str] | None:
    """Require independent layout/text anchors; conflicting CTA reads abstain."""
    def words(x0, y0, x1, y1):
        return [compact(t["text"]) for t in tokens
                if x0 <= t["x"] <= x1 and y0 <= t["y"] <= y1 and t["confidence"] >= 60]
    left = "".join(words(.05, .02, .45, .35))
    right = words(.50, .02, .95, .35)
    if "myarmy" in left and "cookbook" in right:
        # Sword icons can be recognized as stray letters beside the word.
        # Keep whole words; never interpret End Battle as the Battle CTA.
        buttons = {word.lower() for label in footer_labels
                   for word in re.findall(r"[A-Za-z]+", label)
                   if "endbattle" not in compact(label)}
        attack = "attack" in buttons
        battle = "battle" in buttons
        if attack != battle:
            return ("army_confirmation", "army headers + Attack CTA") if attack else ("army_management", "army headers + Battle CTA")
        return None
    logo = words(0, 0, .40, .35)
    if "clash" in logo and compact(loading_label) == "loading":
        return "loading", "Clash logo text + centered Loading label"
    middle = "".join(words(.25, .30, .80, .70))
    if all(word in middle for word in ("connectionlost", "server", "internetconnection")):
        return "popup", "Connection lost dialog and explanatory text"
    return None


def recognize(frame) -> dict:
    """Read fixed screen regions and detected button rectangles, offline only."""
    h, w = frame.shape[:2]
    image = cv2.resize(frame, (1600, max(1, round(h*1600/w))), interpolation=cv2.INTER_CUBIC)
    h, w = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    white = 255-cv2.inRange(hsv, (0, 0, 160), (180, 80, 255))
    tokens = ocr(white)
    footer_labels = []
    header = "".join(compact(t["text"]) for t in tokens if t["y"] < .35)
    if "myarmy" in header and "cookbook" in header:
        # Gray text helps when thresholding breaks a thin header character.
        header_crop = cv2.cvtColor(image[:int(h*.35)], cv2.COLOR_BGR2GRAY)
        extra = ocr(header_crop)
        for token in extra:
            token["y"] *= header_crop.shape[0]/h
        # Keep reading order within each variant; do not interleave words.
        tokens += extra
        x0, y0 = int(w*.55), int(h*.70)
        crop = image[y0:int(h*.98), x0:int(w*.98)]
        # Both green Attack and grey Battle CTAs need recognition.
        color = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        mask = cv2.bitwise_or(cv2.inRange(color, (30, 70, 100), (90, 255, 255)),
                             cv2.inRange(color, (0, 0, 130), (180, 55, 255)))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (9, 5)))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes = []
        for contour in contours:
            x, y, bw, bh = cv2.boundingRect(contour)
            if .08*w <= bw <= .30*w and .025*h <= bh <= .12*h and 1.7 <= bw/bh <= 8:
                boxes.append((x+x0, y+y0, bw, bh))
        for x, y, bw, bh in sorted(boxes, key=lambda b:b[1], reverse=True)[:6]:
            patch = white[y+int(bh*.08):y+int(bh*.92), x+int(bw*.10):x+int(bw*.95)]
            patch = cv2.resize(patch, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
            footer_labels.append(" ".join(t["text"] for t in ocr(patch, psm=7)))
    loading_label = ""
    # A possible Loading label justifies a second pass for the game's logo.
    if any("oad" in compact(t["text"]) and .43 < t["x"] < .57 and .78 < t["y"] < .9 for t in tokens):
        logo = cv2.cvtColor(image[:int(h*.35), :int(w*.4)], cv2.COLOR_BGR2GRAY)
        extra = ocr(logo)
        for token in extra:
            token["x"] *= logo.shape[1]/w
            token["y"] *= logo.shape[0]/h
        tokens += extra
        crop = white[int(h*.79):int(h*.87), int(w*.43):int(w*.57)]
        loading_label = " ".join(t["text"] for t in ocr(crop, psm=7))
    decision = decide(tokens, footer_labels, loading_label)
    # Fixed menu chrome is independent of offer artwork and the classifier's
    # color features. No close coordinate is exposed by this offline helper.
    from coc_bot.vision.auxiliary import AuxiliaryPageDetector
    # Limit to menu anchors: avoid the production upgrade OCR fallback here.
    small = cv2.cvtColor(cv2.resize(frame, (960, 540), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    pages = AuxiliaryPageDetector.current_pages(small) if 1.6 <= frame.shape[1]/frame.shape[0] <= 1.95 else set()
    shop, settings = 'shop' in pages, 'settings' in pages
    anchored = 'shop' if shop else ('settings' if settings else None)
    conflict = bool((shop and settings) or (anchored and decision and decision[0] != anchored))
    if conflict:
        decision = None
    elif anchored:
        decision = anchored, 'multiple fixed menu anchors'
    return {"screen": decision[0] if decision else None,
            "evidence": decision[1] if decision else None,
            "uncertain": conflict,
            "tokens": tokens, "footer_labels": footer_labels, "loading_label": loading_label}
