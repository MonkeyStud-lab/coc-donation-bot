from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock,patch
import cv2
import numpy as np
from coc_bot.layouts.verification import active_preview,compare
from coc_bot.layouts.runner import LayoutRunner
from coc_bot.layouts.importer import LayoutReader
from coc_bot.accounts.store import read,write

FIXTURES=Path(__file__).parent/'fixtures/layouts'


class HomeLayoutProofTests(unittest.TestCase):
    def test_idle_instruction_ignores_obstacles_behind_gaps_but_requires_its_letters(self):
        r=LayoutReader();f=cv2.imread(str(FIXTURES/'idle-instruction-obstacles.png'))
        self.assertTrue(r.idle_editor(f))
        f[730:824,500:1350]=255
        self.assertFalse(r.idle_editor(f))
        f[730:824,500:1350]=0
        self.assertFalse(r.idle_editor(f))

    def test_unselected_ranked_active_caption_has_its_own_native_font(self):
        r=LayoutReader();f=cv2.imread(str(FIXTURES/'active-unselected-ranked.png'))
        self.assertEqual(r.active_slot(f),0)
        self.assertEqual(r.selected_slot(f),2)
        f[374:465,150:540]=0
        self.assertIsNone(r.active_slot(f))

    def test_chat_overlay_needs_both_native_editor_controls(self):
        r=LayoutReader();f=cv2.imread(str(FIXTURES/'editor-chat-overlay.png'))
        self.assertIsNotNone(r.editor_chat_close(f))
        self.assertFalse(r.editing(f))
        f[125:185,1550:1815]=0
        self.assertIsNone(r.editor_chat_close(f))

    def test_actual_home_matches_active_preview_but_not_the_old_arrangement(self):
        with np.load(FIXTURES/'home-layout-proof.npz',allow_pickle=False) as data:
            expected={'features':data['expected'],'visible':data['expected_visible']}
            actual={'features':data['actual'],'visible':data['actual_visible']}
            wrong={'features':data['wrong'],'visible':data['wrong_visible']}
            result=compare(expected,actual)
            self.assertTrue(result['verified']);self.assertGreater(result['correlation'],.95)
            self.assertFalse(compare(wrong,actual)['verified'])
            cropped={'features':data['actual'],'visible':np.zeros((22,22),bool)}
            self.assertFalse(compare(expected,cropped)['verified'])
        self.assertFalse(compare(None,actual)['verified'])
        blank={'features':np.zeros((22,22,2)),'visible':np.ones((22,22),bool)}
        self.assertFalse(compare(blank,blank)['verified'])

    def test_only_the_native_active_frame_can_supply_the_preview(self):
        f=cv2.imread(str(FIXTURES/'active-middle-selected.png'))
        self.assertIsNotNone(active_preview(f,1))
        self.assertIsNone(active_preview(f,0));self.assertIsNone(active_preview(f,2))
        f[338:355,627:1217]=0
        self.assertIsNone(active_preview(f,1))

    def test_new_build_menu_hand_needs_the_menu_heading(self):
        r=LayoutReader();f=cv2.imread(str(FIXTURES/'builder-editor-entry.png'))
        with patch('coc_bot.upgrades.vision.UpgradeReader.menu_kind',return_value='buildings'):
            self.assertIsNotNone(r.builder_editor(f))
            f[770:900,1195:1320]=0;self.assertIsNone(r.builder_editor(f))
        with patch('coc_bot.upgrades.vision.UpgradeReader.menu_kind',return_value=None):
            self.assertIsNone(r.builder_editor(f))

    def runner(self,root):
        config=SimpleNamespace(data_dir=root,account_tag='#PYLQG',account_town_hall=12)
        return LayoutRunner(SimpleNamespace(config=config,capture=Mock(),input=Mock()))

    def test_confirmed_removal_retries_copy_without_erasing_settlement_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            r=self.runner(Path(folder))
            write(r.i.path,{'automatic':{'stage':'clearing'},'last_survey':{'payment_receipt':
                {'operation':'one','at':100,'finished_at':120}}})
            r.remember_removal();r.remember_removal()
            state=read(r.i.path)['automatic']
            self.assertEqual(state['stage'],'clearing')
            self.assertEqual(state['removal_settle_until'],123)
            self.assertEqual(len(state['removals']),1)

    def test_exhausted_copy_clears_sequentially_without_discarding_saved_progress(self):
        with tempfile.TemporaryDirectory() as folder:
            r=self.runner(Path(folder));draft={'slot':2,'placements':[{'phase':'confirmed'}]}
            write(r.i.path,{'automatic':{'clearance_pass':True,'survey_cursor':2},'draft':draft,
                'last_survey':{'payment_receipt':{'operation':'one','at':100,'finished_at':120}}})
            r.remember_removal();r.remember_removal()
            state=read(r.i.path)
            self.assertEqual(state['automatic']['stage'],'clearing')
            self.assertEqual(state['automatic']['survey_cursor'],2)
            self.assertEqual(state['automatic']['removal_settle_until'],123)
            self.assertEqual(len(state['automatic']['removals']),1)
            self.assertEqual(state['draft'],draft)

    def test_complete_clearance_reimports_once_and_keeps_the_previous_draft(self):
        with tempfile.TemporaryDirectory() as folder:
            r=self.runner(Path(folder));draft={'slot':2,'placements':[{'phase':'confirmed'}]}
            write(r.i.path,{'automatic':{'clearance_pass':True,'last_removal_at':100},'draft':draft})
            r.finish_clearance('source',[(11,11),(33,33)])
            state=read(r.i.path)
            self.assertEqual(state['automatic']['stage'],'matching')
            self.assertFalse(state['automatic']['clearance_pass'])
            self.assertEqual(state['automatic']['fit_retry'],{'link':'source','last_removal_at':100})
            self.assertEqual(state['draft'],draft)
            r.s.input.tap.assert_not_called()

    def test_removal_preserves_confirmed_progress_only_for_the_owned_same_source(self):
        from coc_bot.layouts.runner import REVISION
        with tempfile.TemporaryDirectory() as folder:
            r=self.runner(Path(folder))
            draft={'account':'#PYLQG','hall':12,'link':'source','automatic_revision':REVISION,
                   'saved_at':80,'placements':[{'phase':'confirmed'}]}
            for owner,stage in (('#PYLQG','clearing'),('#OTHER','clearing')):
                write(r.i.path,{'automatic':{},'draft':draft|{'account':owner},
                    'last_survey':{'link':'source','payment_receipt':{'operation':'one','at':100}}})
                r.remember_removal()
                self.assertEqual(read(r.i.path)['automatic']['stage'],stage)

    def test_saved_placements_resume_even_after_a_more_recent_obstacle_removal(self):
        from coc_bot.layouts.runner import REVISION
        with tempfile.TemporaryDirectory() as folder:
            r=self.runner(Path(folder));r.s.config.layouts_replace_inactive=True
            write(r.i.path,{'automatic':{'last_removal_at':100},'draft':{
                'account':'#PYLQG','automatic_revision':REVISION,'hall':12,'link':'source','saved_at':80,
                'placement_view':4,'failed_ground':[{'size':3,'tiles':[[5.5,6.5]]}],
                'placements':[{'phase':'confirmed'}]}})
            with patch.object(r.i,'resume_draft',return_value=True) as resume,\
                 patch.object(r,'_open') as opening,\
                 patch.object(r,'_place_open',return_value={'status':'draft'}):
                self.assertEqual(r._place('source',12,1000)['status'],'draft')
            resume.assert_called_once();opening.assert_not_called()
            draft=read(r.i.path)['draft']
            self.assertEqual(draft['placement_view'],0)
            self.assertEqual(draft['failed_ground'],[{'size':3,'tiles':[]}])
            self.assertEqual(draft['placements'],[{'phase':'confirmed'}])

    def test_complete_copy_activates_without_clearing_or_rearranging(self):
        with tempfile.TemporaryDirectory() as folder:
            r=self.runner(Path(folder));r.i.reader=Mock();r.i.reader.ready_save.return_value=(100,100)
            with patch.object(r,'_open',return_value=True),\
                 patch.object(r,'_activate_complete',return_value={'status':'active'}) as active,\
                 patch.object(r,'_place_open') as placing:
                self.assertEqual(r._import('link',12,100)['status'],'active')
            active.assert_called_once_with(12,0);placing.assert_not_called();r.s.input.tap.assert_not_called()

    def test_badge_alone_does_not_mark_automatic_layout_as_active(self):
        with tempfile.TemporaryDirectory() as folder:
            r=self.runner(Path(folder))
            r.i.save_complete=Mock(return_value=True);r.i.activate=Mock(return_value=True)
            with patch.object(r,'_verify_active_home',return_value={'verified':False,'reason':'Different Home layout'}):
                result=r._activate_complete(12,0)
            self.assertEqual(result['status'],'verifying')
            self.assertEqual(read(r.i.path)['automatic']['stage'],'verifying')
            self.assertTrue(read(r.i.path)['automatic']['dirty'])
