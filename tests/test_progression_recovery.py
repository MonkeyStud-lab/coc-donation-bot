"""Known army-page recovery and explicitly enabled resource-only removals."""
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase,skipUnless
from unittest.mock import Mock,patch
import cv2
import numpy as np
import shutil

from coc_bot.progression.preparation import army_page,army_editor_close_button
from coc_bot.progression.space import obstacle,SpaceMaker,home_gems,free_builders


class ArmyRecoveryTests(TestCase):
    def test_one_edit_can_confirm_from_two_complete_card_tables_when_header_is_unreadable(self):
        from coc_bot.progression.preparation import ArmyPreparation
        from coc_bot.attack.army import ArmyCard
        prep=ArmyPreparation.__new__(ArmyPreparation);prep.stop=None;prep.catalog=Mock();prep.army_references={'barbarian'}
        frame=np.zeros((1048,1853,3),np.uint8);prep.frame=Mock(return_value=frame)
        cards=[ArmyCard('card',(804,278,148,151),'barbarian','troop',19)]
        with patch('coc_bot.progression.preparation.army_editor_close_button',return_value=(1792,95)),\
             patch('coc_bot.progression.preparation.capacity',return_value=None),\
             patch('coc_bot.progression.preparation.read_army',return_value=cards):
            _,observed,space=prep.observe(expected_edit=({'barbarian':19},(19,30)))
        self.assertEqual(space,(19,30));self.assertTrue(observed[0].stable)
        self.assertEqual(prep.frame.call_count,2)
        with patch('coc_bot.progression.preparation.army_page',return_value=False):
            with self.assertRaisesRegex(ValueError,'editor changed'):prep.observe()

    def test_edit_proof_never_repairs_a_wrong_missing_or_unidentified_card(self):
        from coc_bot.progression.preparation import ArmyPreparation
        from coc_bot.attack.army import ArmyCard
        frame=np.zeros((1048,1853,3),np.uint8)
        card=ArmyCard('card',(804,278,148,151),'barbarian','troop',19)
        for values in ([card],[ArmyCard('card',card.box,'barbarian','troop',None)],
                       [card,ArmyCard('extra',(952,278,148,151),None,'unknown',1)]):
            prep=ArmyPreparation.__new__(ArmyPreparation);prep.stop=None;prep.catalog=Mock();prep.army_references={'barbarian'}
            prep.frame=Mock(return_value=frame)
            with self.subTest(values=values),\
                 patch('coc_bot.progression.preparation.army_editor_close_button',return_value=(1792,95)),\
                 patch('coc_bot.progression.preparation.capacity',return_value=None),\
                 patch('coc_bot.progression.preparation.read_army',return_value=values):
                with self.assertRaises(ValueError):prep.observe(expected_edit=({'barbarian':18},(18,30)))

    def test_readable_capacity_still_vetoes_an_inconsistent_edit(self):
        from coc_bot.progression.preparation import ArmyPreparation
        prep=ArmyPreparation.__new__(ArmyPreparation);prep.stop=None;prep.catalog=Mock()
        prep.frame=Mock(return_value=np.zeros((1048,1853,3),np.uint8))
        with patch('coc_bot.progression.preparation.army_editor_close_button',return_value=(1792,95)),\
             patch('coc_bot.progression.preparation.capacity',return_value=(20,30)):
            with self.assertRaisesRegex(ValueError,'contradicts'):prep.observe(expected_edit=({'barbarian':19},(19,30)))

    @skipUnless(shutil.which('tesseract'),'Tesseract required for native army badges')
    def test_three_digit_badges_distinguish_two_from_four(self):
        from coc_bot.attack.army import read_badge
        root=Path(__file__).parent/'fixtures/progression'
        for name,count in [('army-dimmed-165-175.png',134),('army-dimmed-161-175.png',130),
                           ('army-dimmed-151-175.png',120),('army-dimmed-143-175.png',112)]:
            with self.subTest(name=name):
                frame=cv2.imread(str(root/name))
                self.assertEqual(read_badge(frame[278:429,804:952]),count)

    @skipUnless(shutil.which('tesseract'),'Tesseract required for native army headings')
    def test_real_dimmed_picker_keeps_its_capacity_but_a_covering_popup_does_not(self):
        from coc_bot.progression.preparation import capacity,picker_editor_visible
        root=Path(__file__).parent/'fixtures/progression'
        frame=cv2.imread(str(root/'army-dimmed-165-175.png'))
        self.assertTrue(picker_editor_visible(frame))
        self.assertEqual(capacity(frame),(165,175));self.assertTrue(army_page(frame))
        changed=cv2.imread(str(root/'army-dimmed-161-175.png'))
        self.assertEqual(capacity(changed),(161,175));self.assertTrue(army_page(changed))
        changed=cv2.imread(str(root/'army-dimmed-151-175.png'))
        self.assertEqual(capacity(changed),(151,175));self.assertTrue(army_page(changed))
        # Only the drawer's safe backdrop dismissal may undim this X.
        self.assertIsNone(army_editor_close_button(frame))
        covered=cv2.imread(str(root/'army-covered-inactivity.png'))
        self.assertFalse(picker_editor_visible(covered));self.assertIsNone(capacity(covered))
        self.assertFalse(army_page(covered));self.assertIsNone(army_editor_close_button(covered))
        for area in ((0,65,650,145),(0,595,1853,1048)):
            bad=frame.copy();x,y,u,v=area;bad[y:v,x:u]=0
            self.assertFalse(picker_editor_visible(bad));self.assertFalse(army_page(bad))

    @skipUnless(shutil.which('tesseract'),'Tesseract required for native army headings')
    def test_cleanup_dismisses_verified_picker_before_closing_the_army_editor(self):
        from coc_bot.progression.preparation import ArmyPreparation
        root=Path(__file__).parent/'fixtures/progression'
        picker=cv2.imread(str(root/'army-dimmed-165-175.png'))
        editor=cv2.imread(str(root/'army-editor.png'))
        prep=ArmyPreparation.__new__(ArmyPreparation);prep.stop=lambda:False;prep.s=Mock();prep.tap=Mock()
        prep.frame=Mock(side_effect=[picker,editor,editor,editor])
        with patch('coc_bot.progression.preparation.read_info',return_value=None),\
             patch('coc_bot.progression.preparation.direct_match_button',return_value=None),\
             patch('coc_bot.progression.home.ensure_home',return_value=True):prep.close()
        self.assertEqual(prep.tap.call_count,2)
        self.assertEqual(prep.tap.call_args_list[0].args[0],(round(picker.shape[1]*.5),round(picker.shape[0]*.17)))

    def test_capacity_ocr_cannot_override_a_contrary_native_read(self):
        from coc_bot.progression.preparation import capacity
        frame=np.zeros((1048,1853,3),np.uint8)
        with patch('coc_bot.progression.preparation.army_editor_close_button',return_value=(1792,95)),\
             patch('coc_bot.progression.preparation._capacity_area',side_effect=[None,None,(151,175),None,None,None,None,None]),\
             patch('coc_bot.progression.preparation._ocr_capacity_area',side_effect=[(150,175),None]*3):
            self.assertIsNone(capacity(frame))

    def test_home_star_bonus_needs_its_title_delivery_message_and_enabled_okay(self):
        from coc_bot.vision.notices import home_star_bonus_button
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/progression/home-star-bonus.png'))
        self.assertIsNotNone(home_star_bonus_button(frame))
        for box in ((605,80,1280,145),(676,439,1528,478),(856,863,1017,916)):
            bad=frame.copy();x,y,u,v=box;bad[y:v,x:u]=0
            self.assertIsNone(home_star_bonus_button(bad))
        self.assertIsNone(home_star_bonus_button((frame*.4).astype(np.uint8)))

    def test_home_bonus_rechecks_before_input_is_bounded_and_obeys_stop(self):
        from coc_bot.progression.home import recover_home_bonus
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/progression/home-star-bonus.png'))
        nav=Mock();nav._stopping.return_value=False;nav.capture.screenshot.return_value=frame
        self.assertTrue(recover_home_bonus(nav,frame));self.assertTrue(recover_home_bonus(nav,frame))
        self.assertFalse(recover_home_bonus(nav,frame));self.assertEqual(nav.input.tap.call_count,2)
        self.assertFalse(recover_home_bonus(nav,np.zeros_like(frame)))
        self.assertTrue(recover_home_bonus(nav,frame))
        nav._stopping.return_value=True
        self.assertFalse(recover_home_bonus(nav,frame));self.assertEqual(nav.input.tap.call_count,3)

    def test_home_confirmation_can_acknowledge_star_bonus_before_home_anchors(self):
        from coc_bot.progression.home import ensure_home
        bonus=cv2.imread(str(Path(__file__).parent/'fixtures/progression/home-star-bonus.png'))
        home=np.zeros_like(bonus);nav=Mock();nav._stopping.return_value=False
        nav.capture.screenshot.side_effect=[bonus,bonus,home,home]
        nav.classifier._clan_chat_anchor_visible.return_value=False
        nav.classifier.auxiliary_page.return_value=None
        nav.classifier.find_reload_game_button.return_value=None
        nav.classifier.looks_like_blocking_popup.return_value=False
        with patch('coc_bot.progression.home.home_build_control_visible',return_value=True),\
             patch('coc_bot.progression.home._white_label',return_value=''),\
             patch('coc_bot.progression.home.interrupted_sleep',return_value=False):
            self.assertTrue(ensure_home(nav))
        nav.input.tap.assert_called_once()

    def test_native_picker_levels_are_read_without_unlocking_gray_cards(self):
        from coc_bot.progression.preparation import picker_boxes,picker_level
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/progression/picker-native-levels.png'))
        observed=[picker_level(frame[y:y+h,x:x+w]) for x,y,w,h in picker_boxes(frame)]
        self.assertEqual(observed,[8,8,6,8,6,None,None,None,None,8,7,7,1,None,None,None,None,None])

    @skipUnless(shutil.which('tesseract'),'Tesseract required for dimmed picker heading')
    def test_empty_wide_picker_keeps_capacity_and_requires_its_dimmed_heading(self):
        from coc_bot.progression.preparation import capacity,army_page,picker_boxes
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/progression/army-empty-picker.png'))
        self.assertEqual(capacity(frame),(0,250))
        self.assertGreaterEqual(len(picker_boxes(frame)),3)
        self.assertTrue(army_page(frame))
        frame[87:130,292:459]=0
        self.assertFalse(army_page(frame))

    def test_missing_info_one_requires_the_visible_isolated_yellow_numeral(self):
        from coc_bot.progression.troop_info import read_info
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/progression/healer-info-level-one.png'))
        def label(image,**_):return 'Healer Level' if image.shape[1]>500 else 'Housing space:'
        with patch('coc_bot.progression.troop_info.text',side_effect=label):
            self.assertEqual(read_info(frame,expected_level=1)['level'],1)
            self.assertIsNone(read_info(frame,expected_level=2))
            bad=frame.copy();bad[48:90,1080:1100]=0
            self.assertIsNone(read_info(bad,expected_level=1))
            # Two visible 1s must not become level 1 when OCR loses both.
            bad=frame.copy();bad[48:90,1099:1119]=frame[48:90,1080:1100]
            self.assertIsNone(read_info(bad,expected_level=1))

    def test_empty_wide_army_reads_zero_capacity_and_only_the_troop_edit_prompt(self):
        from coc_bot.progression.preparation import capacity,army_page,empty_army_button
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/progression/army-empty-wide.png'))
        self.assertEqual(capacity(frame),(0,250))
        with patch('coc_bot.progression.preparation._white_label',return_value=''):
            self.assertTrue(army_page(frame))
            self.assertEqual(empty_army_button(frame),(1304,356))
            frame[343:370,1226:1383]=0
            self.assertIsNone(empty_army_button(frame))

    def test_empty_army_opens_picker_after_two_matching_observations(self):
        from coc_bot.progression.preparation import ArmyPreparation
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/progression/army-empty-wide.png'))
        picker=np.zeros_like(frame)
        prep=ArmyPreparation.__new__(ArmyPreparation);prep.stop=lambda:False;prep.tap=Mock();prep.catalog=Mock()
        prep.frame=Mock(side_effect=[frame,picker,picker]);prep.learn_unlocks=Mock(return_value=picker)
        unlocks={'barbarian':{'level':1,'point':(123,456)}}
        with patch('coc_bot.progression.preparation._white_label',return_value=''),\
             patch('coc_bot.progression.preparation.army_page',return_value=True),\
             patch('coc_bot.progression.preparation.picker_unlocks',return_value=unlocks):
            self.assertEqual(prep.unlocked(frame,[]),unlocks)
        prep.tap.assert_called_once_with((1304,356))

    def test_empty_army_navigation_stops_if_capacity_changed(self):
        from coc_bot.progression.preparation import ArmyPreparation
        frame=np.zeros((1048,1853,3),np.uint8)
        prep=ArmyPreparation.__new__(ArmyPreparation);prep.stop=lambda:False;prep.tap=Mock();prep.frame=Mock(return_value=frame)
        with patch('coc_bot.progression.preparation.empty_army_button',return_value=(1304,356)),\
             patch('coc_bot.progression.preparation.capacity',side_effect=[(1,250),(0,250)]):
            with self.assertRaisesRegex(ValueError,'not verified'):prep.unlocked(frame,[])
        prep.tap.assert_not_called()

    def test_battle_menu_tip_requires_caption_and_both_corners_and_is_bounded(self):
        from coc_bot.vision.notices import battle_menu_tip_button
        from coc_bot.progression.home import recover_home_overlay
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/progression/battle-menu-tip.png'))
        self.assertIsNotNone(battle_menu_tip_button(frame))
        for box in ((835,738,1268,825),(810,697,845,726),(1267,839,1288,867)):
            bad=frame.copy();x,y,u,v=box;bad[y:v,x:u]=0
            self.assertIsNone(battle_menu_tip_button(bad))
        self.assertIsNone(battle_menu_tip_button((frame*.4).astype(np.uint8)))
        nav=Mock();nav.capture.screenshot.return_value=frame;nav._stopping.return_value=False
        self.assertTrue(recover_home_overlay(nav,frame));self.assertTrue(recover_home_overlay(nav,frame))
        self.assertFalse(recover_home_overlay(nav,frame));self.assertEqual(nav.input.tap.call_count,2)

    def test_army_open_recovers_known_tip_before_reading_edit_control(self):
        from coc_bot.progression.preparation import ArmyPreparation
        prep=ArmyPreparation.__new__(ArmyPreparation);prep.stop=lambda:False;prep.s=Mock();prep.tap=Mock()
        tip=np.zeros((1048,1853,3),np.uint8);menu=tip.copy();army=tip.copy()
        prep.frame=Mock(side_effect=[tip,menu,army])
        with patch('coc_bot.progression.home.recover_home_overlay',side_effect=[True,False]),\
             patch('coc_bot.progression.preparation.army_page',side_effect=lambda f,*_:f is army),\
             patch('coc_bot.progression.preparation.edit_army_button',return_value=(100,100)) as edit:
            self.assertIs(prep.open(),army)
        edit.assert_called_once_with(menu,prep.stop)
        prep.tap.assert_called_once_with((100,100))

    def test_town_hall_waits_for_consecutive_readings_without_guessing(self):
        from coc_bot.progression.preparation import ArmyPreparation
        frame=np.zeros((1048,1853,3),np.uint8)
        row={'name':'Town Hall','currency':'gold','cost':4500000,'box':[1358,759,495,117]}
        for levels,expected in (([None,13,13],12),([13,14,13,14,13],None),([3,3,3,3,3],None)):
            prep=ArmyPreparation.__new__(ArmyPreparation);prep.s=Mock();prep.stop=lambda:False
            prep.s.config.account_town_hall=12
            prep.frame=Mock(return_value=frame)
            runner=Mock();runner.open_menu.return_value=frame;runner.clear_filters.return_value=frame
            runner.reader.rows.return_value=[row];runner.reader.menu_kind.return_value='buildings'
            runner.reader.target_level.side_effect=levels;runner.reader.detail_close.return_value=None
            with patch('coc_bot.progression.preparation.ProgressionRunner',return_value=runner):
                if expected is None:
                    with self.assertRaisesRegex(ValueError,'badge could not be verified'):prep.hall()
                else:self.assertEqual(prep.hall(),expected)
            runner.input.tap.assert_not_called();prep.s.input.tap.assert_not_called()

    @skipUnless(shutil.which('tesseract'),'Tesseract required for Town Hall fixture')
    def test_actual_th12_next_level_badge_reads_thirteen(self):
        from coc_bot.progression.reader import ProgressionReader
        from coc_bot.upgrades.vision import compact
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/progression/hall-twelve-list.png'))
        reader=ProgressionReader();row=next(r for r in reader.rows(frame) if compact(r['name'])=='townhall')
        self.assertEqual(reader.target_level(frame,row),13)
        # Even when ordinary OCR shortens the label, the complete glyph read
        # must preserve both visible characters.
        with patch('coc_bot.progression.reader.text',return_value='3'):
            self.assertEqual(reader.target_level(frame,row),13)
        with patch('coc_bot.upgrades.digits.read_digits',return_value=None),\
             patch('coc_bot.progression.reader.text',return_value='3'):
            self.assertIsNone(reader.target_level(frame,row))

    @skipUnless(shutil.which('tesseract'),'Tesseract required for Town Hall fixture')
    def test_badge_stays_readable_when_a_thumbnail_shadow_touches_its_border(self):
        from coc_bot.progression.reader import ProgressionReader
        from coc_bot.upgrades.vision import compact
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/progression/hall-twelve-list-badge-connected.png'))
        reader=ProgressionReader();row=next(r for r in reader.rows(frame) if compact(r['name'])=='townhall')
        with patch('coc_bot.progression.reader.text',return_value='3'):
            self.assertEqual(reader.target_level(frame,row),13)

    def test_welcome_back_requires_both_text_anchors_and_enabled_button(self):
        from coc_bot.vision.notices import welcome_back_button
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/accounts/welcome-after-defense.png'))
        self.assertIsNotNone(welcome_back_button(frame))
        bad=frame.copy();bad[90:160,590:1270]=0
        self.assertIsNone(welcome_back_button(bad))
        bad=frame.copy();bad[830:925,840:1055]=128
        self.assertIsNone(welcome_back_button(bad))
        self.assertIsNone(welcome_back_button((frame*.4).astype(np.uint8)))

    def test_inspected_heading_survives_ocr_error_without_loosening_army_counts(self):
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/progression/army-heading-ocr.png'))
        with patch('coc_bot.progression.preparation._white_label',return_value='myarny'):
            self.assertTrue(army_page(frame))
            point=army_editor_close_button(frame)
            self.assertIsNotNone(point)
            frame[210:270,540:840]=0
            self.assertFalse(army_page(frame))
            self.assertEqual(army_editor_close_button(frame),point)
            # Dimmed/covered controls never authorize closing through a popup.
            self.assertIsNone(army_editor_close_button((frame*.4).astype(np.uint8)))
            frame[85:140,740:1150]=0
            self.assertIsNone(army_editor_close_button(frame))

    def test_account_handoff_closes_known_army_page_before_using_home_anchors(self):
        from coc_bot.accounts.navigation import AccountNavigator
        nav=AccountNavigator.__new__(AccountNavigator)
        nav.stop=lambda:False;nav.session=Mock();nav.tap=Mock()
        frames=[SimpleNamespace(name=n,shape=(1048,1853,3))
                for n in ('army','army','attack','home','menu')]
        nav.frame=Mock(side_effect=frames)
        nav.session.navigator.classifier._clan_chat_anchor_visible.return_value=False
        nav.session.navigator.classifier._open_chat_icon_visible.return_value=True
        def anchor(frame,key,*_):return (1,1) if frame.name=='menu' and key in ('my_profile','menu_close') else None
        with patch('coc_bot.progression.home.recover_home_overlay',return_value=False),\
             patch('coc_bot.accounts.navigation.find',side_effect=anchor),\
             patch('coc_bot.progression.preparation.army_editor_close_button',
                   side_effect=lambda f,*_:(1792,95) if f.name=='army' else None),\
             patch('coc_bot.vision.battle_menu.direct_match_button',
                   side_effect=lambda f,**_:(300,750) if f.name=='attack' else None),\
             patch('coc_bot.vision.battle_menu.home_build_control_visible',side_effect=lambda f:f.name=='home'):
            nav.menu()
        self.assertEqual(nav.tap.call_args_list[0].args,((1792,95),))
        self.assertEqual(nav.tap.call_count,3)


class SeasonalRemovalTests(TestCase):
    @skipUnless(shutil.which('tesseract'),'Tesseract required for removal-label fixtures')
    def test_live_seasonal_price_and_builder_layouts(self):
        folder=Path(__file__).parent/'fixtures/progression'
        frame=cv2.imread(str(folder/'seasonal-remove.png'))
        self.assertEqual(free_builders(frame),(1,5))
        from coc_bot.progression.reader import balance_amount
        from coc_bot.upgrades.vision import crop
        self.assertEqual(balance_amount(crop(frame,(.82,.103,.958,.14))),28100969)
        self.assertIsNone(obstacle(frame))
        value=obstacle(frame,allow_seasonal=True)
        self.assertEqual((value['name'],value['currency'],value['cost']),('Kumquat Tree','elixir',888))
        frame=cv2.imread(str(folder/'seasonal-stump-remove.png'))
        self.assertIsNone(obstacle(frame))
        value=obstacle(frame,allow_seasonal=True)
        self.assertEqual((value['name'],value['currency'],value['cost']),('Curious Stump','elixir',2026))
        # A missing/covered price must not be filled from the known fixture.
        frame[745:790,850:1000]=0
        self.assertIsNone(obstacle(frame,allow_seasonal=True))
        frame=cv2.imread(str(folder/'builders-low-hud.png'))
        self.assertEqual(free_builders(frame),(2,2))

    def test_gem_receipt_tracks_the_gem_icon_not_the_dark_elixir_row(self):
        for name,expected in (('gems-high-hud.png',698),('gems-low-hud.png',244)):
            frame=cv2.imread(str(Path(__file__).parent/'fixtures/progression'/name))
            self.assertEqual(home_gems(frame),expected)
            frame[:320,1780:]=0
            self.assertIsNone(home_gems(frame))

    def test_gem_receipt_keeps_leading_digits_on_a_larger_balance(self):
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/progression/gems-high-hud.png'))
        # Reuse the actual outlined 6 glyph to exercise a four-digit balance
        # extending left of the former three-digit crop. No font is synthesized.
        frame[255:286,1676:1698]=frame[255:286,1698:1720].copy()
        self.assertEqual(home_gems(frame),6698)

    def test_seasonal_consent_still_requires_remove_and_verified_nonpremium_price(self):
        frame=np.zeros((1048,1853,3),np.uint8)
        with patch('coc_bot.progression.space.home_build_control_visible',return_value=True),\
             patch('coc_bot.progression.space.selected_title',return_value='Clashmas Tree'),\
             patch('coc_bot.progression.space.text',return_value='Remove') as label,\
             patch('coc_bot.progression.space.resource_amount',return_value=10000),\
             patch('coc_bot.progression.space.currency',return_value='elixir') as currency:
            self.assertIsNone(obstacle(frame))
            self.assertEqual(obstacle(frame,allow_seasonal=True)['name'],'Clashmas Tree')
            for other in ('gems',None,'dark_elixir','shovel'):
                currency.return_value=other
                self.assertIsNone(obstacle(frame,allow_seasonal=True))
            currency.return_value='elixir';label.return_value='Stash'
            self.assertIsNone(obstacle(frame,allow_seasonal=True))

    def runner(self):
        r=Mock();r.config=SimpleNamespace(progression_clear_obstacles=True,
            progression_clear_seasonal_obstacles=True,upgrade_builders_reserved=0,
            upgrade_gold_reserve=0,upgrade_elixir_reserve=0)
        r.capture.screenshot.return_value=np.zeros((1048,1853,3),np.uint8)
        r.stopped.return_value=False;r.wait.return_value=False;r.stop=None
        r.state.return_value={}
        return r

    def test_one_payment_requires_receipt_and_no_gem_loss(self):
        selected={'name':'Clashmas Tree','currency':'elixir','cost':1000,'point':(926,828)}
        for after_gems in (244,243,None):
            r=self.runner()
            r.config.upgrade_builders_reserved=2
            with self.subTest(after_gems=after_gems),\
                 patch('coc_bot.progression.space.obstacle',side_effect=[selected,selected,None]),\
                 patch('coc_bot.progression.space.free_builders',return_value=(0,2)) as builders,\
                 patch('coc_bot.progression.space.balance_amount',side_effect=[2000,1000]),\
                 patch('coc_bot.progression.space.home_gems',side_effect=[244,after_gems]),\
                 patch('coc_bot.progression.space.write_json'):
                result=SpaceMaker(r).selected()
            self.assertEqual(result['status'],'making_room' if after_gems==244 else 'needs_review')
            self.assertEqual(r.input.tap.call_count,1)
            self.assertEqual(bool(r.state.return_value.get('pending')),after_gems!=244)
            builders.assert_not_called()

    def test_changed_selection_or_unknown_gems_never_sends_payment(self):
        selected={'name':'Clashmas Tree','currency':'elixir','cost':1000,'point':(926,828)}
        r=self.runner()
        with patch('coc_bot.progression.space.obstacle',side_effect=[selected,None]):
            self.assertEqual(SpaceMaker(r).selected()['status'],'changed')
        r.input.tap.assert_not_called()
        with patch('coc_bot.progression.space.obstacle',return_value=selected),\
             patch('coc_bot.progression.space.free_builders',return_value=(1,2)),\
             patch('coc_bot.progression.space.balance_amount',return_value=2000),\
             patch('coc_bot.progression.space.home_gems',return_value=None):
            self.assertEqual(SpaceMaker(r).selected()['status'],'waiting')
        r.input.tap.assert_not_called()

    def test_obstacle_search_stops_if_a_map_selection_opens_a_menu(self):
        r=self.runner()
        with patch('coc_bot.progression.space.candidates',return_value=[(700,400),(850,500)]),\
             patch('coc_bot.progression.space.home_build_control_visible',side_effect=[True,True,False]),\
             patch.object(SpaceMaker,'selected',return_value={'status':'not_obstacle'}):
            self.assertEqual(SpaceMaker(r).run()['status'],'blocked')
        self.assertEqual(r.input.tap.call_count,1)
