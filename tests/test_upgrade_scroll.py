"""Bounded Build-list searches and independently confirmed inventory endings."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock,patch
import cv2
import numpy as np
from coc_bot.upgrades.scroll import menu_list_unchanged
from coc_bot.progression.runner import ProgressionRunner
from coc_bot.progression.preparation import ArmyPreparation


def frame():
    image=np.zeros((600,1000,3),np.uint8);image[:,735:]=(90,130,170)
    for i,y in enumerate(range(100,520,70)):
        cv2.putText(image,'Tower '+str(i),(780,y),cv2.FONT_HERSHEY_SIMPLEX,.5,(255,255,255),1)
    return image


class UpgradeScrollTests(TestCase):
    def test_stationary_list_ignores_village_thumbnails_and_timers(self):
        before=frame();after=before.copy()
        after[:,:770]=(255,0,0);after[:,940:]=(0,255,0)
        self.assertTrue(menu_list_unchanged(before,after))

    def test_moving_dimmed_blank_or_resized_lists_are_not_confirmed(self):
        before=frame();moved=before.copy();moved[66:534,775:925]=np.roll(moved[66:534,775:925],15,axis=0)
        for other in (moved,before//2,np.zeros_like(before),before[:500]):
            with self.subTest(shape=other.shape):self.assertFalse(menu_list_unchanged(before,other))

    def runner(self,folder,images):
        runner=ProgressionRunner.__new__(ProgressionRunner)
        runner.config=SimpleNamespace(data_dir=Path(folder));runner.stop=None
        runner.clear_filters=Mock(side_effect=lambda f:f);runner.stopped=Mock(return_value=False)
        runner.reader=Mock();runner.reader.menu_kind.return_value='buildings'
        runner.reader.balances.return_value={'gold':100000};runner.reader.availability.return_value=(1,2)
        runner.reader.rows.return_value=[{'name':'Wall','new':False,'level':None,'cost':1000,'currency':'gold','point':(850,100),'box':(735,80,265,70)}]
        runner.capture=Mock();runner.capture.screenshot.side_effect=images
        runner.input=Mock();runner.wait=Mock(return_value=False)
        return runner

    def test_complete_inventory_requires_two_different_stationary_swipes(self):
        before=frame()
        with TemporaryDirectory() as folder:
            runner=self.runner(folder,[before.copy(),before.copy()])
            result=runner.scan(before)
            self.assertTrue(result['complete'])
            self.assertEqual([c.kwargs['duration_ms'] for c in runner.input.swipe.call_args_list],[350,180])
            runner.input.tap.assert_not_called()

    def test_short_confirmation_that_moves_must_not_certify_an_end(self):
        before=frame();moved=before.copy();moved[66:534,775:925]=np.roll(moved[66:534,775:925],15,axis=0)
        with TemporaryDirectory() as folder:
            runner=self.runner(folder,[before.copy(),moved,moved.copy(),moved.copy()])
            self.assertTrue(runner.scan(before)['complete'])
            self.assertEqual(runner.input.swipe.call_count,4)

    def test_complete_inventory_includes_rows_read_in_the_final_settled_frame(self):
        before=frame()
        with TemporaryDirectory() as folder:
            runner=self.runner(folder,[before.copy(),before.copy()])
            first=runner.reader.rows.return_value[0]
            runner.reader.rows.side_effect=[[first],[first|{'name':'Laboratory','cost':2000}]]
            result=runner.scan(before)
            self.assertTrue(result['complete'])
            self.assertEqual([r['name'] for r in result['rows']],['Wall','Laboratory'])

    def test_menu_disappearing_during_end_confirmation_never_completes(self):
        before=frame()
        with TemporaryDirectory() as folder:
            runner=self.runner(folder,[before.copy(),before.copy()])
            runner.reader.menu_kind.side_effect=['buildings','buildings',None]
            with self.assertRaisesRegex(ValueError,'end verification'):runner.scan(before)
            runner.input.tap.assert_not_called()

    def test_missing_target_stops_after_one_stationary_scroll(self):
        before=frame()
        with TemporaryDirectory() as folder:
            runner=self.runner(folder,[before.copy(),before.copy()]);runner.open_menu=Mock(return_value=before)
            wanted={'name':'Laboratory','new':False,'level':None,'cost':1000,'currency':'gold'}
            self.assertIsNone(runner.find_row(wanted))
            self.assertEqual(runner.input.swipe.call_count,1)

    def test_builder_free_structure_search_also_stops_at_the_bottom(self):
        from coc_bot.builder_base.progression import BuilderProgressionRunner
        before=frame()
        with TemporaryDirectory() as folder:
            runner=self.runner(folder,[before.copy(),before.copy()]);runner.open_menu=Mock(return_value=before)
            wanted={'name':'Army Camp','new':True,'level':None,'cost':0,'currency':'free'}
            self.assertIsNone(BuilderProgressionRunner.find_row(runner,wanted))
            self.assertEqual(runner.input.swipe.call_count,1)

    def test_missing_town_hall_stops_at_the_bottom_instead_of_twenty_swipes(self):
        before=frame();prep=ArmyPreparation.__new__(ArmyPreparation)
        prep.s=SimpleNamespace(config=SimpleNamespace(account_town_hall=18),capture=Mock(),input=Mock(),navigator=Mock(),_sleep=Mock())
        prep.stop=None;prep.frame=Mock(return_value=before);prep.tap=Mock()
        runner=Mock();runner.open_menu.return_value=before;runner.clear_filters.return_value=before
        runner.reader.rows.return_value=[{'name':'Wall'}];runner.reader.menu_kind.return_value='buildings'
        runner.reader.detail_close.return_value=None
        with patch('coc_bot.progression.preparation.ProgressionRunner',return_value=runner):
            with self.assertRaisesRegex(ValueError,'Town Hall entry was not found'):prep.hall()
        self.assertEqual(prep.s.input.swipe.call_count,1);prep.tap.assert_not_called()
