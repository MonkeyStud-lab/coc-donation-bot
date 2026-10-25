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
            upgrade_excluded_names='',
        )
        self.runner = BuilderBaseRunner(self.config, MagicMock(), MagicMock(), MagicMock(), MagicMock())
        self.runner.enter = MagicMock()
        self.runner.finish = MagicMock()
        self.runner.phase = MagicMock()
        self.runner.attack = MagicMock(return_value={'status': 'returned'})

    def run_visit(self, results):
        with patch('coc_bot.builder_base.resources.ResourceCollector') as collect, \
                patch('coc_bot.builder_base.runner.BuilderUpgradeRunner') as upgrades:
            upgrades.return_value.run.side_effect = results
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

    def test_research_success_or_uncertainty_blocks_other_spending(self):
        for status in ('started', 'needs_review', 'changed'):
            with self.subTest(status=status):
                report, collections, calls = self.run_visit([{'status': status}])
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0].args, ('research',))
                self.assertEqual(collections, 2)

    def test_busy_research_falls_back_to_building_once(self):
        _, _, calls = self.run_visit([{'status': 'nothing_eligible'}, {'status': 'started'}])
        self.assertEqual([c.args[0] for c in calls], ['research', 'buildings'])

    def test_new_rewards_allow_recheck_only_if_nothing_started(self):
        _, _, calls = self.run_visit([{'status': 'nothing_eligible'}]*3 + [{'status': 'started'}])
        self.assertEqual([c.args[0] for c in calls], ['research', 'buildings', 'research', 'buildings'])

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


if __name__ == '__main__':
    unittest.main()
