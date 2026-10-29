from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import Mock,patch
import numpy as np
import cv2

from coc_bot.accounts.store import read,write
from coc_bot.layouts.obstacles import reconcile,remove_selected,home_resources


class ObstacleRecoveryTests(unittest.TestCase):
    def test_full_clearance_does_not_truncate_a_dense_obstacle_view(self):
        from coc_bot.layouts.obstacles import candidates
        hsv=np.full((1048,1853,3),(35,150,180),np.uint8)
        f=cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR)
        for x in range(500,1300,100):
            for y in range(200,700,100):cv2.rectangle(f,(x,y),(x+15,y+15),(0,0,160),-1)
        polygon=[(400,100),(1400,100),(1400,800),(400,800)]
        self.assertEqual(len(candidates(f,[polygon],lower_map=True)),30)
        self.assertEqual(len(candidates(f,[polygon],lower_map=True,limit=None)),40)

    def test_border_tree_exclusion_needs_native_selection_and_outside_anchor(self):
        from coc_bot.layouts.obstacles import outside_selected_tree
        from coc_bot.layouts.importer import LayoutReader
        f=cv2.imread(str(Path(__file__).parent/'fixtures/layouts/selected-border-tree.png'))
        r=LayoutReader();target=(587,763)
        with patch('coc_bot.layouts.grid.camera',return_value={'registered':True}),patch('coc_bot.layouts.grid.tiles',return_value=np.array([[20,46]])) as project:
            self.assertTrue(outside_selected_tree(r,f,target))
            project.return_value=np.array([[20,43]])
            self.assertFalse(outside_selected_tree(r,f,target))
            project.return_value=np.array([[20,46]])
            unknown=f.copy();unknown[740:814,530:585]=0
            self.assertFalse(outside_selected_tree(r,unknown,target))
            no_remove=f.copy();no_remove[730:810,830:1020]=0
            self.assertFalse(outside_selected_tree(r,no_remove,target))

    def test_beige_seasonal_price_uses_strict_digits_and_rejects_conflicts(self):
        from coc_bot.layouts.obstacles import selected
        from coc_bot.layouts.importer import LayoutReader
        f=cv2.imread(str(Path(__file__).parent/'fixtures/layouts/seasonal-stump-price.png'))
        r=LayoutReader()
        with patch('coc_bot.layouts.obstacles.obstacle_name',return_value='Curious Stump'):
            item=selected(r,f,(754,435),seasonal=True)
            self.assertIsNotNone(item)
            self.assertEqual((item['cost'],item['currency']),(2026,'elixir'))
            with patch('coc_bot.layouts.obstacles.resource_amount',return_value=202):
                self.assertIsNone(selected(r,f,(754,435),seasonal=True))
            missing=f.copy();missing[650:688,840:1010]=0
            self.assertIsNone(selected(r,missing,(754,435),seasonal=True))

    def test_home_identity_does_not_require_builder_count_ocr(self):
        f=cv2.imread(str(Path(__file__).parent/'fixtures/layouts/home-helper-builder.png'))
        # The helper splits the HUD into two counters. None is required to
        # identify Home or authorize an otherwise verified resource removal.
        hidden=f.copy();hidden[792:831,1640:1844]=0
        with patch('coc_bot.layouts.obstacles.home_gems',return_value=20),\
             patch('coc_bot.layouts.obstacles.balance_amount',return_value=1000),\
             patch('coc_bot.layouts.obstacles.home_build_control_visible',return_value=True),\
             patch('coc_bot.progression.space.free_builders',side_effect=AssertionError('Count is irrelevant')):
            self.assertIsNotNone(home_resources(f))
            self.assertIsNotNone(home_resources(hidden))
            missing=hidden.copy();missing[745:793,1650:1720]=0
            self.assertIsNone(home_resources(missing))
            self.assertIsNone(home_resources(f,lambda:True))

    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name)
        self.session=SimpleNamespace(config=SimpleNamespace(data_dir=self.root,account_tag='#PYLQG'),capture=Mock(),input=Mock())
        self.importer=SimpleNamespace(s=self.session,path=self.root/'layouts/state.json',stop=lambda:False,reader=Mock(),close=Mock())
        self.importer.reader.active_slot.return_value=None
        self.payment={'kind':'obstacle','name':'Tree','currency':'elixir','cost':100,
                      'balance_before':1000,'gems_before':20,'operation':'unique','phase':'confirming'}
        self.owner={'account':'#PYLQG','payment':self.payment,'original_slot':0,'slot':1}
        write(self.importer.path,{'last_survey':self.owner})
        write(self.root/'upgrades/state.json',{'pending':self.payment})

    def test_recovery_at_home_does_not_require_or_tap_a_nonexistent_close_button(self):
        proof={'gems':20,'balances':{'gold':500,'elixir':900},'builders':[0,2]}
        with patch('coc_bot.layouts.obstacles.home_resources',return_value=proof),\
             patch('coc_bot.accounts.navigation.verify_session') as identity:
            result=reconcile(self.importer)
        self.assertEqual(result['status'],'making_room')
        self.importer.close.assert_not_called();identity.assert_called_once()
        self.session.input.tap.assert_not_called()
        self.assertNotIn('pending',read(self.root/'upgrades/state.json'))
        self.assertNotIn('payment',read(self.importer.path)['last_survey'])

    def test_crash_between_receipt_writes_cannot_send_another_payment(self):
        write(self.root/'upgrades/state.json',{'last_completed':self.payment|{'phase':'confirmed'}})
        self.assertEqual(reconcile(self.importer)['status'],'making_room')
        self.session.capture.screenshot.assert_not_called();self.session.input.tap.assert_not_called()
        self.assertNotIn('payment',read(self.importer.path)['last_survey'])

    def test_foreign_owner_and_missing_receipts_remain_blocked(self):
        write(self.importer.path,{'last_survey':self.owner|{'account':'#OTHER'}})
        self.assertEqual(reconcile(self.importer)['status'],'needs_review')
        self.session.capture.screenshot.assert_not_called()
        write(self.importer.path,{'last_survey':self.owner})
        write(self.root/'upgrades/state.json',{'pending':self.payment|{'operation':'different'}})
        self.assertEqual(reconcile(self.importer)['status'],'needs_review')
        self.session.input.tap.assert_not_called()

    def test_gem_loss_never_clears_an_uncertain_payment(self):
        proof={'gems':19,'balances':{'gold':500,'elixir':900},'builders':[0,2]}
        with patch('coc_bot.layouts.obstacles.home_resources',return_value=proof),\
             patch('coc_bot.accounts.navigation.verify_session'):
            self.assertEqual(reconcile(self.importer)['status'],'needs_review')
        self.assertEqual(read(self.root/'upgrades/state.json')['pending'],self.payment)

    def test_reward_can_mask_deduction_only_with_matching_native_progress_evidence(self):
        proof={'gems':21,'balances':{'gold':500,'elixir':1500},'builders':[0,2]}
        effect={'account':'#PYLQG','operation':'unique','kind':'native_removal_in_progress',
                'cost':100,'currency':'elixir'}
        with patch('coc_bot.layouts.obstacles.home_resources',return_value=proof),\
             patch('coc_bot.accounts.navigation.verify_session'):
            self.assertEqual(reconcile(self.importer)['status'],'needs_review')
            write(self.root/'layouts/removal-proof.json',effect|{'operation':'old'})
            self.assertEqual(reconcile(self.importer)['status'],'needs_review')
            write(self.root/'layouts/removal-proof.json',effect)
            self.assertEqual(reconcile(self.importer)['status'],'making_room')
        self.session.input.tap.assert_not_called()

    def test_free_builders_do_not_prove_removal_finished(self):
        proof={'gems':21,'balances':{'gold':500,'elixir':900},'builders':[2,2]}
        with patch('coc_bot.layouts.obstacles.home_resources',return_value=proof),\
             patch('coc_bot.accounts.navigation.verify_session'):
            self.assertEqual(reconcile(self.importer)['status'],'making_room')
        self.assertNotIn('finished_at',read(self.root/'upgrades/state.json')['last_completed'])
        self.session.input.tap.assert_not_called()

    def test_matching_native_completion_still_shortens_the_settlement_guard(self):
        proof={'gems':21,'balances':{'gold':500,'elixir':900},'builders':[0,2]}
        effect={'account':'#PYLQG','operation':'unique','kind':'native_removal_in_progress',
                'cost':100,'currency':'elixir','finished_at':1234}
        write(self.root/'layouts/removal-proof.json',effect)
        with patch('coc_bot.layouts.obstacles.home_resources',return_value=proof),\
             patch('coc_bot.accounts.navigation.verify_session'):
            self.assertEqual(reconcile(self.importer)['status'],'making_room')
        self.assertEqual(read(self.root/'upgrades/state.json')['last_completed']['finished_at'],1234)

    def test_verified_resource_removal_can_start_with_all_builders_busy_or_reserved(self):
        c=self.session.config
        c.progression_clear_obstacles=True;c.progression_clear_seasonal_obstacles=True
        c.upgrade_builders_reserved=6;c.upgrade_gold_reserve=0;c.upgrade_elixir_reserve=50
        proof={'at':time.time(),'gems':20,'balances':{'gold':500,'elixir':1000},'builders':[0,6]}
        pending={'account':c.account_tag,'phase':'surveying_obstacles','original_slot':0,'slot':1,
                 'home_resources':proof,'survey_collected_at':time.time(),
                 'footprint_source':'registered_default_build_zone_v1',
                 'blocked_footprints':[[[100,100],[500,100],[500,500],[100,500]]]}
        write(self.importer.path,{'pending':pending});write(self.root/'upgrades/state.json',{})
        self.session.capture.screenshot.return_value=np.zeros((1048,1853,3),np.uint8)
        item={'name':'Tree','cost':100,'currency':'elixir','point':(926,828)}
        with patch('coc_bot.layouts.obstacles.selected',return_value=item),\
             patch('coc_bot.layouts.obstacles.interrupted_sleep',return_value=False),\
             patch('coc_bot.layouts.obstacles.removal_started',return_value=False),\
             patch('coc_bot.layouts.obstacles.cv2.imwrite'),\
             patch('coc_bot.layouts.obstacles.reconcile',return_value={'status':'making_room'}):
            self.assertEqual(remove_selected(self.importer,(300,300))['status'],'making_room')
        self.session.input.tap.assert_called_once_with(926,828,jitter=0)
        payment=read(self.root/'upgrades/state.json')['pending']
        self.assertEqual(payment['cost'],100);self.assertEqual(payment['gems_before'],20)
        self.assertEqual(read(self.importer.path)['pending']['payment'],payment)


if __name__=='__main__':unittest.main()
