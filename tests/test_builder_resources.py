import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import cv2

from coc_bot.adb.client import AdbStopped
from coc_bot.builder_base.resources import ResourceReader, ResourceCollector
from coc_bot.builder_base.vision import BuilderReader
from coc_bot.builder_base.upgrades import eligibility
from coc_bot.upgrades.vision import Candidate


class ResourceVisionTests(unittest.TestCase):
    def frame(self,name):
        return cv2.imread(str(Path(__file__).parent/'fixtures/builder_base'/f'resources-{name}.png'))

    def test_collectors_in_both_areas_without_gem_mine_or_hud(self):
        reader=ResourceReader(BuilderReader())
        for name,expected in [('area1',{'gold':1,'elixir':1}),('area2',{'gold':2,'elixir':2}),
                              ('shore',{'gold':0,'elixir':1})]:
            for scale in (1,.75):
                f=cv2.resize(self.frame(name),None,fx=scale,fy=scale)
                hits=reader.bubbles(f)
                self.assertEqual({k:sum(h['resource']==k for h in hits) for k in expected},expected,(name,scale,hits))

    def test_modal_and_battle_do_not_provide_map_targets(self):
        r=ResourceReader(BuilderReader());f=self.frame('cart')
        self.assertTrue(r.cart(f));self.assertIsNotNone(r.cart_collect(f))
        self.assertEqual(r.bubbles(f),[])
        for n in (14,17,18,20,23,28):
            f=cv2.imread(str(Path(__file__).parent/'fixtures/builder_base'/f'controls-{n}.png'))
            self.assertEqual(r.bubbles(f),[],n)
            self.assertIsNone(r.cart_collect(f),n)

    def test_disabled_cart_collect_is_rejected(self):
        r=ResourceReader(BuilderReader());f=self.frame('cart')
        f[840:945,1240:1500]=cv2.cvtColor(cv2.cvtColor(f[840:945,1240:1500],cv2.COLOR_BGR2GRAY),cv2.COLOR_GRAY2BGR)
        self.assertIsNone(r.cart_collect(f))

    def test_village_balance_readings(self):
        r=ResourceReader(BuilderReader())
        balances=r.balances(self.frame('area1'))
        self.assertEqual(balances,{'gold':2539934,'elixir':2171359,'gems':698})

    def test_builder_count_reader_accepts_three_only_in_builder_menu(self):
        reader=BuilderReader()
        with patch.object(reader, 'menu_kind', return_value='buildings'), \
                patch('coc_bot.upgrades.digits.read_digits') as digits:
            for free in range(4):
                digits.return_value=f'{free}/3'
                self.assertEqual(reader.availability(self.frame('area1'),'buildings'),(free,3))
            for invalid in ('4/3','2/1','1/6','0/0'):
                digits.return_value=invalid
                self.assertIsNone(reader.availability(self.frame('area1'),'buildings'))
        with patch.object(reader, 'menu_kind', return_value=None):
            self.assertIsNone(reader.availability(self.frame('area1'),'buildings'))


class ResourceSafetyTests(unittest.TestCase):
    def collector(self):
        r=MagicMock();r.config.dry_run=False;r.reader.stop=None
        r.reader.reward_button.return_value=None
        return ResourceCollector(r)

    def test_practice_and_stop_never_tap(self):
        c=self.collector();c.r.config.dry_run=True
        self.assertEqual(c.run(),{'status':'practice_skipped'})
        c.r.tap.assert_not_called();c.r.frame.assert_not_called()
        c.r.check.side_effect=AdbStopped('stop')
        with self.assertRaises(AdbStopped):c.run()
        c.r.tap.assert_not_called()

    def test_unchanged_unknown_or_decreasing_balance_is_not_success(self):
        c=self.collector()
        for a,b in [(None,100),(100,None),(100,100),(100,99)]:
            self.assertFalse(c.record_gain('elixir',{'elixir':a},{'elixir':b}))
        self.assertEqual(c.report['confirmed'],0)
        self.assertTrue(c.record_gain('elixir',{'elixir':100},{'elixir':140}))
        self.assertEqual(c.report['gains']['elixir'],40)

    def test_moving_or_disappearing_target_is_not_tapped(self):
        c=self.collector();c.reader=MagicMock();c.reader.cart.return_value=False
        c.reader.bubbles.side_effect=[[{'resource':'gold','point':(500,500)}],[],[]]
        c.collect_view();c.r.tap.assert_not_called()

    def test_one_unchanged_bubble_does_not_cause_repeat_taps(self):
        c=self.collector();c.reader=MagicMock();c.reader.cart.return_value=False
        c.reader.bubbles.return_value=[{'resource':'gold','point':(500,500)}]
        c.reader.balances.return_value={'gold':100}
        c.collect_view();c.r.tap.assert_called_once_with((500,500))
        self.assertEqual(c.report['unverified'],1)

    def test_counter_animation_must_settle_before_recording_a_gain(self):
        c=self.collector();c.reader=MagicMock()
        c.reader.balances.side_effect=[{'gold':120},{'gold':140},{'gold':200},{'gold':200}]
        self.assertEqual(c.settled_balances(),{'gold':200})
        c.reader.balances.side_effect=[{'gold':n} for n in range(5)]
        self.assertEqual(c.settled_balances(),{})

    def test_delayed_star_bonus_is_settled_before_collection(self):
        c=self.collector();c.reader=MagicMock()
        c.r.reader.reward_button.return_value=(900,800)
        c.reader.cart.return_value=False;c.reader.bubbles.return_value=[]
        c.collect_view()
        c.r.settle_village.assert_called_once_with(c.r.reader.home)
        c.r.tap.assert_not_called()

    def test_changed_gems_save_evidence_and_block_the_visit(self):
        c=self.collector();c.reader=MagicMock();c.reader.cart.return_value=False
        c.settled_balances=MagicMock(side_effect=[{'gold':100,'gems':698}, {'gold':110,'gems':697}])
        c.collect_view=MagicMock();c.pan=MagicMock()
        with self.assertRaisesRegex(ValueError,'Gem balance changed'):
            c.run()
        self.assertEqual(c.report['status'],'needs_review')
        c.r.evidence.assert_called_once()
        c.r.phase.assert_called_with('collection_needs_review')

    def test_three_builders_supported_without_accepting_home_builder_count(self):
        cfg=SimpleNamespace(upgrade_excluded_names='',builder_base_builders_reserved=0,builder_base_gold_reserve=0)
        item=Candidate('Cannon',100,'gold',(1,2))
        for count in ((1,1),(1,2),(1,3),(2,3),(3,3)):
            self.assertIsNone(eligibility(cfg,item,{'gold':1000},count))
        for count in ((0,0),(0,3),(4,3),(1,6)):
            self.assertIsNotNone(eligibility(cfg,item,{'gold':1000},count))

    def test_reserved_builder_is_preserved_with_three_builders(self):
        cfg=SimpleNamespace(upgrade_excluded_names='',builder_base_builders_reserved=2,builder_base_gold_reserve=0)
        item=Candidate('Cannon',100,'gold',(1,2))
        self.assertIsNotNone(eligibility(cfg,item,{'gold':1000},(2,3)))
        self.assertIsNone(eligibility(cfg,item,{'gold':1000},(3,3)))


if __name__=='__main__': unittest.main()
