import unittest
from unittest.mock import Mock
from coc_bot.donation.quality import COMPOSITIONS,HOUSING,composition

class QualityTests(unittest.TestCase):
    def test_every_castle_size_exactly_fits_without_excluded_troops(self):
        self.assertEqual(set(COMPOSITIONS),set(range(10,56,5)))
        for capacity,units in COMPOSITIONS.items():
            self.assertEqual(sum(HOUSING[u] for u in units),capacity)
            self.assertEqual(dict(composition(capacity,HOUSING)),dict(__import__('collections').Counter(units)))

    def test_every_partial_capacity_is_safe_and_has_no_junk_fallback(self):
        for space in range(56):
            for available in (HOUSING,{'balloon','wizard','minion'},{'barbarian','archer','wall_breaker','goblin'},set()):
                plan=composition(space,available)
                self.assertLessEqual(sum(HOUSING[u]*n for u,n in plan.items()),space)
                self.assertTrue(set(plan)<=set(HOUSING)&set(available))
        self.assertEqual(composition(1,HOUSING),{'archer':1})
        self.assertEqual(composition(3,HOUSING),{'minion':1,'archer':1})
        self.assertFalse(composition(55,{'archer'}))

    def test_fast_capacity_needs_agreement_and_never_loads_neural_ocr(self):
        from coc_bot.donation.capacity_parser import RequestCapacityParser
        import numpy as np
        reader=RequestCapacityParser.__new__(RequestCapacityParser)
        reader._has_tesseract=True;reader.ocr=Mock()
        reader._row_variants=Mock(return_value=[1,2,3])
        reader._tesseract_fraction=Mock(side_effect=[(0,55),(0,55),None])
        self.assertEqual(reader._read_row_fraction(np.ones((3,3)),kind='troop',fast=True),(0,55))
        reader.ocr.read_fraction.assert_not_called()
        reader._tesseract_fraction.side_effect=[(0,55),(0,50),None]
        self.assertIsNone(reader._read_row_fraction(np.ones((3,3)),kind='troop',fast=True))

    def test_shifted_troop_only_grid_does_not_treat_second_troop_row_as_spells(self):
        from pathlib import Path
        import cv2
        from coc_bot.donation.layout import DonationLayout
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/requests/troop-only-open.png'))
        layout=DonationLayout.detect(frame)
        self.assertIsNotNone(layout)
        self.assertIsNone(layout.bar('donation_spell_bar'))
        self.assertLess(abs(layout.troops[1]-473),3)
        self.assertLess(abs(layout.elixir_center[1]-352),5)

    def test_open_request_requires_quality_and_native_caption_confirms_specific(self):
        from pathlib import Path
        from types import SimpleNamespace
        import cv2
        from coc_bot.donation.request_parser import RequestParser,RequestKind
        from coc_bot.vision.matcher import MatchResult
        reader=RequestParser(SimpleNamespace())
        root=Path(__file__).parent/'fixtures/requests'
        button=MatchResult(466,830,1.,175,65)
        self.assertEqual(reader.classify(cv2.imread(str(root/'troop-only-open.png')),button),RequestKind.OPEN)
        self.assertEqual(reader.classify(cv2.imread(str(root/'specific-request.png')),button),RequestKind.SPECIFIC)
