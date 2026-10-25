from pathlib import Path
import sys
from unittest import TestCase
from unittest.mock import patch
import subprocess

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from screen_text_evidence import decide, ocr, parse_tsv, recognize


def token(text, x, y, confidence=95):
    return {"text": text, "x": x, "y": y, "confidence": confidence}


class ScreenTextEvidenceTests(TestCase):
    def setUp(self):
        self.army = [token("My", .18, .1), token("Army", .23, .1), token("Cookbook", .78, .1)]

    def test_attack_requires_both_headers_and_unambiguous_cta(self):
        self.assertEqual(decide(self.army, ["Attack!"], "")[0], "army_confirmation")
        self.assertEqual(decide(self.army, ["VY Attack!"], "")[0], "army_confirmation")
        self.assertEqual(decide(self.army, ["Battle"], "")[0], "army_management")
        for headers, ctas in ((self.army[:2], ["Attack!"]), (self.army, ["End Battle"]),
                              ([], ["Attack!"]), (self.army, ["Attack!", "Battle"]),
                              (self.army, ["V End Battle"])):
            self.assertIsNone(decide(headers, ctas, ""))

    def test_low_confidence_or_wrong_header_position_does_not_override(self):
        self.army[2]["confidence"] = 20
        self.assertIsNone(decide(self.army, ["Attack!"], ""))
        self.army[2].update(confidence=95, y=.9)
        self.assertIsNone(decide(self.army, ["Attack!"], ""))

    def test_loading_requires_logo_and_loading_text(self):
        logo = [token("CLASH", .16, .16)]
        self.assertEqual(decide(logo, [], "Loading")[0], "loading")
        self.assertIsNone(decide([], [], "Loading"))
        self.assertIsNone(decide(logo, [], "Loading troops"))
        self.assertIsNone(decide([token("Clash", .16, .7)], [], "Loading"))

    def test_connection_dialog_requires_body_evidence_in_center(self):
        words = [token(s, .4, .45) for s in ("Connection", "lost", "server", "internet", "connection")]
        self.assertEqual(decide(words, [], "")[0], "popup")
        self.assertIsNone(decide(words[:2], [], ""))
        for word in words: word["x"] = .1
        self.assertIsNone(decide(words, [], ""))

    def test_tsv_literal_quotes_do_not_swallow_following_rows(self):
        header = "left\ttop\twidth\theight\tconf\ttext\n"
        rows = '1\t2\t3\t4\t90\t"\n10\t20\t30\t40\t95\tAttack!\n'
        parsed = parse_tsv(header + rows, 100, 100)
        self.assertEqual([t["text"] for t in parsed], ['"', "Attack!"])
        self.assertEqual(parsed[1]["x"], .25)

    def test_unavailable_ocr_and_timeout_abstain(self):
        image = np.zeros((10, 10), dtype=np.uint8)
        with patch("screen_text_evidence.shutil.which", return_value=None):
            self.assertEqual(ocr(image), [])

        with patch("screen_text_evidence.shutil.which", return_value="tesseract"), \
                patch("screen_text_evidence.subprocess.run", side_effect=subprocess.TimeoutExpired("tesseract", 3)):
            self.assertEqual(ocr(image), [])

    def test_conflicting_anchor_and_text_evidence_is_explicitly_uncertain(self):
        image = np.zeros((540,960,3),dtype=np.uint8)
        with patch('screen_text_evidence.ocr',return_value=[]), \
                patch('screen_text_evidence.decide',return_value=('army_confirmation','army headers')), \
                patch('coc_bot.vision.auxiliary.AuxiliaryPageDetector.current_pages',return_value={'shop'}):
            decision = recognize(image)
        self.assertIsNone(decision['screen'])
        self.assertTrue(decision['uncertain'])
