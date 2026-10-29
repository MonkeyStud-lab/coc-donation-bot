from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock
import time
import cv2
from coc_bot.builder_base.army import editor,editor_close,permitted,repair
from coc_bot.builder_base.vision import BuilderReader


class BuilderArmyTests(TestCase):
    def test_native_missing_camp_and_complete_army_are_distinct(self):
        root=Path(__file__).parent/'fixtures/builder_base';reader=BuilderReader()
        before=cv2.imread(str(root/'army-one-camp-empty.png'))
        after=cv2.imread(str(root/'army-two-camps-ready.png'))
        self.assertEqual(editor(reader,before),{'family':'raged_barbarian','groups':1,'units':3,'missing':[1],'ready':False})
        self.assertEqual(editor(reader,after),{'family':'raged_barbarian','groups':2,'units':6,'missing':[],'ready':True})
        bad=after.copy();bad[350:425,291:394]=0
        self.assertIsNone(editor(reader,bad))
        bad=after.copy();bad[306:334,359:399]=0
        self.assertIsNone(editor(reader,bad))
        self.assertIsNone(editor_close(reader,(after*.5).astype('uint8')))

    def test_repair_requires_recent_owned_native_hall_and_resource_demand(self):
        r=SimpleNamespace(config=SimpleNamespace(builder_base_progression_enabled=True,account_tag='#PYLQG'),record={})
        proof={'account':'#PYLQG','hall':2,'hall_verified':True,'inventory_at':time.time(),'attack':True}
        r.record['resource_demand']=proof;self.assertTrue(permitted(r))
        for change in ({'account':'#OTHER'},{'hall':3},{'hall_verified':False},{'attack':False},
                       {'inventory_at':time.time()-181},{'inventory_at':float('nan')},{'inventory_at':None}):
            r.record['resource_demand']=proof|change
            self.assertFalse(permitted(r))
            r.tap=Mock();r.frame=Mock()
            self.assertFalse(repair(r));r.tap.assert_not_called();r.frame.assert_not_called()
