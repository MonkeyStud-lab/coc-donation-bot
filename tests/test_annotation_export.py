import hashlib
import json
from pathlib import Path
import sys
import tempfile
from unittest import TestCase
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from export_reviewed_annotations import export


class AnnotationExportTests(TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/'images').mkdir()
        self.image=self.root/'images/01.png'
        Image.new('RGB',(100,80)).save(self.image)
        self.schema=self.root/'schema.yaml'
        self.schema.write_text('screens: [home]\nclasses:\n  navigation: [btn_open_chat]\n')
        (self.root/'manifest.json').write_text(json.dumps([{'id':1,'image':'01.png',
            'session':'session-a','suggested_screen':'other',
            'sha256':hashlib.sha256(self.image.read_bytes()).hexdigest()}]))
        self.review=[{'id':1,'screen':'home','boxes':[{'label':'btn_open_chat','xywh':[10,8,20,16]}]}]
        self.save()

    def save(self):
        (self.root/'annotations.json').write_text(json.dumps(self.review))

    def test_coordinates_and_review_provenance_are_preserved(self):
        report=export(self.root,self.schema)
        task=json.loads((self.root/'tasks_reviewed.json').read_text())[0]
        value=task['annotations'][0]['result'][1]['value']
        self.assertEqual((value['x'],value['y'],value['width'],value['height']),(10,10,20,20))
        self.assertFalse(task['data']['human_confirmed'])
        self.assertFalse(task['data']['objects_complete'])
        self.assertFalse(task['data']['training_ready'])
        self.assertEqual(report['screen_corrections'],1)

    def test_changed_source_image_is_rejected(self):
        Image.new('RGB',(100,80),'red').save(self.image)
        with self.assertRaisesRegex(ValueError,'Image changed'):
            export(self.root,self.schema)

    def test_invalid_or_outside_image_box_is_rejected(self):
        for bounds in ([90,8,20,16],[10,8,-20,16],[float('nan'),8,20,16]):
            self.review[0]['boxes'][0]['xywh']=bounds
            self.save()
            with self.assertRaisesRegex(ValueError,'Invalid box'):
                export(self.root,self.schema)
