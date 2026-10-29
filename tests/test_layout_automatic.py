from pathlib import Path
from types import SimpleNamespace
import tempfile
import shutil
import unittest
from unittest.mock import Mock,patch
import cv2
import numpy as np
from coc_bot.accounts.store import read,write
from coc_bot.layouts.grid import camera,zone,pixels,tiles,outline,safe_preview,reserved_tiles
from coc_bot.layouts.obstacles import candidates,remove_selected
from coc_bot.layouts.runner import LayoutRunner,dirty
from coc_bot.layouts.placement import InventoryPlacer
from coc_bot.layouts.importer import LayoutReader

FIXTURES=Path(__file__).parent/'fixtures/layouts'


class GridTests(unittest.TestCase):
    def test_native_six_suffix_is_not_ocr_extra_letter(self):
        from coc_bot.layouts.placement import tray_item,inventory_level
        from coc_bot.upgrades.vision import crop
        f=cv2.imread(str(FIXTURES/'inventory-level-six.png'));r=LayoutReader()
        r.white_text=Mock(return_value='Level 6G')
        item=tray_item(r,f)
        self.assertEqual((item['level'],item['count']),(6,15))
        label=crop(f,(.009,.945,.099,.981)).copy()
        label[:,105:]=0
        self.assertIsNone(inventory_level(r,label))
        r.white_text=Mock(return_value='Unrelated 6G')
        self.assertIsNone(tray_item(r,f))

    @unittest.skipUnless(shutil.which('tesseract'),'Needs the server OCR runtime')
    def test_post_wall_stack_native_receipt_reads_next_card(self):
        from coc_bot.layouts.placement import tray_item
        f=cv2.imread(str(FIXTURES/'inventory-level-six.png'))
        item=tray_item(LayoutReader(),f)
        self.assertEqual((item['level'],item['count']),(6,15))

    def test_idle_editor_instruction_is_positive_selection_proof(self):
        r=LayoutReader();f=cv2.imread(str(FIXTURES/'empty-survey-th12.png'))
        self.assertTrue(r.idle_editor(f))
        for name in ('cake-selected.png','wall-green-zoomed-out.png','lower-build-zone-trees.png'):
            self.assertFalse(r.idle_editor(cv2.imread(str(FIXTURES/name))),name)
        f[730:824,500:1350]=0
        self.assertFalse(r.idle_editor(f))

    def test_lower_trees_are_visible_only_to_the_gated_full_canvas_survey(self):
        f=cv2.imread(str(FIXTURES/'lower-build-zone-trees.png'));m=camera(f)
        old=candidates(f,[zone(m,0).tolist()])
        full=candidates(f,[zone(m,0).tolist()],lower_map=True)
        self.assertFalse(any(np.linalg.norm(np.array(p)-[1100,620])<20 for p in old))
        self.assertTrue(any(np.linalg.norm(np.array(p)-[1100,620])<20 for p in full),full)
        self.assertTrue(any(np.linalg.norm(np.array(p)-[980,718])<25 for p in full),full)

    def test_a_known_unleveled_card_needs_matching_art_and_a_blank_caption(self):
        from coc_bot.layouts.placement import tray_item,tray_offsets
        f=cv2.imread(str(FIXTURES/'inventory-unleveled-hut.png'));r=LayoutReader()
        r.white_text=Mock(return_value='')
        item=tray_item(r,f)
        self.assertIsNotNone(item);self.assertIsNone(item['level']);self.assertEqual(item['count'],1)
        o=tray_offsets(f)[0]
        unknown=f.copy();unknown[910:989,o+13:o+184]=0
        self.assertIsNone(tray_item(r,unknown))
        caption=f.copy();cv2.putText(caption,'Il',(o+45,1010),cv2.FONT_HERSHEY_SIMPLEX,.8,(255,255,255),2)
        self.assertIsNone(tray_item(r,caption))

    def test_full_footprint_ground_ranking_prefers_room_over_a_thin_edge_strip(self):
        from coc_bot.layouts.placement import rank_ground_targets
        f=np.full((1048,1853,3),(65,180,140),np.uint8)
        m={'registered':True,'transform':[[3.4,0,0],[0,3.4,-150]]}
        edge=(1.5,32.5);room=(8.5,30.5)
        corners=pixels(m,[(0,31),(3,31),(3,34),(0,34)])
        cv2.fillConvexPoly(f,np.rint(corners).astype(int),(80,70,65))
        x,y=np.rint(pixels(m,[edge])[0]).astype(int)
        f[y-9:y+10,x-9:x+10]=(65,180,140)
        self.assertEqual(rank_ground_targets(f,m,[edge,room],3),[room,edge])
        # Ranking alone neither rejects an edge nor invents a placement.
        self.assertEqual(rank_ground_targets(f,m,[edge],3),[edge])

    def test_storage_artwork_glints_do_not_invent_an_inventory_stack(self):
        from coc_bot.layouts.placement import tray_item
        f=cv2.imread(str(FIXTURES/'inventory-storage-glare.png'));r=LayoutReader()
        r.white_text=Mock(return_value='Level 13')
        item=tray_item(r,f)
        self.assertIsNotNone(item)
        self.assertEqual((item['level'],item['count']),(13,1))

    def test_native_level_eleven_is_verified_from_glyphs_when_ocr_reads_letters(self):
        from coc_bot.layouts.placement import tray_item
        f=cv2.imread(str(FIXTURES/'inventory-level-eleven.png'));r=LayoutReader()
        r.white_text=Mock(return_value='Level Il')
        item=tray_item(r,f)
        self.assertEqual((item['level'],item['count']),(11,1))
        # OCR's letters alone cannot supply a level when its digits are absent.
        from coc_bot.layouts.placement import inventory_level,tray_offsets
        from coc_bot.upgrades.vision import crop
        o=tray_offsets(f)[0];normalized=f.copy()
        normalized[838:,:f.shape[1]-o]=f[838:,o:];normalized[838:,f.shape[1]-o:]=0
        label=crop(normalized,(.009,.945,.099,.981)).copy()
        label[:,round(label.shape[1]*.62):]=0
        self.assertIsNone(inventory_level(r,label))
        r.white_text=Mock(return_value='Unrelated Il')
        self.assertIsNone(tray_item(r,f))
    def test_centered_and_scrolled_cards_use_their_actual_native_position(self):
        from coc_bot.layouts.placement import tray_start,tray_offsets
        f=cv2.imread(str(FIXTURES/'inventory-scrolled.png'))
        self.assertTrue(tray_start(f));self.assertTrue(20<=tray_offsets(f)[0]<=35)
        f=cv2.imread(str(FIXTURES/'inventory-centered.png'))
        self.assertTrue(tray_start(f));self.assertTrue(40<=tray_offsets(f)[0]<=55)
        for name in ('inventory-wall-14.png','large-red-footprint.png'):
            f=cv2.imread(str(FIXTURES/name))
            self.assertTrue(tray_start(f))
    @unittest.skipUnless(shutil.which('tesseract'),'Needs the server OCR runtime')
    def test_multiple_native_inventory_cards_keep_their_own_level_and_quantity(self):
        from coc_bot.layouts.placement import tray_offsets,tray_item
        f=cv2.imread(str(FIXTURES/'large-red-footprint.png'));r=LayoutReader()
        values=[tray_item(r,f,i) for i in range(len(tray_offsets(f)))]
        self.assertEqual([v['level'] for v in values],[3,3,5,10,5,10,11,3,8])
        self.assertEqual([v['count'] for v in values],[1,1,1,1,1,2,1,1,1])
        self.assertEqual([v['slot'] for v in values],list(range(9)))
        f=cv2.imread(str(FIXTURES/'inventory-centered.png'))
        item=tray_item(r,f)
        self.assertEqual((item['level'],item['count']),(8,2))
        self.assertTrue(130<=item['point'][0]<=150)
        shifted=f.copy();shifted[838:]=0;shifted[838:,100:]=f[838:,:-100]
        again=tray_item(r,shifted)
        self.assertEqual((again['level'],again['count']),(8,2))
        self.assertEqual(again['point'],(item['point'][0]+100,item['point'][1]))
        from coc_bot.layouts.placement import same_art
        self.assertTrue(same_art(item,again))

    def test_collapsed_wrench_requires_the_native_editor_heading(self):
        f=cv2.imread(str(FIXTURES/'collapsed-tools.png'));r=LayoutReader()
        self.assertIsNotNone(r.collapsed_tools(f))
        f[:94,:519]=0
        self.assertIsNone(r.collapsed_tools(f))
    def test_collect_all_recovery_cancels_only_the_exact_building_dialog(self):
        f=cv2.imread(str(FIXTURES/'collect-all.png'));r=LayoutReader()
        self.assertIsNotNone(r.collect_all_cancel(f))
        f[450:510,500:1340]=0
        self.assertIsNone(r.collect_all_cancel(f))

    @unittest.skipUnless(shutil.which('tesseract'),'Needs the server OCR runtime')
    def test_native_removal_progress_is_bound_to_the_selected_obstacle(self):
        from coc_bot.layouts.obstacles import removal_started
        f=cv2.imread(str(FIXTURES/'removal-started.png'));r=LayoutReader()
        self.assertTrue(removal_started(r,f,(760,575),'Trunk'))
        self.assertTrue(removal_started(r,f,(760,575),'Runk'))
        self.assertFalse(removal_started(r,f,(760,575),'Stone'))
        f[630:814,835:1020]=0
        self.assertFalse(removal_started(r,f,(760,575),'Trunk'))

    @unittest.skipUnless(shutil.which('tesseract'),'Needs the server OCR runtime')
    def test_selected_cake_price_and_gem_currency_rejection(self):
        from coc_bot.layouts.obstacles import selected
        frame=cv2.imread(str(FIXTURES/'cake-selected.png'));r=LayoutReader()
        result=selected(r,frame,(618,418),seasonal=True)
        self.assertEqual(result['cost'],1200)
        self.assertEqual(result['currency'],'gold')
        self.assertIn('anniversary',result['name'].lower())
        self.assertIsNone(selected(r,frame,(618,418),seasonal=False))
        shifted=frame.copy();shifted[630:814,730:1120]=0
        shifted[630:814,730:915]=frame[630:814,835:1020]
        moved=selected(r,shifted,(618,418),seasonal=True)
        self.assertEqual(moved['cost'],1200)
        self.assertLess(moved['point'][0],result['point'][0])
        frame[695:735,900:950]=(50,220,50)
        self.assertIsNone(selected(r,frame,(618,418),seasonal=True))
        rock=cv2.imread(str(FIXTURES/'stone-twenty-thousand.png'))
        result=selected(r,rock,(712,564),seasonal=True)
        self.assertEqual((result['name'],result['cost'],result['currency']),('Stone',20000,'gold'))
        rock[754:793,850:1000]=0
        self.assertIsNone(selected(r,rock,(712,564),seasonal=True))
    def test_round_trip_and_conservative_zone(self):
        m={'registered':True,'transform':[[3.4,0,10],[0,3.4,-50]]}
        points=np.array([[.5,.5],[43.5,43.5],[20,15]])
        self.assertTrue(np.allclose(tiles(m,pixels(m,points)),points))
        self.assertTrue(np.allclose(tiles(m,zone(m)),[[1,1],[43,1],[43,43],[1,43]]))
        with self.assertRaises(ValueError):pixels(m,[[np.nan,1]])
        with self.assertRaises(ValueError):tiles({'registered':False},[[1,1]])

    def test_future_building_interior_is_reserved_as_well_as_white_edges(self):
        f=np.full((1048,1853,3),(65,180,140),np.uint8)
        m={'registered':True,'transform':[[3.4,0,0],[0,3.4,-150]]}
        p=pixels(m,[(15,16),(18,16),(18,19),(15,19)])
        cv2.polylines(f,[np.rint(p).astype(int)],True,(245,245,245),3)
        blocked=reserved_tiles(f,m)
        self.assertTrue(blocked[16,17])
        self.assertFalse(blocked[3,3])

    def test_sunlit_grass_does_not_reserve_most_of_the_native_village(self):
        frame=cv2.imread(str(FIXTURES/'crowded-reservations.png'));m=camera(frame)
        blocked=reserved_tiles(frame,m)
        def occupied(pixel):
            u,v=np.floor(tiles(m,[pixel])[0]).astype(int)
            return bool(blocked[u,v])
        self.assertTrue(occupied([755,220]))
        self.assertFalse(occupied([400,590]))
        self.assertLess(blocked.sum(),400)

    def test_native_tiled_large_floor_is_not_mistaken_for_its_inner_tiles(self):
        frame=cv2.imread(str(FIXTURES/'large-red-footprint.png'));m=camera(frame)
        value=outline(frame,(821,685),m)
        self.assertEqual(value['colour'],'red');self.assertEqual(value['size'],3)
        self.assertFalse(safe_preview(value))

    def test_three_four_and_five_tile_green_floors_keep_their_real_size(self):
        m={'registered':True,'transform':[[2.7,0,0],[0,2.7,-80]]}
        for size in (3,4,5):
            f=np.full((1048,1853,3),(65,180,140),np.uint8)
            center=np.array([size/2,20.5 if size%2 else 20.])
            corners=pixels(m,[center+[-size/2,-size/2],center+[size/2,-size/2],
                              center+[size/2,size/2],center+[-size/2,size/2]])
            cv2.fillConvexPoly(f,np.rint(corners).astype(np.int32),(20,160,20))
            # The native floor has an internal tile grid as well as its border.
            for offset in range(size+1):
                for axis in (0,1):
                    a=center-np.array([size/2,size/2]);a[axis]+=offset
                    b=a.copy();b[1-axis]+=size
                    p,q=np.rint(pixels(m,[a,b])).astype(int)
                    cv2.line(f,tuple(p),tuple(q),(0,255,0),1)
            point=np.rint(pixels(m,[center])[0]+[0,30]).astype(int)
            value=outline(f,tuple(point),m)
            self.assertIsNotNone(value,size)
            self.assertEqual(value['size'],size);self.assertTrue(safe_preview(value))

    def test_native_floor_green_and_red_have_different_outcomes(self):
        for file,pointer,colour in [('wall-green-edge.png',(450,216),'green'),
                                    ('wall-green-zoomed-out.png',(408,308),'green'),
                                    ('wall-red-outside.png',(394,316),'red')]:
            frame=cv2.imread(str(FIXTURES/file));mapping=camera(frame)
            value=outline(frame,pointer,mapping,wall=True)
            self.assertIsNotNone(value,file)
            self.assertEqual(value['colour'],colour)
            self.assertEqual(value['size'],1)
            self.assertEqual(safe_preview(value),colour=='green')
        self.assertFalse(safe_preview(None))
        self.assertFalse(safe_preview({'colour':'green','size':3,'tile_center':[0,20]}))

    def test_lime_arrows_or_blank_frame_do_not_authorize_placement(self):
        f=np.zeros((1048,1853,3),np.uint8)
        cv2.fillConvexPoly(f,np.array([[700,400],[725,420],[680,420]]),(40,220,150))
        m={'registered':True,'transform':[[3.4,0,10],[0,3.4,-50]]}
        self.assertIsNone(outline(f,(700,430),m,wall=True))

    def test_caption_ocr_variance_cannot_change_the_verified_price_or_currency(self):
        from coc_bot.layouts.obstacles import same_removal
        first={'name':'12th Anniversary Cake','cost':1200,'currency':'gold','point':(927,734)}
        second=first|{'name':'(ety Anniversary Cake'}
        self.assertTrue(same_removal(first,second,seasonal=True))
        self.assertFalse(same_removal(first,second|{'cost':120},seasonal=True))
        self.assertFalse(same_removal(first,second|{'currency':'gems'},seasonal=True))
        self.assertFalse(same_removal(first,second,seasonal=False))

    def test_survey_finds_seasonal_and_ordinary_inside_zone(self):
        frame=cv2.imread(str(FIXTURES/'empty-survey-th12.png'));m=camera(frame)
        found=candidates(frame,[zone(m).tolist()])
        self.assertTrue(any(np.linalg.norm(np.array(p)-[618,418])<10 for p in found))
        self.assertTrue(any(np.linalg.norm(np.array(p)-[405,314])<10 for p in found))
        self.assertTrue(all(cv2.pointPolygonTest(zone(m).astype(np.float32),p,False)>=0 for p in found))
        self.assertTrue(all(p[1]<frame.shape[0]*.58 for p in found))
        rock=cv2.imread(str(FIXTURES/'stone-twenty-thousand.png'));m=camera(rock)
        found=candidates(rock,[zone(m,margin=0).tolist()])
        self.assertTrue(any(np.linalg.norm(np.array(p)-[712,564])<10 for p in found))

    def test_full_legal_zone_includes_edge_obstacles_and_excludes_the_outer_ring(self):
        frame=np.full((1048,1853,3),(65,180,140),np.uint8)
        m={'registered':True,'transform':[[2.7,0,0],[0,2.7,-80]]}
        inside,outside=np.rint(pixels(m,[[.5,25.5],[-1.5,25.5]])).astype(int)
        for point in (inside,outside):cv2.circle(frame,tuple(point),8,(30,30,30),-1)
        points=candidates(frame,[zone(m,margin=0).tolist()])
        self.assertTrue(any(np.linalg.norm(np.array(p)-inside)<10 for p in points))
        self.assertFalse(any(np.linalg.norm(np.array(p)-outside)<10 for p in points))

    def test_wide_forest_landmarks_are_sufficiently_constrained(self):
        result=camera(cv2.imread(str(FIXTURES/'wide-landmark-survey.png')))
        self.assertTrue(result['registered'],result)
        self.assertGreater(result['inliers'],60)
        self.assertLess(result['error_p95'],2.5)


class AutomaticTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name)
        self.config=SimpleNamespace(data_dir=self.root,account_tag='#PYLQG',account_town_hall=12,
            layouts_enabled=True,layouts_replace_inactive=True,dry_run=False,
            progression_clear_obstacles=True,progression_clear_seasonal_obstacles=True,
            upgrade_builders_reserved=0,donation_enabled=False)
        self.s=SimpleNamespace(config=self.config,capture=Mock(),input=Mock(),client=Mock(),navigator=Mock())
        self.r=LayoutRunner(self.s)

    def test_last_camera_pan_returns_its_new_frame_instead_of_old_tap_coordinates(self):
        f=np.zeros((1048,1853,3),np.uint8)
        before=(f,{'view':0});middle=(f.copy(),{'view':1});after=(f.copy(),{'view':2})
        with patch.object(self.r,'mapped_frame',side_effect=[before,middle,after]) as capture,\
             patch.object(self.r,'wait',return_value=False),\
             patch('coc_bot.layouts.runner.pixels',side_effect=[np.array([[100,100]]),np.array([[450,320]])]),\
             patch('coc_bot.adb.multitouch.Multitouch'):
            actual=self.r.reframe((22,22))
        self.assertIs(actual,after)
        self.assertEqual(capture.call_count,3)

    def test_practice_and_disabled_never_send_inputs(self):
        self.config.dry_run=True
        self.assertEqual(self.r.run()['status'],'disabled')
        self.config.dry_run=False;self.config.layouts_enabled=False
        self.assertEqual(self.r.run()['status'],'disabled')
        self.s.capture.screenshot.assert_not_called();self.s.input.tap.assert_not_called()

    def test_automatic_layouts_are_an_opt_in_boolean_setting(self):
        import yaml
        from coc_bot.config import BotConfig
        from coc_bot.control.settings_fields import SETTINGS
        self.assertIs(BotConfig.__dataclass_fields__['layouts_enabled'].default,False)
        defaults=yaml.safe_load((Path(__file__).resolve().parents[1]/'config/default.yaml').read_text())
        self.assertIs(defaults['layouts']['enabled'],False)
        setting=next(f for f in SETTINGS if f.key=='layouts_enabled')
        self.assertEqual(setting.kind,'bool')

    def test_layout_logging_allows_home_and_recovery_but_flags_combat(self):
        from coc_bot.runtime.game_state import GameState,GameStateMachine
        machine=GameStateMachine(GameState.HOME)
        self.assertTrue(machine.note_loop_state('layouts'))
        self.assertTrue(machine.transition(GameState.RECOVERING))
        machine.reset(GameState.LAYOUTS)
        self.assertFalse(machine.transition(GameState.IN_BATTLE))

    def test_unknown_hall_and_unsupported_low_hall_do_not_import(self):
        for hall in (None,2,3):
            self.config.account_town_hall=hall
            self.assertEqual(self.r.run()['status'],'unavailable')
        self.s.input.tap.assert_not_called()

    def test_foreign_layout_checkpoint_blocks_before_capture(self):
        write(self.r.i.path,{'pending':{'account':'#OTHER','phase':'opening'}})
        self.assertEqual(self.r.run()['status'],'needs_review')
        self.s.capture.screenshot.assert_not_called()

    def test_all_builders_busy_does_not_block_the_obstacle_survey(self):
        proof={'builders':[0,4],'gems':20,'balances':{'gold':1000,'elixir':1000}}
        self.config.upgrade_builders_reserved=4
        with patch('coc_bot.layouts.runner.ensure_home',return_value=True),\
             patch('coc_bot.layouts.runner.home_resources',return_value=proof),\
             patch.object(self.r.i,'open_survey',return_value=False) as opening:
            result=self.r._clear_one('unused',12,999999999)
        self.assertEqual(result['status'],'blocked');opening.assert_called_once()
        self.s.input.tap.assert_not_called()

    def test_changed_counters_do_not_open_editor(self):
        with patch('coc_bot.layouts.runner.ensure_home',return_value=True),\
             patch('coc_bot.layouts.runner.home_resources',side_effect=[{'gems':20},{'gems':21}]),\
             patch.object(self.r.i,'open_survey') as opening:
            self.assertEqual(self.r._clear_one('unused',12,999999999)['status'],'waiting')
        opening.assert_not_called()

    def test_lower_candidate_cannot_be_tapped_without_positive_idle_proof(self):
        proof={'builders':[1,4],'gems':20,'balances':{'gold':1000,'elixir':1000}}
        f=np.zeros((1048,1853,3),np.uint8)
        m={'registered':True,'transform':[[3.4,0,0],[0,3.4,-150]]}
        self.s.capture.screenshot.return_value=f
        self.r.i.reader=Mock();self.r.i.reader.editing.return_value=True
        self.r.i.reader.idle_editor.return_value=False
        with patch('coc_bot.layouts.runner.home_resources',return_value=proof),\
             patch('coc_bot.layouts.runner.candidates',return_value=[(966,667)]),\
             patch.object(self.r.i,'open_survey',return_value=True),\
             patch.object(self.r,'zoom_out',return_value=True),\
             patch.object(self.r.i,'expose_obstacles',return_value=True),\
             patch.object(self.r.i,'confirm_obstacle_survey',return_value=True),\
             patch.object(self.r,'mapped_frame',return_value=(f,m)),\
             patch.object(self.r,'wait',return_value=False),\
             patch('coc_bot.layouts.runner.remove_selected') as payment:
            self.assertEqual(self.r._clear_one('unused',12,999999999)['status'],'needs_review')
        self.s.input.tap.assert_called_once_with(74,702,jitter=0);payment.assert_not_called()

    def test_lower_candidate_uses_two_idle_frames_and_fresh_camera_before_payment(self):
        proof={'builders':[1,4],'gems':20,'balances':{'gold':1000,'elixir':1000}}
        f=np.zeros((1048,1853,3),np.uint8)
        m={'registered':True,'transform':[[3.4,0,0],[0,3.4,-150]]}
        self.s.capture.screenshot.return_value=f
        self.r.i.reader=Mock();self.r.i.reader.editing.return_value=True
        self.r.i.reader.idle_editor.return_value=True
        with patch('coc_bot.layouts.runner.home_resources',return_value=proof),\
             patch('coc_bot.layouts.runner.candidates',return_value=[(966,667)]),\
             patch('coc_bot.layouts.runner.camera',return_value=m),\
             patch.object(self.r.i,'open_survey',return_value=True),\
             patch.object(self.r,'zoom_out',return_value=True),\
             patch.object(self.r.i,'expose_obstacles',return_value=True),\
             patch.object(self.r.i,'confirm_obstacle_survey',return_value=True),\
             patch.object(self.r,'mapped_frame',return_value=(f,m)),\
             patch.object(self.r,'wait',return_value=False),\
             patch('coc_bot.layouts.runner.selected',return_value={'name':'Tree'}),\
             patch('coc_bot.layouts.runner.remove_selected',return_value={'status':'making_room'}) as payment:
            write(self.r.i.path,{'pending':{}})
            self.assertEqual(self.r._clear_one('unused',12,999999999)['status'],'making_room')
        self.s.input.tap.assert_called_once_with(966,667,jitter=0)
        self.assertGreaterEqual(self.r.i.reader.idle_editor.call_count,3)
        payment.assert_called_once_with(self.r.i,(966,667))

    def test_unreadable_remove_control_cannot_be_counted_as_clear_ground(self):
        proof={'gems':20,'balances':{'gold':1000,'elixir':1000}}
        f=np.zeros((1048,1853,3),np.uint8)
        m={'registered':True,'transform':[[3.4,0,0],[0,3.4,-150]]}
        self.s.capture.screenshot.return_value=f
        self.r.i.reader=Mock();self.r.i.reader.editing.return_value=True
        self.r.i.reader.idle_editor.return_value=True
        self.r.i.reader.find.return_value=(927,772)
        with patch('coc_bot.layouts.runner.home_resources',return_value=proof), \
             patch('coc_bot.layouts.runner.candidates',return_value=[(966,667)]), \
             patch('coc_bot.layouts.runner.camera',return_value=m), \
             patch.object(self.r.i,'open_survey',return_value=True), \
             patch.object(self.r,'zoom_out',return_value=True), \
             patch.object(self.r.i,'expose_obstacles',return_value=True), \
             patch.object(self.r.i,'confirm_obstacle_survey',return_value=True), \
             patch.object(self.r,'mapped_frame',return_value=(f,m)), \
             patch.object(self.r,'wait',return_value=False), \
             patch('coc_bot.layouts.runner.selected',return_value=None), \
             patch('coc_bot.layouts.runner.remove_selected') as payment, \
             patch.object(self.r,'finish_clearance') as cleared:
            self.assertEqual(self.r._clear_one('unused',12,999999999)['status'],'waiting')
        cleared.assert_not_called();payment.assert_not_called()
        self.assertEqual(read(self.r.i.path)['automatic']['survey_rejected'],[])

    def test_recovery_resolves_existing_payment_without_new_clearing(self):
        write(self.r.i.path,{'pending':{'account':self.config.account_tag,'payment':{'cost':100}}})
        self.config.layouts_enabled=False
        with patch('coc_bot.layouts.runner.reconcile',return_value={'status':'making_room'}) as receipt:
            self.assertTrue(self.r.recover())
        receipt.assert_called_once();self.s.input.tap.assert_not_called()

    def test_activation_recovery_needs_home_before_completing_the_journal(self):
        write(self.r.i.path,{'pending':{'account':self.config.account_tag,'phase':'activating',
             'slot':1,'original_slot':0,'hall':12},'draft':{'slot':1}})
        self.r.i.reader=Mock();self.r.i.reader.active_slot.return_value=1
        with patch.object(self.r.i,'close',return_value=True),\
             patch.object(self.r,'home',return_value=False):
            self.assertFalse(self.r.recover())
        self.assertIn('pending',read(self.r.i.path));self.assertNotIn('completed',read(self.r.i.path))
        with patch.object(self.r.i,'close',return_value=True),\
             patch.object(self.r,'home',return_value=True):
            self.assertTrue(self.r.recover())
        state=read(self.r.i.path)
        self.assertEqual(state['completed']['status'],'active')
        self.assertEqual(state['automatic']['stage'],'verifying')
        self.assertNotIn('draft',state);self.s.input.tap.assert_not_called()

    def test_disabled_layout_still_recovers_an_existing_receipt_before_cooldown(self):
        self.config.layouts_enabled=False
        write(self.r.i.path,{'last_survey':{'account':self.config.account_tag,'payment':{'cost':100}},
                             'automatic':{'next_check_at':9999999999}})
        with patch.object(self.r,'recover',return_value=True) as recovery:
            self.assertEqual(self.r.run()['status'],'recovered')
        recovery.assert_called_once();self.s.input.tap.assert_not_called()

    def test_previous_obstacle_reward_must_settle_before_another_payment(self):
        write(self.r.i.path,{'automatic':{'removal_settle_until':9999999999}})
        self.assertEqual(self.r.run()['status'],'waiting')
        self.s.capture.screenshot.assert_not_called();self.s.input.tap.assert_not_called()

    def test_confirmed_moves_are_saved_when_the_next_camera_read_fails(self):
        write(self.r.i.path,{'pending':{'account':self.config.account_tag,'slot':1,'original_slot':0}})
        self.r.i.reader=Mock();self.r.i.reader.ready_save.return_value=None
        with patch.object(self.r,'_open',return_value=True),\
             patch.object(self.r,'reframe',return_value=(None,None)),\
             patch.object(self.r.i,'show_tools',return_value=True),\
             patch.object(self.r.i,'save_draft',return_value=True) as save,\
             patch.object(self.r.i,'close',return_value=True),\
             patch('coc_bot.layouts.runner.InventoryPlacer') as placer:
            placer.return_value.one.side_effect=[{'status':'placed'},{'status':'needs_geometry'}]
            result=self.r._place('unused',12,999999999)
        self.assertEqual(result,{'status':'draft','placed_this_visit':1,'retry_reason':'needs_geometry'})
        save.assert_called_once();self.s.input.tap.assert_not_called()

    def test_final_item_completes_native_save_even_at_the_visit_deadline(self):
        write(self.r.i.path,{'pending':{'account':self.config.account_tag,'slot':1,'original_slot':0}})
        self.r.i.reader=Mock();self.r.i.reader.ready_save.return_value=None
        with patch.object(self.r,'_open',return_value=True),\
             patch.object(self.r,'reframe',return_value=(None,None)),\
             patch.object(self.r,'home',return_value=True),\
             patch.object(self.r.i,'show_tools',return_value=True),\
             patch.object(self.r.i,'save_complete',return_value=True) as complete,\
             patch.object(self.r.i,'activate',return_value=True) as activate,\
             patch.object(self.r,'_verify_active_home',return_value={'verified':True}),\
             patch.object(self.r.i,'close',return_value=True),\
             patch.object(self.r.i,'save_draft') as draft,\
             patch('coc_bot.layouts.runner.time.monotonic',side_effect=[0,0,100]),\
             patch('coc_bot.layouts.runner.InventoryPlacer') as placer:
            placer.return_value.one.return_value={'status':'placed','native_complete':True}
            result=self.r._place('unused',12,1)
        self.assertEqual(result,{'status':'active','placed_this_visit':1,'home_verified':True})
        complete.assert_called_once();activate.assert_called_once();draft.assert_not_called()

    def test_camera_search_continues_from_saved_next_view_after_deadline(self):
        write(self.r.i.path,{'pending':{'account':self.config.account_tag,'slot':1,'original_slot':0}})
        self.r.i.reader=Mock();self.r.i.reader.ready_save.return_value=None
        with patch.object(self.r,'_open',return_value=True),\
             patch.object(self.r,'reframe',return_value=(None,None)),\
             patch.object(self.r.i,'show_tools',return_value=True),\
             patch.object(self.r.i,'save_draft',return_value=True),\
             patch.object(self.r.i,'close',return_value=True),\
             patch('coc_bot.layouts.runner.time.monotonic',side_effect=[0,0,100]),\
             patch('coc_bot.layouts.runner.InventoryPlacer') as placer:
            placer.return_value.one.return_value={'status':'no_spare_ground'}
            self.assertEqual(self.r._place('unused',12,1)['status'],'draft')
        self.assertEqual(read(self.r.i.path)['pending']['placement_view'],1)
        with patch.object(self.r,'_open',return_value=True),\
             patch.object(self.r,'reframe',return_value=None) as pan:
            self.assertEqual(self.r._place('unused',12,999999999)['status'],'needs_geometry')
        pan.assert_called_once_with((11,33))

    def test_an_unchanged_room_survey_does_not_discard_a_saved_layout(self):
        from coc_bot.layouts.runner import REVISION
        write(self.r.i.path,{'automatic':{'cleared_at':300,'last_removal_at':100},
             'draft':{'automatic_revision':REVISION,'hall':12,'link':'unused','saved_at':200}})
        with patch.object(self.r.i,'resume_draft',return_value=False) as resume,\
             patch.object(self.r,'_open') as opening:
            self.assertEqual(self.r._place('unused',12,999999999)['status'],'needs_review')
        resume.assert_called_once();opening.assert_not_called()

    def test_changed_reference_cannot_resume_an_old_layout_draft(self):
        from coc_bot.layouts.runner import REVISION
        write(self.r.i.path,{'automatic':{'last_removal_at':100},
             'draft':{'automatic_revision':REVISION,'hall':12,'link':'old','saved_at':200,
                      'slot':1,'original_slot':0}})
        with patch.object(self.r.i,'resume_draft') as resume,\
             patch.object(self.r,'_open',return_value=False) as opening:
            self.assertEqual(self.r._place('new',12,999999999)['status'],'blocked')
        resume.assert_not_called();opening.assert_called_once_with('new',12)
        self.s.input.tap.assert_not_called()
        self.assertEqual(read(self.r.i.path)['draft']['original_slot'],0)

    def test_run_uses_the_importers_canonical_link_for_draft_comparison(self):
        from coc_bot.layouts.runner import REVISION
        from coc_bot.layouts.catalog import official_layout
        url='https://link.clashofclans.com/en/?action=OpenLayout&id=TH12:HV:ABCDEFGHIJKL'
        write(self.r.i.path,{'automatic':{'hall':12,'revision':REVISION,'stage':'placing','cleared_at':9999999999,'selected_reference':official_layout(url,12)}})
        with patch('coc_bot.layouts.runner.catalog',return_value=[{'link':url}]),\
             patch.object(self.r,'home',return_value=True),\
             patch.object(self.r,'_place',return_value={'status':'draft'}) as place:
            self.assertEqual(self.r.run()['status'],'draft')
        self.assertEqual(place.call_args.args[:2],(official_layout(url,12),12))
        self.assertIn('%3A',place.call_args.args[0])

    def test_full_search_resurveys_once_then_selects_another_reference(self):
        from coc_bot.layouts.runner import REVISION
        from coc_bot.layouts.catalog import official_layout
        first=official_layout('https://link.clashofclans.com/en/?action=OpenLayout&id=TH12:HV:ABCDEFGHIJKL',12)
        second=official_layout('https://link.clashofclans.com/en/?action=OpenLayout&id=TH12:HV:MNOPQRSTUVWX',12)
        write(self.r.i.path,{'automatic':{'hall':12,'revision':REVISION,'last_removal_at':100,'cleared_at':9999999999}})
        with patch('coc_bot.layouts.runner.catalog',return_value=[{'link':first},{'link':second}]),\
             patch.object(self.r,'home',return_value=True),\
             patch.object(self.r,'_import',return_value={'status':'draft'}) as place:
            self.r.exhausted_reference(first,12)
            self.assertEqual(read(self.r.i.path)['automatic']['stage'],'matching')
            self.assertEqual(read(self.r.i.path)['automatic']['unfit_references'],[first])
            self.assertEqual(self.r.run()['status'],'draft')
        self.assertEqual(place.call_args.args[:2],(second,12));self.s.input.tap.assert_not_called()

    def test_a_new_obstacle_removal_allows_a_fresh_fit_check(self):
        write(self.r.i.path,{'automatic':{'last_removal_at':200,
             'fit_retry':{'link':'same','last_removal_at':100}}})
        self.r.exhausted_reference('same',12)
        result=read(self.r.i.path)['automatic']
        self.assertEqual(result['stage'],'clearing')
        self.assertEqual(result['fit_retry']['last_removal_at'],200)
        self.assertNotIn('same',result.get('unfit_references',[]))

    def test_exhausted_catalog_stops_without_reimporting_or_touching_active_slot(self):
        from coc_bot.layouts.runner import REVISION
        from coc_bot.layouts.catalog import official_layout
        url=official_layout('https://link.clashofclans.com/en/?action=OpenLayout&id=TH12:HV:ABCDEFGHIJKL',12)
        write(self.r.i.path,{'automatic':{'hall':12,'revision':REVISION,'stage':'needs_reference',
                                        'unfit_references':[url]}})
        with patch('coc_bot.layouts.runner.catalog',return_value=[{'link':url}]):
            self.assertEqual(self.r.run()['status'],'unavailable')
        self.s.capture.screenshot.assert_not_called();self.s.input.tap.assert_not_called()

    def test_failed_camera_pan_does_not_disqualify_a_reference(self):
        write(self.r.i.path,{'pending':{'account':self.config.account_tag,'slot':1,'original_slot':0}})
        self.r.i.reader=Mock();self.r.i.reader.ready_save.return_value=None
        with patch.object(self.r,'_open',return_value=True),\
             patch.object(self.r,'reframe',side_effect=[(None,None),None]),\
             patch.object(self.r.i,'show_tools',return_value=True),\
             patch.object(self.r,'exhausted_reference') as exhausted,\
             patch('coc_bot.layouts.runner.InventoryPlacer') as placer:
            placer.return_value.one.return_value={'status':'no_spare_ground'}
            self.assertEqual(self.r._place('unused',12,999999999)['status'],'needs_geometry')
        exhausted.assert_not_called()

    def test_cold_navigation_cannot_exhaust_the_native_completion_check(self):
        write(self.r.i.path,{'pending':{'account':self.config.account_tag,'slot':1,'original_slot':0}})
        self.r.i.reader=Mock();self.r.i.reader.ready_save.return_value=(100,100)
        with patch.object(self.r,'_open',return_value=True),\
             patch.object(self.r,'reframe',return_value=(None,None)),\
             patch.object(self.r,'home',return_value=True),\
             patch.object(self.r.i,'show_tools',return_value=True),\
             patch.object(self.r.i,'save_complete',return_value=True) as complete,\
             patch.object(self.r.i,'activate',return_value=True),\
             patch.object(self.r,'_verify_active_home',return_value={'verified':True}),\
             patch.object(self.r.i,'close',return_value=True),\
             patch.object(self.r.i,'save_draft') as draft,\
             patch('coc_bot.layouts.runner.time.monotonic',return_value=100),\
             patch('coc_bot.layouts.runner.InventoryPlacer') as placer:
            self.assertEqual(self.r._place('unused',12,1)['status'],'active')
        complete.assert_called_once();draft.assert_not_called();placer.assert_not_called()

    def test_cold_clearing_navigation_still_attempts_a_real_survey(self):
        proof={'builders':[1,4],'gems':20,'balances':{'gold':1000,'elixir':1000}}
        with patch('coc_bot.layouts.runner.home_resources',return_value=proof),\
             patch('coc_bot.layouts.runner.time.monotonic',return_value=100),\
             patch.object(self.r.i,'open_survey',return_value=True),\
             patch.object(self.r,'zoom_out',return_value=True),\
             patch.object(self.r.i,'expose_obstacles',return_value=True),\
             patch.object(self.r.i,'confirm_obstacle_survey',return_value=True),\
             patch.object(self.r,'mapped_frame',return_value=None) as survey:
            self.assertEqual(self.r._clear_one('unused',12,1)['status'],'needs_geometry')
        survey.assert_called_once();self.s.input.tap.assert_not_called()

    def test_a_room_survey_uses_the_other_inactive_slot_to_preserve_the_working_draft(self):
        write(self.r.i.path,{'draft':{'account':self.config.account_tag,'slot':1}})
        def opening(*args):
            state=read(self.r.i.path,{});state['pending']={};write(self.r.i.path,state)
            return True
        self.r.i.reader=Mock();self.r.i.reader.inventory_notice.return_value=None
        self.r.i.reader.editing.return_value=True
        with patch.object(self.r.i,'open',side_effect=opening),\
             patch.object(self.r.i,'select_empty',return_value=True) as choose,\
             patch.object(self.r,'zoom_out',return_value=True):
            self.assertTrue(self.r._open('unused',12,{'at':100}))
        choose.assert_called_once_with(replace_inactive=True,exclude_slots=(1,))

    def test_stop_leaves_checkpoint_and_sends_nothing(self):
        write(self.r.i.path,{'pending':{'account':self.config.account_tag,'phase':'copying_to_empty_slot'}})
        self.r.stop=lambda:True
        self.assertEqual(self.r.run()['status'],'stopped')
        self.assertIn('pending',read(self.r.i.path));self.s.input.tap.assert_not_called()

    def test_new_construction_marks_layout_dirty_without_losing_receipts(self):
        write(self.r.i.path,{'completed':{'status':'active'},'automatic':{'stage':'active','dirty':False}})
        dirty(self.config);state=read(self.r.i.path)
        self.assertTrue(state['automatic']['dirty'])
        self.assertEqual(state['completed'],{'status':'active'})

    def test_cancelling_a_resumed_visit_restores_only_the_last_saved_draft(self):
        art=(np.arange(2048)%255).reshape(32,64).tolist()
        prior={'account':self.config.account_tag,'hall':12,'slot':1,'original_slot':0,
               'backup':'verified','thumbnail':art,'placements':[{'phase':'confirmed'}]}
        pending=prior|{'phase':'copying_to_empty_slot','placements':[{},{}],
                       'resume_checkpoint':prior}
        write(self.r.i.path,{'pending':pending})
        self.r.i.reader=Mock();self.r.i.reader.editing.return_value=False
        self.r.i.reader.active_slot.return_value=0;self.r.i.reader.thumbnail.return_value=art
        self.assertTrue(self.r.i.cancel_obstacle_survey())
        state=read(self.r.i.path)
        self.assertEqual(state['draft'],prior)
        self.assertEqual(len(state['last_survey']['placements']),2)
        self.s.input.tap.assert_not_called()

    def test_hall_change_ignores_old_cooldown_and_cannot_inherit_active_status(self):
        from coc_bot.layouts.runner import REVISION
        write(self.r.i.path,{'automatic':{'stage':'active','hall':11,'revision':REVISION,
                                        'dirty':False,'next_check_at':9999999999}})
        with patch.object(self.r,'_clear_one',return_value={'status':'waiting'}) as clearing,\
             patch.object(self.r,'home',return_value=True):
            self.assertEqual(self.r.run()['status'],'waiting')
        clearing.assert_called_once()
        state=read(self.r.i.path)['automatic']
        self.assertEqual(state['hall'],12);self.assertEqual(state['stage'],'clearing')
        self.assertTrue(state['dirty'])

    def placement(self,after,*,measure=False,slot=0,tail_anchor=True,offset=False,size=1,unreadable_first=False,old_cache=False):
        frame=np.full((1048,1853,3),(65,180,140),np.uint8)
        self.s.capture.screenshot.return_value=frame
        self.r.i.reader=Mock();self.r.i.reader.editing.return_value=True
        self.r.i.reader.ready_save.return_value=None
        before={'level':4,'count':3,'art':np.eye(32,dtype=np.uint8).tolist(),
                'wall':True,'point':(93,943)}
        if slot:before.update(count=1,wall=False,point=(485,943))
        if size>1:before['wall']=False
        anchor=before|{'level':15,'count':20,'slot':0}
        before.update(slot=slot,measure_only=measure,anchor=anchor)
        write(self.r.i.path,{'pending':{'phase':'copying_to_empty_slot','account':self.config.account_tag,
                                     'slot':1,'original_slot':0,'backup':'verified-backup'}})
        if old_cache:
            state=read(self.r.i.path)
            state['pending'].update(placements=[{'phase':'confirmed'}],failed_ground=[{'level':before['level'],'art':before['art'],'size':size,'tiles':[[2.5,32.5]]}])
            write(self.r.i.path,state)
        mapping={'registered':True,'transform':[[3.4,0,0],[0,3.4,-150]]}
        value={'colour':'green','size':size,'center':[600,400],'tile_center':[2.5,32.5],'score':1.}
        fresh=None if after is None else before|{'count':after}
        observed=[]
        def native_floor(f,point,m,**kwargs):
            observed.append(point)
            if unreadable_first and len(observed)==1:return None
            if offset and len(observed)==1:
                return value|{'colour':'red','center':[point[0]-18,point[1]-54]}
            return value
        receipts=[before,fresh,fresh]
        if slot and fresh is None:receipts.extend([anchor,anchor if tail_anchor else None])
        with patch('coc_bot.layouts.placement.inventory_choice',return_value=before),\
             patch('coc_bot.layouts.placement.tray_item',side_effect=receipts),\
             patch.object(InventoryPlacer,'reset_inventory',return_value=True),\
             patch('coc_bot.layouts.grid.camera',return_value=mapping),\
             patch('coc_bot.layouts.grid.outline',side_effect=native_floor),\
             patch('coc_bot.layouts.grid.reserved_tiles',return_value=np.zeros((44,44),bool)),\
             patch('coc_bot.adb.multitouch.Multitouch') as transport,\
             patch('coc_bot.layouts.placement.interrupted_sleep',return_value=False):
            result=InventoryPlacer(self.r.i).one()
        return result,read(self.r.i.path),transport

    def test_native_green_and_inventory_decrement_are_both_required(self):
        result,state,transport=self.placement(2,offset=True)
        self.assertEqual(result['status'],'placed')
        self.assertNotIn('placement',state['pending'])
        self.assertEqual(len(state['pending']['placements']),1)
        transport.return_value.__enter__.return_value.release_fingers.assert_called_once()
        events=transport.return_value.__enter__.return_value._send.call_args_list
        self.assertEqual([e.args[-1][0] for e in events[:9]],[93]*9)
        self.assertLess(events[8].args[-1][1],838)
        evidence=read(self.config.data_dir/'layouts/placement-receipt.json')
        adjusted=np.asarray(evidence['observations'][1]['pointer'])-[18,54]
        uv=tiles({'registered':True,'transform':[[3.4,0,0],[0,3.4,-150]]},[adjusted])[0]
        fraction=(uv-.5)%1
        self.assertTrue(np.all(np.minimum(fraction,1-fraction)<.04))

    def test_unchanged_inventory_is_not_a_successful_placement(self):
        result,state,_=self.placement(3)
        self.assertEqual(result['status'],'rejected')
        self.assertNotIn('placements',state['pending'])

    def test_red_large_floor_skips_cells_that_cannot_hold_its_footprint(self):
        result,state,_=self.placement(2,offset=True,size=3)
        self.assertEqual(result['status'],'placed')
        evidence=read(self.config.data_dir/'layouts/placement-receipt.json')
        self.assertEqual(evidence['observations'][0]['outline']['colour'],'red')
        pointer=np.asarray(evidence['observations'][1]['pointer'])-[18,54]
        uv=tiles({'registered':True,'transform':[[3.4,0,0],[0,3.4,-150]]},[pointer])[0]
        self.assertTrue(np.all(uv>=1.45) and np.all(uv<=42.55),uv)
        self.assertEqual(state['pending']['failed_ground'][0]['size'],3)

    def test_unreadable_floor_does_not_permanently_reject_a_location(self):
        result,state,_=self.placement(2,unreadable_first=True)
        self.assertEqual(result['status'],'placed')
        self.assertEqual(state['pending']['failed_ground'][0]['tiles'],[])

    def test_old_search_cache_is_reset_without_losing_confirmed_placements(self):
        result,state,_=self.placement(2,old_cache=True)
        self.assertEqual(result['status'],'placed')
        self.assertEqual(len(state['pending']['placements']),2)
        self.assertEqual(state['pending']['failed_ground'][0]['tiles'],[])
        self.assertEqual(state['pending']['placement_cache_policy'],'native-red-world-v1')

    def test_unreadable_receipt_retains_the_move_journal(self):
        result,state,_=self.placement(None)
        self.assertEqual(result['status'],'needs_review')
        self.assertIn('placement',state['pending'])

    def test_measuring_a_building_returns_it_without_placing_or_changing_its_count(self):
        result,state,transport=self.placement(3,measure=True)
        self.assertEqual(result['status'],'probed')
        self.assertNotIn('placements',state['pending'])
        self.assertNotIn('placement',state['pending'])
        self.assertEqual(state['pending']['failed_ground'][0]['size'],1)
        self.assertEqual(transport.return_value.__enter__.return_value._send.call_args.args[-1],(93,943))

    def test_changed_inventory_during_measurement_is_not_a_successful_probe(self):
        result,state,_=self.placement(2,measure=True)
        self.assertEqual(result['status'],'needs_review')
        self.assertIn('placement',state['pending'])
        self.assertNotIn('placements',state['pending'])

    def test_last_card_disappearance_needs_the_same_left_inventory_anchor(self):
        result,state,_=self.placement(None,slot=2)
        self.assertEqual(result['status'],'placed')
        self.assertEqual(len(state['pending']['placements']),1)
        result,state,_=self.placement(None,slot=2,tail_anchor=False)
        self.assertEqual(result['status'],'needs_review')
        self.assertIn('placement',state['pending'])

    def test_inventory_uses_the_first_card_without_scrolling_to_other_cards(self):
        from coc_bot.layouts.placement import inventory_choice
        art=np.eye(32,dtype=np.uint8).tolist()
        wall={'level':4,'count':3,'art':art,'wall':True,'slot':0}
        tower=wall|{'level':8,'wall':False,'slot':1}
        camp=wall|{'level':5,'wall':False,'slot':2}
        known=[tower|{'size':3},camp|{'size':5}]
        with patch('coc_bot.layouts.placement.tray_item',return_value=wall) as card:
            value=inventory_choice(None,None,{'failed_ground':[]})
            self.assertEqual(value['slot'],0);self.assertFalse(value['measure_only'])
            value=inventory_choice(None,None,{'failed_ground':known})
            self.assertEqual(value['slot'],0);self.assertFalse(value['measure_only'])
            self.assertEqual(card.call_args.args,(None,None))

    def test_inventory_receipt_page_is_restored_inside_the_tray_and_needs_an_unchanged_card(self):
        self.r.i.reader=Mock();self.r.i.reader.editing.return_value=True
        self.r.i.reader.ready_save.return_value=None
        self.s.capture.screenshot.return_value=np.zeros((1048,1853,3),np.uint8)
        a={'level':4,'count':7,'art':np.eye(32,dtype=np.uint8).tolist()}
        with patch('coc_bot.layouts.placement.interrupted_sleep',return_value=False),\
             patch('coc_bot.layouts.placement.tray_start',return_value=True),\
             patch('coc_bot.layouts.placement.tray_item',side_effect=[None,a,a,a,a]):
            self.assertTrue(InventoryPlacer(self.r.i).reset_inventory())
        self.assertEqual(self.s.input.swipe.call_count,2)
        self.s.input.swipe.assert_called_with(315,1022,1538,1022,450)
        self.r.i.reader.editing.return_value=False
        self.assertFalse(InventoryPlacer(self.r.i).reset_inventory())
        self.s.input.tap.assert_not_called()


if __name__=='__main__':unittest.main()
