"""Visit sequencing must not duplicate spending or require attacks to collect."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from coc_bot.builder_base.runner import BuilderBaseRunner
from coc_bot.builder_base.upgrades import BuilderUpgradeRunner
from coc_bot.upgrades.vision import Candidate


class VisitTests(unittest.TestCase):
    def test_orphaned_builder_payment_blocks_handoff_and_never_repeats_spending(self):
        from coc_bot.accounts.store import write
        from coc_bot.builder_base.runner import pending
        write(self.config.data_dir/'builder_base/upgrades.json',{'pending':{'kind':'construction'}})
        self.assertTrue(pending(self.config))
        self.runner.reader.home=MagicMock(return_value=True)
        with patch('coc_bot.builder_base.progression.BuilderProgressionRunner') as recovery:
            recovery.return_value.state.return_value={'pending':{'kind':'construction'}}
            with self.assertRaisesRegex(ValueError,'receipt verification'):self.runner.run()
            recovery.return_value.run.assert_called_once_with('buildings',execute=False)
        self.runner.enter.assert_not_called();self.runner.attack.assert_not_called();self.runner.finish.assert_not_called()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = SimpleNamespace(
            data_dir=Path(self.temp.name), dry_run=False,
            builder_base_collect_resources=True,
            builder_base_attacks_enabled=True,
            builder_base_research_enabled=True,
            builder_base_upgrades_enabled=True,
            builder_base_elixir_reserve=100_000,
            builder_base_gold_reserve=100_000,
            builder_base_builders_reserved=0,
            upgrade_excluded_names='',
        )
        self.runner = BuilderBaseRunner(self.config, MagicMock(), MagicMock(), MagicMock(), MagicMock())
        self.runner.enter = MagicMock()
        self.runner.finish = MagicMock()
        self.runner.phase = MagicMock()
        self.runner.attack = MagicMock(return_value={'status': 'returned'})
        self.runner.resource_demand=MagicMock(return_value={
            'builders':(1,2),'lab':(0,1),'balances':{'gold':0,'elixir':0},
            'capacities':{'gold':1000000,'elixir':1000000},'targets':[
                {'kind':'buildings','name':'Cannon','cost':200000,'currency':'gold','supported':True}]})

    def run_visit(self, results):
        with patch('coc_bot.builder_base.resources.ResourceCollector') as collect, \
                patch('coc_bot.builder_base.runner.BuilderUpgradeRunner') as upgrades:
            upgrades.return_value.run.side_effect = iter(results+[{'status':'nothing_eligible'}]*5)
            collect.return_value.run.return_value = {'status': 'completed'}
            result = self.runner.run()
            return result, collect.return_value.run.call_count, upgrades.return_value.run.call_args_list

    def test_collection_only_visit(self):
        self.config.builder_base_attacks_enabled = False
        self.config.builder_base_research_enabled = False
        self.config.builder_base_upgrades_enabled = False
        report, collections, upgrades = self.run_visit([])
        self.assertEqual(collections, 1)
        self.assertEqual(upgrades, [])
        self.assertNotIn('attack', report)
        self.runner.attack.assert_not_called()
        self.runner.finish.assert_called_once()

    def test_research_uncertainty_blocks_other_spending(self):
        for status in ('needs_review', 'changed'):
            with self.subTest(status=status):
                report, collections, calls = self.run_visit([{'status': status}])
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0].args, ('research',))
                self.assertEqual(collections, 1)

    def test_confirmed_research_can_be_followed_by_free_builder_work(self):
        _,_,calls=self.run_visit([{'status':'started'},{'status':'started'},{'status':'nothing_eligible'}])
        self.assertEqual([c.args[0] for c in calls],['research','buildings','buildings'])

    def test_uncertain_second_building_stops_the_batch(self):
        result,_,calls=self.run_visit([{'status':'nothing_eligible'},{'status':'started'},{'status':'needs_review'}])
        self.assertEqual(len(calls),3)
        self.assertEqual(result['upgrade']['status'],'needs_review')
        self.runner.attack.assert_not_called()

    def test_busy_slots_skip_attack_and_duplicate_collection(self):
        self.runner.resource_demand.return_value={'builders':(0,2),'lab':(0,1)}
        report,collections,_=self.run_visit([{'status':'nothing_eligible'}]*2)
        self.assertEqual(report['attack']['status'],'not_needed')
        self.runner.attack.assert_not_called();self.assertEqual(collections,1)

    def test_busy_research_falls_back_to_building_once(self):
        _, _, calls = self.run_visit([{'status': 'nothing_eligible'}, {'status': 'started'}])
        self.assertEqual([c.args[0] for c in calls], ['research', 'buildings','buildings'])

    def test_new_rewards_allow_recheck_only_if_nothing_started(self):
        _, _, calls = self.run_visit([{'status': 'nothing_eligible'}]*3 + [{'status': 'started'},{'status':'nothing_eligible'}])
        self.assertEqual([c.args[0] for c in calls], ['research', 'buildings', 'research', 'buildings','buildings'])

    def test_pending_visit_recovers_before_new_work(self):
        self.runner.record = {'phase': 'collecting_resources'}
        self.runner.recover = MagicMock()
        self.assertEqual(self.runner.run(), {'status': 'recovered'})
        self.runner.recover.assert_called_once()
        self.runner.enter.assert_not_called()
        self.runner.attack.assert_not_called()

    def test_gem_change_checkpoint_does_not_clear_itself_on_restart(self):
        self.runner.record = {'phase': 'collection_needs_review'}
        with self.assertRaisesRegex(ValueError, 'gem balance'):
            self.runner.recover()
        self.runner.capture.screenshot.assert_not_called()
        self.runner.finish.assert_not_called()

    def test_research_reserve_busy_slot_and_unknown_units(self):
        runner = BuilderUpgradeRunner.__new__(BuilderUpgradeRunner)
        runner.config = self.config
        item = Candidate('Night Witch', 2_500_000, 'elixir', (1, 2))
        self.assertIsNone(runner.eligibility('research', item, {'elixir': 2_600_000}, (1, 1)))
        for balance, availability in ((2_599_999, (1, 1)), (3_000_000, (0, 1)), (None, (1, 1))):
            self.assertIsNotNone(runner.eligibility('research', item, {'elixir': balance}, availability))
        for name, currency in (('Baby Dragon', 'elixir'), ('Night Witch', 'gems')):
            candidate = Candidate(name, 100, currency, (1, 2))
            self.assertIsNotNone(runner.eligibility('research', candidate, {currency: 1000}, (1, 1)))

    def test_unrecognized_unpaid_progression_research_does_not_starve_construction(self):
        self.config.builder_base_progression_enabled=True;self.config.builder_base_attacks_enabled=False
        with patch('coc_bot.builder_base.resources.ResourceCollector'),\
             patch('coc_bot.builder_base.progression.BuilderProgressionRunner') as upgrades:
            upgrades.return_value.state.return_value={}
            upgrades.return_value.run.side_effect=[{'status':'nothing_eligible'},
                {'status':'blocked','message':'Unrecognized research confirmation'},
                {'status':'started'},{'status':'nothing_eligible'}]
            result=self.runner.run()
            self.assertEqual([v.args[0] for v in upgrades.return_value.run.call_args_list],
                             ['buildings','research','buildings','buildings'])
            self.assertEqual(result['upgrade']['status'],'started')
            self.assertEqual(len(result['upgrade']['paused_operations']),1)


if __name__ == '__main__':
    unittest.main()
