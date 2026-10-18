from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import os

from coc_bot.runtime.screenshot_retention import RetentionPolicy, prune_attack_diagnostics


class RetentionTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.now=2000000

    def group(self,index,*,family='attack-surveys',at=1):
        ident=f'{index:032x}'
        if family=='attack-executions':
            folder=self.root/'debug'/family; folder.mkdir(parents=True,exist_ok=True)
            paths=[folder/(ident+'.jsonl'),folder/(ident+'.before.png'),folder/(ident+'.after.png')]
        else:
            folder=self.root/'debug'/family/ident;folder.mkdir(parents=True,exist_ok=True)
            paths=[folder/'reference.png',folder/'view-0.png',folder/'view-0.json']
        for path in paths:
            path.write_bytes(b'evidence'*10); os.utime(path,(at,at))
        return paths

    def test_age_prunes_whole_groups_but_keeps_newest_three_per_family(self):
        for family in ('attack-surveys','attack-executions'):
            for i in range(5): self.group(i,family=family,at=i+1)
        result=prune_attack_diagnostics(self.root,now=self.now)
        self.assertEqual(result['removed_groups'],4)
        self.assertEqual(result['remaining_groups'],6)
        self.assertEqual(len(list((self.root/'debug/attack-executions').glob('*.jsonl'))),3)

    def test_size_and_count_prune_recent_oldest_first(self):
        paths=[self.group(i,at=self.now+i) for i in range(5)]
        result=prune_attack_diagnostics(self.root,now=self.now,
            policy=RetentionPolicy(max_bytes=800,max_groups=3))
        self.assertEqual(result['removed_groups'],2)
        self.assertFalse(paths[0][0].exists());self.assertTrue(paths[4][0].exists())

    def test_pending_marker_preserves_even_old_evidence(self):
        for i in range(5):self.group(i)
        marker=self.root/'attack-planner/attack-pending.json';marker.parent.mkdir();marker.write_text('corrupt')
        self.assertTrue(prune_attack_diagnostics(self.root,now=self.now)['skipped_pending'])
        self.assertEqual(len(list((self.root/'debug/attack-surveys').iterdir())),5)

    def test_training_backups_calibration_and_unknown_reports_are_untouched(self):
        protected=['calibrated.yaml','templates/ui/home.png','collection/a.png','labelstudio/a.png',
                   'update_backups/a.zip','attack-planner/camera-before.png','debug/attack-observations/a.png']
        for name in protected:
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'keep')
        paths=self.group(0);(paths[0].parent/'human-review.txt').write_text('keep')
        prune_attack_diagnostics(self.root,now=self.now,policy=RetentionPolicy(keep_recent=0))
        self.assertTrue(all((self.root/name).read_bytes()==b'keep' for name in protected))
        self.assertTrue(paths[0].exists())

    def test_dry_run_never_deletes_and_errors_are_nonfatal(self):
        for i in range(5):self.group(i)
        result=prune_attack_diagnostics(self.root,now=self.now,dry_run=True)
        self.assertEqual(result['removed_groups'],2)
        self.assertEqual(len(list((self.root/'debug/attack-surveys').iterdir())),5)
        with patch('pathlib.Path.unlink',side_effect=PermissionError('busy')):
            result=prune_attack_diagnostics(self.root,now=self.now)
        self.assertIn('error',result)

    def test_symlink_family_cannot_delete_outside_debug(self):
        outside=self.root/'collection';outside.mkdir();(outside/'data.png').write_bytes(b'keep')
        debug=self.root/'debug';debug.mkdir()
        try:(debug/'attack-surveys').symlink_to(outside,target_is_directory=True)
        except OSError:self.skipTest('symlinks not permitted')
        prune_attack_diagnostics(self.root,policy=RetentionPolicy(keep_recent=0),now=self.now)
        self.assertEqual((outside/'data.png').read_bytes(),b'keep')
