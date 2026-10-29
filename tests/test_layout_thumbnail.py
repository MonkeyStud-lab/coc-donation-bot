import unittest
import numpy as np
from coc_bot.layouts.importer import same_saved_layout

class SavedLayoutTests(unittest.TestCase):
    def setUp(self):
        self.art=np.random.default_rng(12).integers(20,230,(32,64),dtype=np.uint8)
    def test_native_bottom_badge_changes_do_not_change_map_identity(self):
        changed=self.art.copy();changed[24:,40:]=255
        self.assertTrue(same_saved_layout(changed,self.art))
    def test_changed_map_is_rejected(self):
        changed=self.art.copy();changed[8:16,20:40]=255
        self.assertFalse(same_saved_layout(changed,self.art))
    def test_invalid_or_flat_map_is_rejected(self):
        for value in (None,np.zeros((32,64)),np.full((32,64),np.nan),np.zeros((31,64))):
            self.assertFalse(same_saved_layout(value,self.art))

    def test_new_obstacle_notice_invalidates_clearance_and_retains_draft(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import Mock,patch
        from coc_bot.accounts.store import read,write
        from coc_bot.layouts.importer import LayoutImporter
        with tempfile.TemporaryDirectory() as folder:
            session=SimpleNamespace(config=SimpleNamespace(data_dir=Path(folder),account_tag='#PYLQG',account_town_hall=18),capture=Mock(),input=Mock())
            session.capture.screenshot.return_value=np.zeros((1048,1853,3),np.uint8)
            importer=LayoutImporter(session);importer.reader=Mock();importer.open_editor=Mock(return_value=True)
            importer.cancel_obstacle_survey=Mock(return_value=True)
            draft={'account':'#PYLQG','hall':18,'slot':2,'original_slot':0,'backup':'backup','thumbnail':self.art.tolist()}
            write(importer.path,{'draft':draft,'automatic':{'stage':'placing','cleared_at':123}})
            importer.reader.active_slot.return_value=0;importer.reader.thumbnail.return_value=self.art.tolist()
            importer.reader.edit_layout.return_value=(590,960)
            importer.reader.inventory_notice.return_value=(926,670)
            with patch('coc_bot.stop.interrupted_sleep',return_value=False):
                self.assertFalse(importer.resume_draft())
            state=read(importer.path)
            self.assertEqual(state['automatic']['stage'],'clearing')
            self.assertEqual(state['automatic']['cleared_at'],0)
            self.assertEqual(state['draft'],draft)
            importer.cancel_obstacle_survey.assert_called_once()
