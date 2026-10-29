from pathlib import Path
import unittest

import cv2
import numpy as np

from coc_bot.layouts.terrain import register, project


class TerrainTests(unittest.TestCase):
    def test_native_empty_thumbnail_matches_survey_after_native_camera_change(self):
        root=Path(__file__).parent/'fixtures/layouts'
        reference=cv2.imread(str(root/'empty-terrain.png'))
        frame=cv2.imread(str(root/'terrain-survey.png'))
        result=register(reference,frame)
        self.assertTrue(result['registered'],result)
        self.assertGreater(result['inliers'],50)
        self.assertLess(result['error_p95'],2)
        self.assertFalse(result['tile_grid_verified'])
        expected=np.array([[3.102,0,38],[0,3.102,-127.16]])
        self.assertTrue(np.allclose(result['transform'],expected,atol=.4))
        points=project(result,[[100,100]])
        self.assertTrue(np.allclose(points,[[348.2,183.04]],atol=.5))

    def test_controls_alone_blank_and_stopped_frames_cannot_establish_terrain(self):
        ref=np.zeros((385,571,3),np.uint8);frame=np.zeros((1048,1853,3),np.uint8)
        for source,screen in ((ref,frame),(None,frame),(ref,frame[:5])):
            self.assertFalse(register(source,screen)['registered'])
        self.assertEqual(register(ref,frame,lambda:True)['reason'],'Stopped')
        with self.assertRaises(ValueError):project({'registered':False},[[1,2]])

    def test_nonfinite_projection_cannot_produce_coordinates(self):
        with self.assertRaises(ValueError):
            project({'registered':True,'transform':[[1,0,0],[0,1,0]]},[[np.nan,0]])


if __name__=='__main__':unittest.main()
