import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import cv2
import shutil
from coc_bot.accounts.store import read,write
from coc_bot.layouts.catalog import official_layout,placement_plan,catalog
from coc_bot.layouts.importer import LayoutReader,LayoutImporter


class LayoutTests(unittest.TestCase):
    def test_ranked_selected_card_keeps_active_lettering_above_ranked_label(self):
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/layouts/active-ranked-left-selected.png'))
        reader=LayoutReader()
        self.assertEqual(reader.active_slot(frame),0)
        self.assertIsNone(reader.active_slot((frame*.5).astype('uint8')))
        frame[359:407,160:525]=0
        self.assertIsNone(reader.active_slot(frame))

    def test_selected_active_card_uses_the_native_enlarged_badge(self):
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/layouts/active-middle-selected.png'))
        reader=LayoutReader()
        self.assertEqual(reader.active_slot(frame),1)
        frame[376:440,730:1110]=0
        self.assertIsNone(reader.active_slot(frame))

    def test_import_arrow_cannot_hide_the_active_slot_during_recovery(self):
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/layouts/import-covered-heading.png'))
        reader=LayoutReader()
        self.assertEqual(reader.active_slot(frame),0)
        frame[338:355,48:638]=0;frame[380:700,48:60]=0
        self.assertIsNone(reader.active_slot(frame))

    def test_interrupted_draft_save_reconciles_native_receipt_without_repeating_input(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as folder:
            s=SimpleNamespace(config=SimpleNamespace(data_dir=Path(folder),account_tag='#PYLQG'),capture=Mock(),input=Mock())
            importer=LayoutImporter(s);importer.reader=Mock()
            importer.reader.active_slot.return_value=0;importer.reader.selected_slot.return_value=1
            importer.reader.thumbnail.return_value=np.random.default_rng(4).integers(0,256,(32,64)).tolist()
            write(importer.path,{'pending':{'account':'#PYLQG','phase':'saving_draft','slot':1,'original_slot':0,'backup':'backup'}})
            self.assertTrue(importer.save_draft());self.assertIn('thumbnail',read(importer.path)['draft'])
            s.input.tap.assert_not_called()

    def test_spare_copy_never_chooses_the_working_draft_or_original_active_slot(self):
        reader=LayoutReader();root=Path(__file__).parent/'fixtures/layouts'
        frame=cv2.imread(str(root/'import-full.png'))
        chosen=reader.empty_slot(frame,replace_inactive=True)
        self.assertIsNotNone(chosen)
        protected=chosen['slot']
        other=reader.empty_slot(frame,replace_inactive=True,exclude_slots=(protected,))
        self.assertIsNotNone(other);self.assertNotEqual(other['slot'],protected)
        self.assertNotEqual(other['slot'],other['original_slot'])
        self.assertIsNone(reader.empty_slot(frame,replace_inactive=True,exclude_slots=(0,1,2)))
        with self.assertRaises(ValueError):reader.empty_slot(frame,exclude_slots=(True,))

    def test_resume_uses_saved_inactive_thumbnail_and_journals_before_edit(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as folder:
            s=SimpleNamespace(config=SimpleNamespace(data_dir=Path(folder),account_tag='#PYLQG',account_town_hall=10),capture=Mock(),input=Mock())
            importer=LayoutImporter(s);importer.reader=Mock();importer.open_editor=Mock(return_value=True)
            s.capture.screenshot.return_value=np.zeros((1048,1853,3),np.uint8)
            art=np.random.default_rng(5).integers(0,256,(32,64),dtype=np.uint8).tolist()
            draft={'account':'#PYLQG','hall':10,'slot':1,'original_slot':0,'backup':'backup','thumbnail':art}
            write(importer.path,{'draft':draft})
            importer.reader.active_slot.return_value=0;importer.reader.thumbnail.return_value=art
            importer.reader.edit_layout.return_value=(590,960);importer.reader.editing.return_value=True
            def tap(x,y,**kwargs):
                if (x,y)==(590,960):self.assertEqual(read(importer.path)['pending']['phase'],'resuming_draft')
            s.input.tap.side_effect=tap
            with patch('coc_bot.stop.interrupted_sleep',return_value=False):self.assertTrue(importer.resume_draft())
            self.assertEqual(read(importer.path)['pending']['phase'],'copying_to_empty_slot')
            self.assertNotIn('draft',read(importer.path));self.assertEqual(s.input.tap.call_count,2)

    def test_old_or_cross_account_drafts_cannot_be_resumed(self):
        with tempfile.TemporaryDirectory() as folder:
            s=SimpleNamespace(config=SimpleNamespace(data_dir=Path(folder),account_tag='#PYLQG',account_town_hall=10),capture=Mock(),input=Mock())
            importer=LayoutImporter(s)
            for draft in ({},{'account':'#PYLQG','hall':10,'slot':1,'original_slot':0,'backup':'backup'},
                          {'account':'#OTHER','thumbnail':[[42]*64]*32}):
                write(importer.path,{'draft':draft})
                with self.assertRaises(ValueError):importer.resume_draft()
            s.input.tap.assert_not_called()

    def test_normal_editor_requires_owned_chooser_and_enabled_edit_control(self):
        reader=LayoutReader();frame=cv2.imread(str(Path(__file__).parent/'fixtures/layouts/chooser-third-slot.png'))
        self.assertIsNotNone(reader.edit_layout(frame))
        dim=(frame*.5).astype('uint8')
        self.assertIsNone(reader.edit_layout(dim))
        frame[900:1027,445:730]=0
        self.assertIsNone(reader.edit_layout(frame))

    def test_failed_draft_save_keeps_checkpoint_when_active_village_changed(self):
        with tempfile.TemporaryDirectory() as folder:
            s=SimpleNamespace(config=SimpleNamespace(data_dir=Path(folder),account_tag='#PYLQG'),capture=Mock(),input=Mock())
            importer=LayoutImporter(s);importer.reader=Mock()
            importer.reader.inventory_notice.return_value=None
            importer.reader.draft_button.return_value=(1600,640)
            importer.reader.active_slot.return_value=1;importer.reader.selected_slot.return_value=1
            write(importer.path,{'pending':{'account':'#PYLQG','phase':'copying_to_empty_slot','slot':1,'original_slot':0,'backup':'backup'}})
            with patch('coc_bot.stop.interrupted_sleep',return_value=False):
                with self.assertRaisesRegex(ValueError,'Draft save'):importer.save_draft()
            self.assertIn('pending',read(importer.path));self.assertNotIn('draft',read(importer.path))

    @unittest.skipUnless(shutil.which('tesseract'),'OCR executable is required')
    def test_inventory_quantities_keep_their_leading_digits(self):
        from coc_bot.layouts.placement import first_item
        r=LayoutReader();root=Path(__file__).parent/'fixtures/layouts'
        for count in (6,14,274):
            with self.subTest(count=count):
                f=cv2.imread(str(root/('inventory-wall-'+str(count)+'.png')))
                self.assertEqual(first_item(r,f)['count'],count)
        # Losing the leading 2 must not silently turn a 274 stack into 74.
        number=f[846:894,37:182]
        white=cv2.inRange(cv2.cvtColor(number,cv2.COLOR_BGR2HSV),(0,0,220),(180,70,255))
        _,_,stats,_=cv2.connectedComponentsWithStats(white)
        parts=sorted([(x,y,w,h) for x,y,w,h,area in stats[1:] if h>=48*.35 and area>12])
        x,y,w,h=parts[1];number[y:y+h,x:x+w]=0
        self.assertIsNone(first_item(r,f))

    def test_current_chooser_uses_lettering_instead_of_thumbnail_scenery(self):
        r=LayoutReader();f=cv2.imread(str(Path(__file__).parent/'fixtures/layouts/chooser-third-slot.png'))
        self.assertEqual(r.active_slot(f),0);self.assertEqual(r.selected_slot(f),2)
        f[380:465,56:630]=0
        self.assertIsNone(r.active_slot(f));self.assertIsNone(r.selected_slot(f))

    def test_discard_dialog_needs_its_exact_explanation_and_green_control(self):
        r=LayoutReader();f=cv2.imread(str(Path(__file__).parent/'fixtures/layouts/discard-confirm.png'))
        self.assertIsNotNone(r.discard_confirmation(f))
        f[436:515,528:1326]=0
        self.assertIsNone(r.discard_confirmation(f))

    def test_incomplete_or_uncertain_layout_cannot_be_activated(self):
        with tempfile.TemporaryDirectory() as folder:
            s=SimpleNamespace(config=SimpleNamespace(data_dir=Path(folder),account_tag='#PYLQG'),capture=Mock(),input=Mock())
            i=LayoutImporter(s)
            p={'account':'#PYLQG','phase':'copying_to_empty_slot','slot':1,'original_slot':0,'backup':'backup'}
            for change in ({},{'phase':'ready_to_activate'},{'phase':'ready_to_activate','saved_at':1,'placement':{'phase':'moving'}}):
                write(i.path,{'pending':p|change})
                with self.assertRaises(ValueError):i.activate()
            s.input.tap.assert_not_called()

    def test_activation_journals_before_input_and_verifies_active_twice(self):
        with tempfile.TemporaryDirectory() as folder:
            s=SimpleNamespace(config=SimpleNamespace(data_dir=Path(folder),account_tag='#PYLQG'),capture=Mock(),input=Mock())
            i=LayoutImporter(s);i.reader=Mock()
            p={'account':'#PYLQG','phase':'ready_to_activate','slot':1,'original_slot':0,'backup':'backup','saved_at':1}
            write(i.path,{'pending':p,'draft':{'slot':1}})
            i.reader.active_slot.side_effect=[0,0,1,1]
            i.reader.selected_slot.return_value=1;i.reader.set_active.return_value=(1260,960)
            def tapped(*args,**kwargs):self.assertEqual(read(i.path)['pending']['phase'],'activating')
            s.input.tap.side_effect=tapped
            with patch('coc_bot.stop.interrupted_sleep',return_value=False):self.assertTrue(i.activate())
            self.assertEqual(read(i.path)['completed']['status'],'active');s.input.tap.assert_called_once()
            self.assertNotIn('draft',read(i.path))

    def test_owned_discard_confirmation_can_resume_without_another_edit(self):
        with tempfile.TemporaryDirectory() as folder:
            s=SimpleNamespace(config=SimpleNamespace(data_dir=Path(folder),account_tag='#PYLQG'),capture=Mock(),input=Mock())
            i=LayoutImporter(s);i.reader=Mock();i.reader.editing.return_value=False
            i.reader.discard_confirmation.side_effect=[(1127,674),(1127,674),None]
            i.reader.active_slot.return_value=0
            write(i.path,{'pending':{'account':'#PYLQG','phase':'cancelling_obstacle_survey',
                'slot':2,'original_slot':0,'backup':'backup'}})
            with patch('coc_bot.stop.interrupted_sleep',return_value=False):self.assertTrue(i.cancel_obstacle_survey())
            s.input.tap.assert_called_once_with(1127,674,jitter=0)
            self.assertNotIn('pending',read(i.path))

    def test_only_hall_matched_official_home_layout_links_are_accepted(self):
        url='https://link.clashofclans.com/en/?action=OpenLayout&id=TH10:HV:abcdefghijklmnopqrstuv'
        self.assertIn('TH10%3AHV%3A',official_layout(url,10))
        for bad in (url.replace('https:','http:'),url.replace('com/','com.evil/'),
                    url.replace(':HV:',':WB:'),url+'&extra=1',url+'#fragment',
                    url.replace('TH10:','TH11:'),url.replace('OpenLayout','OpenProfile')):
            with self.subTest(bad=bad),self.assertRaises(ValueError):official_layout(bad,10)

    def test_missing_buildings_leave_their_exact_reserved_footprints_empty(self):
        plan=[{'name':'Town Hall','x':20,'y':20,'width':4,'height':4},
              {'name':'Cannon','x':25,'y':20,'width':3,'height':3}]
        result=placement_plan(plan,{'Town Hall':1})
        self.assertEqual(result['placements'],plan[:1]);self.assertEqual(result['empty'],plan[1:])
        self.assertTrue(result['complete'])

    def test_unknown_remaining_buildings_and_overlaps_prevent_activation(self):
        item={'name':'Cannon','x':25,'y':20,'width':3,'height':3}
        self.assertFalse(placement_plan([item],{'Cannon':2})['complete'])
        with self.assertRaises(ValueError):placement_plan([item,item],{'Cannon':2})
        with self.assertRaises(ValueError):placement_plan([item|{'x':43}],{'Cannon':1})

    def test_catalog_does_not_claim_candidates_are_live_verified(self):
        self.assertEqual({e['hall'] for e in catalog()}, set(range(2,19)))
        self.assertTrue(all(e['status']!='verified' for e in catalog()))

    def test_import_only_selects_a_verified_empty_inactive_slot(self):
        reader=LayoutReader();folder=Path(__file__).parent/'fixtures/layouts'
        for name in ('import-empty.png','import-ranked.png'):
            frame=cv2.imread(str(folder/name));result=reader.empty_slot(frame)
            self.assertEqual((result['slot'],result['original_slot']),(1,0))
            frame[820:861,591:1269]=0
            self.assertIsNone(reader.empty_slot(frame))

    def test_incomplete_copy_is_recognized_but_never_treated_as_active(self):
        reader=LayoutReader();frame=cv2.imread(str(Path(__file__).parent/'fixtures/layouts/unplaced-notice.png'))
        self.assertIsNotNone(reader.inventory_notice(frame))
        self.assertIsNone(reader.empty_slot(frame))
        frame[410:550,533:1322]=0
        self.assertIsNone(reader.inventory_notice(frame))

    def test_edit_heading_ignores_scenery_but_not_modal_dimming(self):
        reader=LayoutReader()
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/layouts/editor-heading.png'))
        self.assertTrue(reader.editing(frame));self.assertIsNotNone(reader.draft_button(frame))
        self.assertFalse(reader.editing((frame*.4).astype('uint8')))
        frame[:94,:519]=0
        self.assertFalse(reader.editing(frame));self.assertIsNone(reader.draft_button(frame))

    def test_existing_layout_obstacle_notice_requires_message_title_and_okay(self):
        reader=LayoutReader()
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/layouts/existing-obstacle-notice.png'))
        self.assertIsNotNone(reader.inventory_notice(frame))
        self.assertFalse(reader.editing(frame))
        for top,bottom,left,right in ((435,522,522,1332),(280,350,660,1200),(640,700,840,1010)):
            masked=frame.copy();masked[top:bottom,left:right]=0
            self.assertIsNone(reader.inventory_notice(masked))
        self.assertIsNone(reader.inventory_notice((frame*.4).astype('uint8')))

    def test_inactive_replacement_requires_explicit_opt_in_and_import_arrow(self):
        reader=LayoutReader()
        for name in ('import-full.png','import-full-bounce.png'):
            frame=cv2.imread(str(Path(__file__).parent/'fixtures/layouts'/name))
            self.assertIsNone(reader.empty_slot(frame))
            result=reader.empty_slot(frame,replace_inactive=True)
            self.assertEqual((result['slot'],result['original_slot'],result['replacing']),(1,0,True))
            frame[380:550,660:1800]=0
            self.assertIsNone(reader.empty_slot(frame,replace_inactive=True))

    def test_changed_or_full_import_does_not_replace_an_existing_slot(self):
        with tempfile.TemporaryDirectory() as folder:
            session=SimpleNamespace(config=SimpleNamespace(data_dir=Path(folder),account_tag='#PYLQG'),
                                    capture=Mock(),input=Mock())
            importer=LayoutImporter(session);importer.reader=Mock()
            write(importer.path,{'pending':{'phase':'opening','account':'#PYLQG'}})
            importer.reader.empty_slot.return_value=None
            with patch('coc_bot.stop.interrupted_sleep',return_value=False),self.assertRaisesRegex(ValueError,'No verified inactive'):importer.select_empty()
            session.input.tap.assert_not_called()
            self.assertEqual(read(importer.path)['pending']['phase'],'opening')

    def test_slow_deep_link_waits_for_the_same_inactive_slot_on_two_frames(self):
        with tempfile.TemporaryDirectory() as folder:
            session=SimpleNamespace(config=SimpleNamespace(data_dir=Path(folder),account_tag='#PYLQG'),
                                    capture=Mock(),input=Mock())
            importer=LayoutImporter(session);importer.reader=Mock()
            write(importer.path,{'pending':{'phase':'opening','account':'#PYLQG'}})
            slot={'slot':1,'original_slot':0,'point':(923,555),'replacing':True}
            importer.reader.empty_slot.side_effect=[None,None,slot,slot]
            with patch('coc_bot.stop.interrupted_sleep',return_value=False):
                self.assertTrue(importer.select_empty(replace_inactive=True))
            session.input.tap.assert_called_once_with(923,555,jitter=0)
            self.assertEqual(read(importer.path)['pending']['slot'],1)

    def test_survey_confirmation_requires_exact_title_and_buildings_message(self):
        reader=LayoutReader()
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/layouts/collect-all.png'))
        self.assertIsNotNone(reader.collect_all_confirmation(frame))
        self.assertFalse(reader.editing(frame))
        frame[450:510,500:1340]=0
        self.assertIsNone(reader.collect_all_confirmation(frame))

    def test_survey_exit_requires_one_verified_active_home_slot(self):
        reader=LayoutReader()
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/layouts/survey-cancelled.png'))
        self.assertEqual(reader.active_slot(frame),0)
        frame[380:470,130:560]=0
        self.assertIsNone(reader.active_slot(frame))

    def test_remove_all_is_blocked_on_active_foreign_and_unbacked_layouts(self):
        with tempfile.TemporaryDirectory() as folder:
            session=SimpleNamespace(config=SimpleNamespace(data_dir=Path(folder),account_tag='#PYLQG'),
                                    capture=Mock(),input=Mock())
            importer=LayoutImporter(session)
            pending={'phase':'copying_to_empty_slot','account':'#PYLQG','slot':1,'original_slot':0,'backup':'backup'}
            for change in ({'slot':0},{'account':'#OTHER'},{'backup':None},{'slot':True},{'original_slot':4}):
                write(importer.path,{'pending':pending|change})
                with self.assertRaises(ValueError):importer.expose_obstacles()
            session.capture.screenshot.assert_not_called();session.input.tap.assert_not_called()

    def test_remove_all_journals_before_input_and_cannot_be_repeated(self):
        with tempfile.TemporaryDirectory() as folder:
            session=SimpleNamespace(config=SimpleNamespace(data_dir=Path(folder),account_tag='#PYLQG'),
                                    capture=Mock(),input=Mock())
            importer=LayoutImporter(session);importer.reader=Mock()
            importer.reader.remove_all_button.return_value=(1660,155)
            write(importer.path,{'pending':{'phase':'copying_to_empty_slot','account':'#PYLQG',
                'slot':1,'original_slot':0,'backup':'backup'},'draft':{'status':'draft_needs_placement'}})
            def tapped(*args,**kwargs):self.assertEqual(read(importer.path)['pending']['phase'],'surveying_obstacles')
            session.input.tap.side_effect=tapped
            with patch('coc_bot.stop.interrupted_sleep',return_value=False):self.assertTrue(importer.expose_obstacles())
            with self.assertRaises(ValueError):importer.expose_obstacles()
            session.input.tap.assert_called_once()
            self.assertEqual(read(importer.path)['draft']['status'],'draft_needs_placement')

    def test_survey_stop_and_changed_confirmation_send_no_input(self):
        with tempfile.TemporaryDirectory() as folder:
            session=SimpleNamespace(config=SimpleNamespace(data_dir=Path(folder),account_tag='#PYLQG'),
                                    capture=Mock(),input=Mock())
            importer=LayoutImporter(session);importer.reader=Mock()
            pending={'phase':'surveying_obstacles','account':'#PYLQG','slot':1,'original_slot':0,'backup':'backup'}
            write(importer.path,{'pending':pending})
            importer.reader.collect_all_confirmation.side_effect=[(1100,675),None]
            self.assertFalse(importer.confirm_obstacle_survey())
            importer.stop=lambda:True
            self.assertFalse(importer.cancel_obstacle_survey())
            session.input.tap.assert_not_called();self.assertIn('pending',read(importer.path))

    def test_cancel_reconciles_only_the_original_active_slot_and_retains_draft(self):
        with tempfile.TemporaryDirectory() as folder:
            session=SimpleNamespace(config=SimpleNamespace(data_dir=Path(folder),account_tag='#PYLQG'),
                                    capture=Mock(),input=Mock())
            importer=LayoutImporter(session);importer.reader=Mock()
            importer.reader.editing.return_value=False
            write(importer.path,{'pending':{'phase':'surveying_obstacles','account':'#PYLQG',
                'slot':1,'original_slot':0,'backup':'backup'},'draft':{'status':'draft_needs_placement'}})
            importer.reader.active_slot.return_value=1
            with patch('coc_bot.stop.interrupted_sleep',return_value=False):
                self.assertFalse(importer.cancel_obstacle_survey())
            self.assertIn('pending',read(importer.path))
            importer.reader.active_slot.return_value=0
            self.assertTrue(importer.cancel_obstacle_survey())
            result=read(importer.path);self.assertNotIn('pending',result)
            self.assertEqual(result['draft']['status'],'draft_needs_placement')
            self.assertEqual(result['last_survey']['status'],'cancelled')
            session.input.tap.assert_not_called()
