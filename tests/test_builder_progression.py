import tempfile,unittest,shutil
from pathlib import Path
from unittest.mock import Mock,patch
import cv2,numpy as np
from coc_bot.config import load_config
from dataclasses import replace
from coc_bot.accounts.store import read,write
from coc_bot.builder_base.progression import BuilderProgressionReader,BuilderProgressionRunner,BuilderConstruction,hall_blockers
from coc_bot.upgrades.vision import Candidate,compact


class BuilderProgressionTests(unittest.TestCase):
    def test_last_wall_requires_exact_native_word_and_no_quantity_suffix(self):
        frame=self.fixture('last-new-wall.png');reader=BuilderProgressionReader()
        row={'new':True,'box':(1358,117,495,68)}
        self.assertTrue(reader.single_new_wall(frame,row))
        cv2.putText(frame,'x2',(1500,145),cv2.FONT_HERSHEY_SIMPLEX,.7,(80,255,120),2)
        self.assertFalse(reader.single_new_wall(frame,row))

    @unittest.skipUnless(shutil.which('tesseract'),'OCR executable is required')
    def test_single_wall_fallback_recovers_missing_short_title_ocr(self):
        rows=BuilderProgressionReader().rows(self.fixture('last-new-wall.png'))
        wall=next(r for r in rows if compact(r['name'])=='wall')
        self.assertEqual((wall['quantity'],wall['cost'],wall['currency']),(1,0,'free'))
        lab=next(r for r in rows if compact(r['name'])=='starlaboratory')
        self.assertEqual((lab['cost'],lab['currency']),(15000,'elixir'))

    def test_wall_cancel_remains_visible_when_its_red_mask_joins_a_barracks_roof(self):
        frame=self.fixture('wall-bright-preview.png')
        found=self.r.construction_controls(frame)
        self.assertIsNotNone(found);self.assertEqual(found['confirm'],(956,462))
        self.assertLess(abs(found['cancel'][0]-891),3)
        frame[448:480,877:905]=0
        self.assertIsNone(self.r.construction_controls(frame))

    def test_research_sorting_is_not_mistaken_for_resource_filters(self):
        reader=BuilderProgressionReader();frame=self.fixture('research-sorting-only.png')
        self.assertTrue(reader.research_sorting(frame))
        for box in ((889,144,1046,182),(935,228,1092,266),(1203,228,1354,266)):
            bad=frame.copy();x0,y0,x1,y1=box;bad[y0:y1,x0:x1]=0
            self.assertFalse(reader.research_sorting(bad))
        self.assertFalse(reader.research_sorting((frame*.5).astype(np.uint8)))

    def test_research_scan_closes_exact_sort_popup_without_toggling_build_filters(self):
        r=self.r;r.reader=Mock();r.wait=Mock(return_value=False)
        sort=self.fixture('research-sorting-only.png');menu=self.fixture('starter-research-complete.png')
        r.reader.research_sorting.side_effect=lambda f:f is sort
        r.reader.menu_kind.side_effect=lambda f:'research' if f is menu else None
        r.research_top=Mock(return_value=menu)
        r.capture.screenshot.side_effect=[sort,menu,menu]
        self.assertIs(r.clear_filters(sort),menu)
        r.reader.selected_filter.assert_not_called()
        r.input.tap.assert_called_once_with(round(1853*.40),round(1048*.60),jitter=0)

    def test_research_inventory_returns_to_the_top_before_scanning(self):
        r=self.r;r.reader=Mock();r.wait=Mock(return_value=False)
        frame=self.fixture('starter-research-complete.png')
        r.reader.menu_kind.return_value='research';r.capture.screenshot.return_value=frame
        self.assertIs(r.research_top(frame),frame)
        self.assertEqual(r.input.swipe.call_count,2)
        r.input.tap.assert_not_called()

    def test_builder_camp_gray_check_is_native_and_requires_builder_village(self):
        from coc_bot.progression.construction import controls
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/builder_base/starter-camp-preview.png'))
        self.assertIsNone(controls(frame)['confirm'])
        observed=self.r.construction_controls(frame)
        self.assertEqual(observed['confirm'],(884,330))
        frame[310:354,862:907]=0
        self.assertIsNone(self.r.construction_controls(frame)['confirm'])
        frame[0:100,1740:]=0
        self.assertIsNone(self.r.construction_controls(frame))

    def test_builder_preview_scaling_keeps_its_check_shape_but_rejects_a_cross(self):
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/builder_base/starter-camp-scaled-preview.png'))
        self.assertEqual(self.r.construction_controls(frame)['confirm'],(883,320))
        # Leave the green button and cancel X intact, but replace its check.
        frame[310:330,872:894]=(54,132,39)
        cv2.line(frame,(873,311),(892,329),(180,180,180),5)
        cv2.line(frame,(892,311),(873,329),(180,180,180),5)
        self.assertIsNone(self.r.construction_controls(frame)['confirm'])

    def test_builder_counter_fallback_keeps_all_five_gold_digits(self):
        from coc_bot.builder_base.resources import ResourceReader
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/builder_base/starter-camp-scaled-preview.png'))
        with patch('coc_bot.builder_base.resources.resource_amount',return_value=None):
            values=ResourceReader(BuilderProgressionReader()).balances(frame)
        self.assertEqual(values,{'gold':10446,'elixir':14448,'gems':297})

    def test_two_unknown_resource_counters_never_compare_as_payment_proof(self):
        r=self.r;r.reader=Mock();r.wait=Mock(return_value=False)
        frame=np.zeros((100,100,3),np.uint8)
        row={'name':'Army Camp','cost':12000,'currency':'elixir','point':(80,15)}
        placement={'confirm':(9,9),'cancel':(1,1)}
        r.find_row=Mock(return_value=(row,frame));r.eligibility=Mock(return_value=None)
        r.capture.screenshot.return_value=frame;r.construction_controls=Mock(return_value=placement)
        balances={'gold':None,'elixir':14448}
        r.reader.balances.return_value=balances;r.reader.availability.return_value=(1,1)
        with patch('coc_bot.progression.construction.Construction.locate_space',return_value=placement),\
             patch('coc_bot.builder_base.resources.ResourceReader') as resource:
            resource.return_value.balances.return_value=balances|{'gems':297}
            self.assertEqual(BuilderConstruction(r).start(row,{'balances':balances})['status'],'changed')
        self.assertNotIn('pending',r.state())
        self.assertNotIn((9,9),[v.args for v in r.input.tap.call_args_list])

    def test_wall_quantity_uses_actual_number_glyph_when_ocr_reads_ampersand(self):
        from coc_bot.progression.reader import wall_quantity
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/builder_base/starter-walls-six.png'))
        title=frame[120:154,1436:1714]
        letters=cv2.inRange(cv2.cvtColor(title,cv2.COLOR_BGR2HSV),(35,80,170),(90,255,255))
        self.assertEqual(wall_quantity('Wall x &',letters),6)
        self.assertEqual(wall_quantity('Wall x 6',letters),6)
        self.assertIsNone(wall_quantity('Wall',letters))  # OCR must not drop a visible suffix.
        self.assertIsNone(wall_quantity('Wall x 8',letters))
        self.assertIsNone(wall_quantity('Cannon x &',letters))
        letters[:,80:]=0
        self.assertIsNone(wall_quantity('Wall x &',letters))

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.r=BuilderProgressionRunner(replace(load_config(),data_dir=Path(self.temp.name),builder_base_gold_reserve=0,
            builder_base_elixir_reserve=0,builder_base_builders_reserved=0,upgrade_excluded_names=''),Mock(),Mock(),Mock())

    def fixture(self,name):return cv2.imread(str(Path(__file__).parent/'fixtures/builder_base'/name))

    @unittest.skipUnless(shutil.which('tesseract'),'OCR executable is required')
    def test_archer_shimmer_never_changes_the_verified_unit_price_or_resource(self):
        reader=BuilderProgressionReader()
        for name in ('starter-archer-confirm.png','starter-archer-shimmer.png'):
            frame=self.fixture(name);candidate=Candidate('Sneaky Archer',5000,'elixir',(1,2))
            result=reader.confirmation(frame,candidate)
            self.assertIsNotNone(result);self.assertEqual(result['target_level'],2)
            for c in (Candidate('Night Witch',5000,'elixir',(1,2)),Candidate('Sneaky Archer',500,'elixir',(1,2)),Candidate('Sneaky Archer',5000,'gems',(1,2))):
                self.assertIsNone(reader.confirmation(frame,c))
            frame[350:500,571:702]=0
            self.assertIsNone(reader.confirmation(frame,candidate))

    @unittest.skipUnless(shutil.which('tesseract'),'OCR executable is required')
    def test_locked_rows_prove_the_next_level_and_do_not_become_free_upgrades(self):
        frame=self.fixture('starter-research-complete.png');reader=BuilderProgressionReader()
        rows=reader.rows(frame)
        self.assertEqual([(compact(v['name']),v['target_level'],v['state']) for v in rows],
                         [('ragedbarbarian',3,'future_locked'),('sneakyarcher',3,'future_locked')])
        self.assertTrue(all(v['cost'] is None and v['currency'] is None for v in rows))
        self.assertEqual(self.r.menu_gems(frame),297)

    def test_hall_advancement_requires_a_complete_verified_max_inventory(self):
        ready={'complete':True,'unfiltered':True,'unknown':False,'busy':False,'hall_verified':True,'rows':[]}
        self.assertEqual(hall_blockers(ready),[])
        for field,value in [('complete',False),('unfiltered',False),('unknown',True),('busy',True),('hall_verified',False)]:
            with self.subTest(field=field):self.assertTrue(hall_blockers(ready|{field:value}))
        self.assertTrue(hall_blockers(ready|{'rows':[{'name':'Wall','new':True,'cost':0,'currency':'free'}]}))
        self.assertTrue(hall_blockers(ready|{'rows':[{'name':'Cannon','cost':999999999,'currency':'gold'}]}))

    def test_hall_proof_is_read_while_visible_not_after_scrolling_it_away(self):
        r=self.r;r.reader=Mock();r.wait=Mock(return_value=False)
        first=np.full((100,100,3),30,np.uint8);bottom=np.full_like(first,80)
        hall={'name':'Builder Hall','new':False,'level':None,'cost':30000,'currency':'gold',
              'target_level':3,'point':(80,20),'box':(73,12,27,10)}
        other={'name':'Cannon','new':False,'level':None,'cost':None,'currency':None,
               'state':'maxed','point':(80,30),'box':(73,23,27,10)}
        r.clear_filters=Mock(return_value=first)
        r.reader.menu_kind.return_value='buildings';r.reader.availability.return_value=(1,1)
        r.reader.balances.return_value={'gold':500,'elixir':500}
        r.reader.rows.side_effect=lambda frame:[hall] if frame[0,0,0]==30 else [other]
        r.capture.screenshot.side_effect=[first,bottom,bottom]
        result=r.scan(first)
        self.assertTrue(result['complete']);self.assertTrue(result['hall_verified'])
        self.assertEqual(result['hall'],2);self.assertEqual(r.capture.screenshot.call_count,3)
        r.input.tap.assert_not_called()

    def test_lab_priority_and_new_building_order_apply_to_the_actual_preview(self):
        r=self.r;r.reader=Mock();frame=np.zeros((10,10,3),np.uint8)
        r.reader.home.return_value=False;r.reader.availability.return_value=(1,1)
        r.open_menu=Mock(return_value=frame);r.close=Mock()
        lab={'name':'Star Laboratory','new':False,'cost':5000,'currency':'elixir','point':(1,2)}
        new={'name':'Cannon','new':True,'cost':1000,'currency':'gold','point':(3,4)}
        old={'name':'Gold Mine','new':False,'cost':500,'currency':'gold','point':(5,6)}
        inventory={'complete':True,'unknown':False,'rows':[old,new,lab],
                   'balances':{'gold':3000,'elixir':6000}}
        r.scan=Mock(return_value=inventory)
        self.assertEqual(r.run('buildings')['selected']['name'],'Star Laboratory')
        inventory['balances']['elixir']=0
        self.assertEqual(r.run('buildings')['selected']['name'],'Cannon')
        r.input.tap.assert_not_called()

    def pending_research(self):
        return {'kind':'research','name':'Sneaky Archer','cost':5000,'currency':'elixir',
                'free_before':1,'active_before':0,'target_level':2,'balances_before':{'elixir':8053},'gems_before':297}

    def test_completed_short_research_can_reconcile_without_another_payment(self):
        r=self.r;r.reader=Mock();r.reader.active_names.return_value=[];r.reader.availability.return_value=(1,1)
        r.reader.rows.return_value=[{'name':'Sneaky Archer','target_level':3}]
        r.reader.balances.return_value={'elixir':3053};r.menu_gems=Mock(return_value=297)
        state={'pending':self.pending_research()}
        self.assertTrue(r._verify_pending(state,'research',object()))
        self.assertNotIn('pending',read(r.path));self.assertEqual(state['last_completed']['level_after'],2)
        r.input.tap.assert_not_called()

    def test_unknown_gems_or_unchanged_level_cannot_clear_short_research(self):
        r=self.r;r.reader=Mock();r.reader.active_names.return_value=[];r.reader.availability.return_value=(1,1)
        r.reader.rows.return_value=[{'name':'Sneaky Archer','target_level':3}]
        r.reader.balances.return_value={'elixir':3053};r.menu_gems=Mock(return_value=None)
        state={'pending':self.pending_research()}
        self.assertFalse(r._verify_pending(state,'research',object()));self.assertIn('pending',state)
        r.menu_gems.return_value=297;r.reader.rows.return_value=[{'name':'Sneaky Archer','target_level':2}]
        self.assertFalse(r._verify_pending(state,'research',object()))
        r.input.tap.assert_not_called()

    def test_paid_construction_recovery_only_reads_the_receipt(self):
        r=self.r;r.reader=Mock()
        write(r.path,{'pending':{'kind':'construction','row':{'name':'Archer Tower','cost':12000,'currency':'gold'},
            'before':{'gold':17000,'elixir':8053,'gems':297}}})
        with patch('coc_bot.progression.construction.controls',return_value=None),\
             patch('coc_bot.builder_base.resources.ResourceReader') as resource:
            resource.return_value.balances.return_value={'gold':5000,'elixir':8053,'gems':297}
            self.assertEqual(BuilderConstruction(r).reconcile()['status'],'started')
        r.input.tap.assert_not_called();self.assertNotIn('pending',read(r.path))

    def test_free_walls_need_an_independent_quantity_decrement(self):
        r=self.r;r.reader=Mock();r.open_menu=Mock();r.scan=Mock();r.find_row=Mock(return_value=({},object()))
        pending={'kind':'construction','row':{'name':'Wall','cost':0,'currency':'free','quantity':10},
                 'before':{'gold':5000,'elixir':8053,'gems':297}}
        with patch('coc_bot.progression.construction.controls',return_value=None),\
             patch('coc_bot.builder_base.resources.ResourceReader') as resource:
            resource.return_value.balances.return_value=pending['before']
            for remaining,status in ((8,'needs_review'),(9,'started')):
                write(r.path,{'pending':pending})
                row={'name':'Wall','new':True,'quantity':remaining,'currency':'free','cost':0}
                r.scan.return_value={'complete':True,'rows':[row]};r.reader.rows.return_value=[row]
                self.assertEqual(BuilderConstruction(r).reconcile()['status'],status)
            write(r.path,{'pending':pending})
            r.scan.return_value={'complete':True,'rows':[row]};r.reader.rows.return_value=[row|{'quantity':8}]
            self.assertEqual(BuilderConstruction(r).reconcile()['status'],'needs_review')
        r.input.tap.assert_not_called()
