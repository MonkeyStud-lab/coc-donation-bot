from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import Mock,patch
import numpy as np
from coc_bot.accounts.store import read,write
from coc_bot.layouts.runner import LayoutRunner,REVISION,dirty
from coc_bot.layouts.catalog import official_layout
from coc_bot.layouts.compatibility import assess_remaining


class ClearFirstTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        c=SimpleNamespace(data_dir=Path(self.tmp.name),account_tag='#TEST',account_town_hall=16,
            dry_run=False,layouts_enabled=True,layouts_replace_inactive=True,
            progression_clear_obstacles=True,donation_enabled=False)
        self.r=LayoutRunner(SimpleNamespace(config=c,capture=Mock(),input=Mock()))
        self.links=[official_layout('https://link.clashofclans.com/en/?action=OpenLayout&id=TH16:HV:'+v,16)
                    for v in ('ABCDEFGHIJKL','MNOPQRSTUVWX')]
        self.catalog=patch('coc_bot.layouts.runner.catalog',return_value=[{'link':v} for v in self.links])
        self.catalog.start();self.addCleanup(self.catalog.stop)
        self.r.home=Mock(return_value=True)

    def state(self,**values):
        write(self.r.i.path,{'automatic':dict(hall=16,revision=REVISION,stage='matching',
              cleared_at=time.time(),**values)})

    def test_old_partial_layout_migrates_to_clear_first_and_preserves_draft(self):
        draft={'placements':[{'confirmed':True}],'slot':2}
        write(self.r.i.path,{'draft':draft,'automatic':{'hall':16,'revision':'old','stage':'placing'}})
        with patch.object(self.r,'_clear_one',return_value={'status':'waiting'}) as clear,patch.object(self.r,'_import') as imp:
            self.r.run()
        clear.assert_called_once();imp.assert_not_called()
        self.assertEqual(read(self.r.i.path)['draft'],draft)

    def test_verified_active_layout_is_not_rebuilt_for_policy_change(self):
        write(self.r.i.path,{'completed':{'account':'#TEST','hall':16,'home_verified':True,'home_verified_at':time.time()},
            'automatic':{'hall':16,'revision':'old','stage':'active','dirty':False}})
        self.assertEqual(self.r.run()['status'],'current')
        self.r.s.input.tap.assert_not_called()

    def test_all_candidates_are_checked_before_small_fallback(self):
        self.state(compatibility={self.links[0]:{'count':2,'small':True}})
        with patch.object(self.r,'_import',return_value={'status':'matching'}) as imp:
            self.r.run()
        self.assertEqual(imp.call_args.args[0],self.links[1])
        self.assertIsNone(read(self.r.i.path)['automatic'].get('selected_reference'))

    def test_best_small_native_fit_is_selected(self):
        self.state(compatibility={self.links[0]:{'count':5,'small':True},self.links[1]:{'count':2,'small':True}})
        with patch.object(self.r,'_import',return_value={'status':'draft'}) as imp:self.r.run()
        self.assertEqual(imp.call_args.args[0],self.links[1])
        self.assertEqual(read(self.r.i.path)['automatic']['selected_reference'],self.links[1])

    def test_bounded_trial_is_selected_only_after_all_native_imports(self):
        self.state(compatibility={self.links[0]:{'count':4,'small':False,'probe':True},self.links[1]:{'count':20,'small':False}})
        with patch.object(self.r,'_import',return_value={'status':'draft'}) as imp:self.r.run()
        self.assertEqual(imp.call_args.args[0],self.links[0])

    def test_resumed_trial_cannot_make_a_seventh_placement(self):
        self.state();v=read(self.r.i.path);v['pending']={'placements':[{}]*6,'bounded_trial':True};write(self.r.i.path,v)
        self.r.i.reader.ready_save=Mock(return_value=None);self.r.i.show_tools=Mock(return_value=True)
        with patch.object(self.r,'reframe',return_value=True),patch('coc_bot.layouts.runner.InventoryPlacer') as place,patch.object(self.r,'_activate_complete') as activate:
            result=self.r._place_open(self.links[0],16,time.monotonic()+30)
        self.assertEqual(result['status'],'candidate_incomplete');place.assert_not_called();activate.assert_not_called()
        self.assertIn(self.links[0],read(self.r.i.path)['automatic']['unfit_references'])

    def test_native_completion_after_six_moves_still_requires_activation_verification(self):
        self.state();v=read(self.r.i.path);v['pending']={'placements':[{}]*6,'bounded_trial':True};write(self.r.i.path,v)
        self.r.i.reader.ready_save=Mock(return_value=(1700,630));self.r.i.show_tools=Mock(return_value=True)
        with patch.object(self.r,'reframe',return_value=True),patch('coc_bot.layouts.runner.InventoryPlacer') as place,patch.object(self.r,'_activate_complete',return_value={'status':'verifying'}) as activate:
            self.assertEqual(self.r._place_open(self.links[0],16,time.monotonic()+30)['status'],'verifying')
        place.assert_not_called();activate.assert_called_once()

    def test_large_mismatches_never_trigger_mass_placement(self):
        self.state(compatibility={v:{'count':20,'small':False} for v in self.links})
        with patch.object(self.r,'_import') as imp:
            self.assertEqual(self.r.run()['status'],'needs_reference')
        imp.assert_not_called();self.r.s.input.tap.assert_not_called()

    def test_unknown_candidate_does_not_hide_other_complete_fits(self):
        self.state(compatibility={self.links[0]:{'count':None,'small':False,'unreadable':True}})
        with patch.object(self.r,'_import',return_value={'status':'active'}) as imp:self.r.run()
        self.assertEqual(imp.call_args.args[0],self.links[1])

    def test_unreadable_candidates_are_retryable_not_declared_incompatible(self):
        self.state(compatibility={v:{'count':None,'small':False,'unreadable':True} for v in self.links})
        self.assertEqual(self.r.run()['status'],'unreadable_inventory')
        self.assertEqual(read(self.r.i.path)['automatic']['compatibility'],{})
        self.r.s.input.tap.assert_not_called()

    def test_new_catalog_candidate_reopens_a_missing_reference_without_losing_clearance(self):
        self.state(compatibility={self.links[0]:{'count':20,'small':False}})
        v=read(self.r.i.path);v['automatic']['stage']='needs_reference';write(self.r.i.path,v)
        with patch.object(self.r,'_import',return_value={'status':'matching'}) as imp:
            self.r.run()
        self.assertEqual(imp.call_args.args[0],self.links[1])

    def test_new_candidate_cannot_reuse_expired_clearance(self):
        self.state(compatibility={self.links[0]:{'count':20,'small':False}})
        v=read(self.r.i.path);v['automatic'].update(stage='needs_reference',cleared_at=1);write(self.r.i.path,v)
        with patch.object(self.r,'_clear_one',return_value={'status':'yielding'}) as clear,patch.object(self.r,'_import') as imp:
            self.r.run()
        clear.assert_called_once();imp.assert_not_called()

    def test_unreadable_inventory_cannot_activate_or_place(self):
        self.state();self.r.i.reader.ready_save=Mock(return_value=None)
        with patch.object(self.r,'_open',return_value=True),patch.object(self.r,'close_unsaved',return_value=True),patch('coc_bot.layouts.compatibility.assess_remaining',return_value=None),patch.object(self.r,'_place_open') as place,patch.object(self.r,'_activate_complete') as activate:
            self.assertEqual(self.r._import(self.links[0],16,100)['status'],'matching')
        place.assert_not_called();activate.assert_not_called()

    def test_construction_invalidates_clearance_and_native_fit(self):
        self.state(compatibility={'x':{'small':True}},selected_reference='x')
        dirty(self.r.s.config);a=read(self.r.i.path)['automatic']
        self.assertEqual(a['stage'],'clearing');self.assertEqual(a['compatibility'],{})
        self.assertFalse(a['cleared_at'])

    def test_survey_entry_does_not_open_copy_link(self):
        i=self.r.i;i.open_editor=Mock(return_value=True);i.reader=Mock()
        f=np.zeros((1048,1853,3),np.uint8);self.r.s.capture.screenshot.return_value=f
        i.reader.active_slot.return_value=0;i.reader.selected_slot.return_value=1
        i.reader.edit_layout.return_value=(600,960);i.reader.editing.return_value=True
        with patch('coc_bot.layouts.importer.backup',return_value='saved'),patch('coc_bot.stop.interrupted_sleep',return_value=False),patch.object(i,'open') as copy:
            self.assertTrue(i.open_survey(16,{'gems':123}))
        copy.assert_not_called()
        p=read(i.path)['pending'];self.assertEqual(p['original_slot'],0);self.assertEqual(p['slot'],1)
        self.assertEqual(p['purpose'],'clear_build_zone')

    def test_survey_does_not_edit_the_protected_draft(self):
        i=self.r.i;i.open_editor=Mock(return_value=True);i.reader=Mock()
        draft={'account':'#TEST','hall':16,'slot':1,'placements':[{}]}
        write(i.path,{'draft':draft})
        f=np.zeros((1048,1853,3),np.uint8);self.r.s.capture.screenshot.return_value=f
        i.reader.active_slot.return_value=0;i.reader.selected_slot.return_value=2
        i.reader.edit_layout.return_value=(600,960);i.reader.editing.return_value=True
        with patch('coc_bot.layouts.importer.backup',return_value='saved'),patch('coc_bot.stop.interrupted_sleep',return_value=False):
            self.assertTrue(i.open_survey(16,{'gems':123}))
        state=read(i.path);self.assertEqual(state['draft'],draft)
        self.assertEqual(state['pending']['slot'],2)

    def test_survey_acknowledges_stable_inventory_notice_before_waiting_for_editor(self):
        i=self.r.i;i.open_editor=Mock(return_value=True);i.reader=Mock()
        self.r.s.capture.screenshot.return_value=np.zeros((1048,1853,3),np.uint8)
        i.reader.active_slot.return_value=0;i.reader.selected_slot.return_value=1
        i.reader.edit_layout.return_value=(600,960);i.reader.editing.return_value=True
        i.reader.inventory_notice.side_effect=[(926,670),(926,670),None]
        with patch('coc_bot.layouts.importer.backup',return_value='saved'),patch('coc_bot.stop.interrupted_sleep',return_value=False):
            self.assertTrue(i.open_survey(16,{'gems':123}))
        self.r.s.input.tap.assert_any_call(926,670,jitter=0)
        self.assertEqual(read(i.path)['pending']['original_slot'],0)

    def test_survey_does_not_tap_a_changed_inventory_notice(self):
        i=self.r.i;i.open_editor=Mock(return_value=True);i.reader=Mock()
        self.r.s.capture.screenshot.return_value=np.zeros((1048,1853,3),np.uint8)
        i.reader.active_slot.return_value=0;i.reader.selected_slot.return_value=1
        i.reader.edit_layout.return_value=(600,960)
        i.reader.inventory_notice.side_effect=[(926,670),None]
        with patch('coc_bot.layouts.importer.backup',return_value='saved'),patch('coc_bot.stop.interrupted_sleep',return_value=False):
            self.assertFalse(i.open_survey(16,{'gems':123}))
        self.assertFalse(any(c.args==(926,670) for c in self.r.s.input.tap.call_args_list))
        self.assertTrue(read(i.path)['pending'])


class ResidualTests(unittest.TestCase):
    def test_partial_prefix_is_only_a_trial_not_a_complete_inventory(self):
        from coc_bot.layouts.compatibility import bounded_prefix
        a={'count':4,'point':(100,900)};r=Mock()
        with patch('coc_bot.layouts.compatibility.tray_boxes',return_value=[1,2]),patch('coc_bot.layouts.compatibility.tray_item',side_effect=[a,a,None,None]),patch('coc_bot.layouts.compatibility.same_art',side_effect=[True,False]):
            result=bounded_prefix(r,None,None)
        self.assertEqual(result['count'],4);self.assertTrue(result['probe']);self.assertFalse(result['small']);self.assertFalse(result['complete_count'])

    def test_hidden_inventory_is_not_small(self):
        f=np.zeros((1048,1853,3),np.uint8);i=Mock();i.stop.return_value=False;i.s.capture.screenshot.return_value=f
        a=[{'count':2,'level':15,'wall':False}];b=[{'count':4,'level':15,'wall':False}]
        with patch('coc_bot.layouts.compatibility.excessive_prefix',return_value=None),patch('coc_bot.layouts.compatibility.InventoryPlacer'),patch('coc_bot.layouts.compatibility.page',side_effect=[a,a,b,b]),patch('coc_bot.layouts.compatibility.equal_page',side_effect=[True,True,False]),patch('coc_bot.layouts.compatibility.interrupted_sleep',return_value=False):
            result=assess_remaining(i)
        self.assertFalse(result['small']);self.assertFalse(result['complete_count'])

    def test_full_small_inventory_requires_both_end_observations(self):
        f=np.zeros((1048,1853,3),np.uint8);i=Mock();i.stop.return_value=False;i.s.capture.screenshot.return_value=f
        a=[{'count':2,'level':15,'wall':False}]
        with patch('coc_bot.layouts.compatibility.excessive_prefix',return_value=None),patch('coc_bot.layouts.compatibility.InventoryPlacer'),patch('coc_bot.layouts.compatibility.page',return_value=a),patch('coc_bot.layouts.compatibility.equal_page',return_value=True),patch('coc_bot.layouts.compatibility.interrupted_sleep',return_value=False):
            result=assess_remaining(i)
        self.assertTrue(result['small']);self.assertEqual(result['count'],2)
        i.s.input.tap.assert_not_called()

    def test_known_excess_is_rejected_before_unknown_decoration_cards(self):
        from coc_bot.layouts.compatibility import excessive_prefix
        a={'count':5};b={'count':2};r=Mock()
        with patch('coc_bot.layouts.compatibility.tray_boxes',return_value=[1,2,3]),patch('coc_bot.layouts.compatibility.tray_item',side_effect=[a,a,b,b]) as item,patch('coc_bot.layouts.compatibility.same_art',return_value=True):
            self.assertEqual(excessive_prefix(r,None,None),7)
        self.assertEqual(item.call_count,4)
