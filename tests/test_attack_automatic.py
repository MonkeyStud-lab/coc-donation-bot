from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import numpy as np

from coc_bot.adb.client import AdbStopped
from coc_bot.attack.army import ArmyCard
from coc_bot.attack.automatic import automatic_plan, scan_army
from coc_bot.attack.executor import ExecutionResult
from coc_bot.attack.planned_farmer import run_planned_attack


def card(name='electro_dragon', kind='troop', quantity=11, x=100, stable=True):
    return ArmyCard(name, (x, 850, 130, 180), name, kind, quantity,
                    identity_score=.98, identity_margin=.1, stable=stable)


class AutomaticPlanTests(TestCase):
    def test_generates_current_counts_without_human_confirmation(self):
        cards = [card(), card('rage_spell','spell',5,250),
                 card('flame_flinger','siege',1,400), card('king_skin','hero',1,550)]
        self.assertFalse(any(c.confirmed for c in cards))
        plan = automatic_plan(cards)
        self.assertEqual([s.action for s in plan.steps],
                         ['deploy_line','cast_points','deploy_point','deploy_point','ability'])
        self.assertEqual([s.quantity for s in plan.steps[:2]], [11,5])
        changed = automatic_plan([replace(cards[0],quantity=9),replace(cards[1],quantity=3)])
        self.assertEqual([s.quantity for s in changed.steps], [9,3])
        self.assertEqual(len(changed.steps[1].points),3)

    def test_dragons_only_and_single_rage_are_supported(self):
        self.assertEqual(len(automatic_plan([card()]).steps),1)
        self.assertEqual(automatic_plan([card(),card('rage','spell',1)]).steps[1].points[0].y,.5)

    def test_each_hero_ability_follows_its_own_deployment(self):
        plan=automatic_plan([card()]+[card('hero_'+str(i),'hero',1) for i in range(4)])
        for i in range(4):
            deploy,ability=plan.steps[1+i*2:3+i*2]
            self.assertEqual((deploy.action,ability.action),('deploy_point','ability'))
            self.assertEqual(deploy.unit_id,ability.unit_id)

    def test_unknown_unsupported_and_ambiguous_armies_never_generate_a_plan(self):
        cases = [[], [card(stable=False)], [replace(card(),unit_id=None)],
                 [card(quantity=None)], [card(quantity=0)], [card(quantity=21)],
                 [card('recall_spell','spell',1)], [card('king','hero',1)], [card(),card()],
                 [card(),card('flame_flinger','siege',1),card('battle_blimp','siege',1)],
                 [card(),card('rage','spell',1),card('rage_spell','spell',1)],
                 [card()]+[card('hero_'+str(i),'hero',1) for i in range(5)]]
        for cards in cases:
            with self.subTest(cards=cards), self.assertRaises(ValueError):
                automatic_plan(cards)

    def test_extra_cards_do_not_veto_verified_dragons_or_authorize_extra_taps(self):
        unknown=replace(card(),slot='extra',unit_id=None,kind='unknown',quantity=None,stable=False)
        plan=automatic_plan([unknown,card('barbarian','troop',50),card(),
                             card('recall_spell','spell',5)])
        self.assertEqual([e.unit_id for e in plan.army],['electro_dragon'])
        self.assertEqual([(s.unit_id,s.quantity) for s in plan.steps],[('electro_dragon',11)])


class AutomaticScanTests(TestCase):
    def session(self):
        s = Mock()
        s.client.stop_check = lambda:False
        s.capture.screenshot.return_value = np.zeros((1048,1853,3),np.uint8)
        return s

    def read_pages(self, pages):
        return [page for page in pages for _ in range(2)]

    def test_checks_both_endpoints_without_selecting_or_deploying(self):
        session,catalog = self.session(),Mock()
        cards = [card(),card('rage_spell','spell',5,250)]
        with patch('coc_bot.attack.automatic.BattleFrameGate'), \
                patch('coc_bot.attack.automatic.read_army',side_effect=self.read_pages([cards]*3)):
            army = scan_army(session,catalog)
        self.assertEqual([c.quantity for c in army],[11,5])
        self.assertEqual(session.input.swipe.call_count,2)
        # Both swipes start on a known card, even when the row is very short.
        self.assertEqual([call.args[0] for call in session.input.swipe.call_args_list],[165,315])
        session.input.tap.assert_not_called()

    def test_overlapping_pages_merge_counts_without_adding(self):
        session,catalog = self.session(),Mock()
        left=[card(),card('king','hero',1,250)]
        right=[card('king','hero',1,100),card('rage_spell','spell',5,250)]
        with patch('coc_bot.attack.automatic.BattleFrameGate'), \
                patch('coc_bot.attack.automatic.read_army',side_effect=self.read_pages([left,left,right,right])):
            army = scan_army(session,catalog)
        self.assertEqual({c.unit_id:c.quantity for c in army},
                         {'electro_dragon':11,'king':1,'rage_spell':5})

    def test_count_change_between_pages_is_rejected(self):
        session,catalog = self.session(),Mock()
        left=[card()];right=[card(quantity=10,x=200)]
        with patch('coc_bot.attack.automatic.BattleFrameGate'), \
                patch('coc_bot.attack.automatic.read_army',side_effect=self.read_pages([left,left,right])):
            with self.assertRaisesRegex(ValueError,'changed between pages'):scan_army(session,catalog)
        session.input.tap.assert_not_called()

    def test_ignored_cards_are_not_scroll_anchors_or_inventory(self):
        session,catalog=self.session(),Mock()
        unknown=replace(card(x=50),unit_id=None,kind='unknown',quantity=None)
        cards=[unknown,card(x=250),card('recall_spell','spell',5,500)]
        with patch('coc_bot.attack.automatic.BattleFrameGate'), \
                patch('coc_bot.attack.automatic.read_army',side_effect=self.read_pages([cards]*3)):
            army=scan_army(session,catalog)
        self.assertEqual([c.unit_id for c in army],['electro_dragon'])
        self.assertEqual([c.args[0] for c in session.input.swipe.call_args_list],[315,315])
        session.input.tap.assert_not_called()

    def test_unknown_card_and_inconsistent_frames_are_rejected(self):
        for readings in ([card(),replace(card(),unit_id=None)], [card(),card(quantity=10)]):
            session,catalog=self.session(),Mock()
            with patch('coc_bot.attack.automatic.BattleFrameGate'), \
                    patch('coc_bot.attack.automatic.read_army',side_effect=[[c] for c in readings]):
                with self.assertRaisesRegex(ValueError,'unreadable'):scan_army(session,catalog)
            session.input.swipe.assert_not_called()

    def test_scrolling_is_bounded_when_the_start_never_settles(self):
        session,catalog=self.session(),Mock()
        pages=[[card(x=100+i*20)] for i in range(5)]
        with patch('coc_bot.attack.automatic.BattleFrameGate'), \
                patch('coc_bot.attack.automatic.read_army',side_effect=self.read_pages(pages)):
            with self.assertRaisesRegex(ValueError,'start of the army bar'):scan_army(session,catalog)
        self.assertEqual(session.input.swipe.call_count,4)

    def test_stop_and_screen_change_prevent_further_swipes(self):
        session,catalog=self.session(),Mock()
        stopped=[]
        session.client.stop_check=lambda:bool(stopped)
        def stop(*args):stopped.append(True)
        session.input.swipe.side_effect=stop
        with patch('coc_bot.attack.automatic.BattleFrameGate'), \
                patch('coc_bot.attack.automatic.read_army',return_value=[card()]):
            with self.assertRaises(AdbStopped):scan_army(session,catalog)
        self.assertEqual(session.input.swipe.call_count,1)
        session=self.session()
        with patch('coc_bot.attack.automatic.BattleFrameGate') as gate, \
                patch('coc_bot.attack.automatic.read_army',return_value=[card()]):
            gate.return_value.accept.side_effect=[True,True,False]
            with self.assertRaisesRegex(ValueError,'before army scroll'):scan_army(session,catalog)
        session.input.swipe.assert_not_called()


class AutomaticLifecycleTests(TestCase):
    def farmer(self, root):
        f=Mock()
        f.config=SimpleNamespace(data_dir=Path(root),farm_battle_timeout_seconds=200)
        f.input.client.stop_check=lambda:False
        f._sleep.return_value=False
        f.attack_nav.classifier._clan_chat_anchor_visible.return_value=True
        return f

    def test_runs_without_loading_or_changing_a_saved_routine(self):
        with TemporaryDirectory() as root:
            f=self.farmer(root)
            path=Path(root)/'attack-planner/routine.json';path.parent.mkdir();path.write_text('unrelated saved plan')
            with patch('coc_bot.attack.planned_farmer.load_template') as load, \
                    patch('coc_bot.attack.planned_farmer.remember_camera'), \
                    patch('coc_bot.attack.planned_farmer.restore_camera'), \
                    patch('coc_bot.attack.planned_farmer.survey',return_value={'projection':Mock(),'reference':Mock()}), \
                    patch('coc_bot.attack.planned_farmer.learned_catalog') as catalog, \
                    patch('coc_bot.attack.automatic.scan_army',return_value=[card()]), \
                    patch('coc_bot.attack.planned_farmer.VerifiedExecutor') as executor:
                catalog.return_value.references=[]
                executor.return_value.run.return_value=ExecutionResult(True,'verified',11,123)
                result=run_planned_attack(f,automatic=True)
            self.assertTrue(result.success)
            load.assert_not_called()
            catalog.assert_called_once_with(f.config,use_saved_routine=False)
            self.assertEqual(executor.call_args.args[1].steps[0].quantity,11)
            self.assertEqual(path.read_text(),'unrelated saved plan')
            f.donation_nav.ensure_clan_chat.assert_called_once()

    def test_missing_dragons_recovers_without_deploy_and_advances_interval(self):
        with TemporaryDirectory() as root:
            f=self.farmer(root)
            with patch('coc_bot.attack.planned_farmer.remember_camera'), \
                    patch('coc_bot.attack.planned_farmer.restore_camera') as restore, \
                    patch('coc_bot.attack.planned_farmer.survey',return_value={'projection':Mock(),'reference':Mock()}), \
                    patch('coc_bot.attack.planned_farmer.learned_catalog'), \
                    patch('coc_bot.attack.automatic.scan_army',return_value=[card('recall_spell','spell',1)]), \
                    patch('coc_bot.attack.abort.leave_unstarted_opponent',return_value=True) as abandon, \
                    patch('coc_bot.attack.planned_farmer.VerifiedExecutor') as executor:
                result=run_planned_attack(f,automatic=True)
            self.assertFalse(result.success);self.assertTrue(result.counts_toward_interval)
            self.assertIn('no verified Electro Dragons',result.reason)
            executor.assert_not_called()
            self.assertEqual(restore.call_count,2)
            abandon.assert_called_once()
            f.attack_nav.wait_for_battle_end.assert_not_called()

    def test_stop_during_auto_inventory_sends_no_cleanup_inputs(self):
        with TemporaryDirectory() as root:
            f=self.farmer(root)
            with patch('coc_bot.attack.planned_farmer.remember_camera'), \
                    patch('coc_bot.attack.planned_farmer.restore_camera') as restore, \
                    patch('coc_bot.attack.planned_farmer.survey',return_value={'projection':Mock(),'reference':Mock()}), \
                    patch('coc_bot.attack.planned_farmer.learned_catalog'), \
                    patch('coc_bot.attack.automatic.scan_army',side_effect=AdbStopped('Stopped')):
                result=run_planned_attack(f,automatic=True)
            self.assertEqual(result.reason,'stopped')
            self.assertEqual(restore.call_count,1)
            f.attack_nav.return_home_from_attack.assert_not_called()
