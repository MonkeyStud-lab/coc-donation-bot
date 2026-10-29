"""Account isolation, role boundaries and interrupted-switch recovery; no device."""
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch
import hashlib
import json
import shutil
import tempfile
import yaml
import cv2

from coc_bot.accounts.store import AccountStore, backup, apply_roles, ROLES
from coc_bot.config import load_config, project_root
from coc_bot.control.service import ControlService
from coc_bot.accounts.service import Accounts


class AccountsTests(TestCase):
    def test_switch_allows_defense_to_finish_after_the_old_one_minute_limit(self):
        from coc_bot.accounts.navigation import AccountNavigator
        import numpy as np
        s=Mock();n=AccountNavigator(s)
        n.saved_cards=Mock(return_value=[{'name':'Other','hall':10}])
        n.card_point=Mock(return_value=(100,100));n.tap=Mock();n.button=Mock()
        n.frame=Mock(return_value=np.zeros((1048,1853,3),np.uint8))
        n.identity=Mock(return_value={'tag':'#PYLQG'})
        with patch('coc_bot.accounts.navigation.time.monotonic',side_effect=[0,65,66]),\
             patch('coc_bot.accounts.navigation.interrupted_sleep',return_value=False),\
             patch('coc_bot.progression.home.recover_home_overlay',side_effect=[True,False]),\
             patch('coc_bot.vision.battle_menu.home_build_control_visible',return_value=True):
            result=n.switch({'selector':'Other','tag':'#PYLQG'})
        self.assertEqual(result,{'tag':'#PYLQG','hall':10})
        n.identity.assert_called_once();n.tap.assert_called_once_with((100,100))

    def test_account_load_calendar_claims_only_the_free_native_reward(self):
        from coc_bot.progression.home import recover_home_overlay
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/builder_base/daily-reward.png'))
        nav=Mock();nav._stopping.return_value=False;nav.capture.screenshot.return_value=frame
        self.assertTrue(recover_home_overlay(nav,frame))
        nav.input.tap.assert_called_once_with(670,440,jitter=0)
        claimed=cv2.imread(str(Path(__file__).parent/'fixtures/builder_base/daily-reward-claimed.png'))
        nav.capture.screenshot.return_value=claimed;nav.input.tap.reset_mock()
        self.assertTrue(recover_home_overlay(nav,claimed))
        nav.input.tap.assert_called_once_with(1565,150,jitter=0)

    def test_completed_defense_requires_native_headers_damage_summary_and_return_card(self):
        from coc_bot.vision.notices import defense_results_return_button
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/accounts/defense-results.png'))
        self.assertEqual(defense_results_return_button(frame),(123,933))
        for x0,y0,x1,y1 in ((580,90,715,125),(1135,90,1270,125),(840,260,1015,300),(20,830,225,1035)):
            changed=frame.copy();changed[y0:y1,x0:x1]=0
            self.assertIsNone(defense_results_return_button(changed))
        self.assertIsNone(defense_results_return_button((frame*.5).astype('uint8')))
        battle=cv2.imread(str(Path(__file__).parent/'fixtures/builder_base/controls-17.png'))
        self.assertIsNone(defense_results_return_button(battle))

    def test_defense_return_observes_stop_before_tapping(self):
        from coc_bot.progression.home import recover_home_overlay
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/accounts/defense-results.png'))
        nav=Mock();nav._stopping.return_value=True
        self.assertFalse(recover_home_overlay(nav,frame));nav.input.tap.assert_not_called()

    def test_profile_scroll_uses_verified_page_strip_instead_of_hero_gallery(self):
        from coc_bot.accounts.navigation import AccountNavigator
        import numpy as np
        nav=AccountNavigator.__new__(AccountNavigator);nav.stop=lambda:False
        nav.session=Mock();nav.input=Mock();nav.menu=Mock();nav.button=Mock()
        nav.frame=Mock(return_value=np.zeros((1048,1853,3),np.uint8))
        with patch('coc_bot.accounts.navigation.read_tag',side_effect=[None,None,None]+['#PYLQG']*4),\
             patch('coc_bot.accounts.navigation.find',return_value=(1,1)),\
             patch('coc_bot.accounts.navigation.read_name',return_value='Example'),\
             patch('coc_bot.accounts.navigation.profile_scroll_point',return_value=(1000,750)),\
             patch('coc_bot.accounts.navigation.profile_strip_still_visible',return_value=True),\
             patch('coc_bot.accounts.navigation.profile_uncovered',return_value=True),\
             patch('coc_bot.progression.home.recover_home_overlay',return_value=False),\
             patch('coc_bot.accounts.navigation.interrupted_sleep',return_value=False):
            self.assertEqual(nav.identity()['tag'],'#PYLQG')
        nav.input.swipe.assert_called_once_with(1000,750,1000,970,duration_ms=120)

    def test_native_profile_strips_reframe_as_the_hero_gallery_scrolls(self):
        from coc_bot.accounts.navigation import profile_scroll_point,profile_strip_still_visible,profile_uncovered
        import numpy as np
        root=Path(__file__).parent/'fixtures/accounts'
        first_frame=cv2.imread(str(root/'profile-hero-gallery.png'));after_frame=cv2.imread(str(root/'profile-hero-below.png'))
        first=profile_scroll_point(first_frame)
        after=profile_scroll_point(after_frame)
        self.assertIsNotNone(first);self.assertIsNotNone(after)
        self.assertGreater(first[1],710);self.assertLess(after[1],690)
        self.assertTrue(profile_strip_still_visible(first_frame,first))
        self.assertTrue(profile_strip_still_visible(after_frame,after))
        self.assertTrue(profile_uncovered(first_frame));self.assertTrue(profile_uncovered(after_frame))
        self.assertFalse(profile_uncovered((first_frame*.5).astype(np.uint8)))
        self.assertFalse(profile_strip_still_visible(np.zeros_like(first_frame),first))
        self.assertIsNone(profile_scroll_point(np.zeros((1048,1853,3),np.uint8)))

    def test_profile_reload_does_not_authorize_a_scroll_through_the_new_village(self):
        from coc_bot.accounts.navigation import AccountNavigator
        import numpy as np
        nav=AccountNavigator.__new__(AccountNavigator);nav.stop=lambda:False
        nav.session=Mock();nav.input=Mock();nav.menu=Mock();nav.button=Mock()
        nav.frame=Mock(return_value=np.zeros((1048,1853,3),np.uint8))
        with patch('coc_bot.accounts.navigation.read_tag',return_value=None),\
             patch('coc_bot.progression.home.recover_home_overlay',return_value=True),\
             patch('coc_bot.accounts.navigation.interrupted_sleep',return_value=False):
            with self.assertRaisesRegex(ValueError,'Game reloaded'):nav.identity()
        nav.input.swipe.assert_not_called()

    def test_speech_bubble_has_no_purchase_control_and_repeated_caption_is_bounded(self):
        from coc_bot.vision.notices import event_story_button
        from coc_bot.progression.home import recover_home_overlay
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/accounts/event-story.png'))
        self.assertIsNotNone(event_story_button(frame))
        bad=frame.copy();bad[602:631,538:573]=0
        self.assertIsNone(event_story_button(bad))
        bad=frame.copy();bad[650:730,600:950]=(0,255,0)
        self.assertIsNone(event_story_button(bad))
        nav=Mock();nav.capture.screenshot.return_value=frame;nav._stopping.return_value=False
        self.assertTrue(recover_home_overlay(nav,frame));self.assertTrue(recover_home_overlay(nav,frame))
        self.assertFalse(recover_home_overlay(nav,frame));self.assertEqual(nav.input.tap.call_count,2)

    def test_expired_event_acknowledgement_requires_complete_notice_and_enabled_control(self):
        from coc_bot.vision.notices import event_ended_button
        import numpy as np
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/accounts/event-ended.png'))
        self.assertIsNotNone(event_ended_button(frame))
        for box in ((752,429,1108,487),(448,615,1390,705),(823,855,1038,921)):
            bad=frame.copy();x0,y0,x1,y1=box;bad[y0:y1,x0:x1]=0
            self.assertIsNone(event_ended_button(bad))
        self.assertIsNone(event_ended_button((frame*.5).astype(np.uint8)))

    def test_complete_chooser_finds_ids_below_the_first_four_cards(self):
        from coc_bot.accounts.navigation import AccountNavigator
        def card(name, y): return {'name':name,'game_name':name,'hall':10,'point':(1570,y)}
        first=[card(c,500+100*i) for i,c in enumerate('ABCD')]
        last=[card(c,500+100*i) for i,c in enumerate('CDEF')]
        nav=AccountNavigator.__new__(AccountNavigator)
        nav.chooser_top=Mock();nav.scroll_cards=Mock()
        nav.stable_cards=Mock(side_effect=[(None,first),(None,last),(None,last)])
        rows=nav.saved_cards()
        self.assertEqual([r['name'] for r in rows],list('ABCDEF'))
        self.assertTrue(all('point' not in r for r in rows))

    def test_complete_chooser_rejects_duplicates_and_discontinuous_scroll(self):
        from coc_bot.accounts.navigation import AccountNavigator
        def card(name,hall=10):return {'name':name,'game_name':name,'hall':hall,'point':(1570,600)}
        for pages in ([['A','B'],['B','A'],['B','A']], [['A','B'],['D','E']]):
            nav=AccountNavigator.__new__(AccountNavigator)
            nav.chooser_top=Mock();nav.scroll_cards=Mock()
            nav.stable_cards=Mock(side_effect=[(None,[card(n) for n in page]) for page in pages])
            with self.assertRaises(ValueError):nav.saved_cards()

    def test_card_selection_relocates_the_card_after_scrolling(self):
        from coc_bot.accounts.navigation import AccountNavigator
        first={'name':'First','game_name':'First','hall':2,'point':(1570,600)}
        wanted={'name':'Last','game_name':'Last','hall':12}
        nav=AccountNavigator.__new__(AccountNavigator)
        nav.chooser_top=Mock();nav.scroll_cards=Mock()
        nav.stable_cards=Mock(side_effect=[(None,[first]),(None,[wanted|{'point':(1570,720)}])])
        self.assertEqual(nav.card_point(wanted),(1570,720))
        nav.scroll_cards.assert_called_once_with()

    def test_reload_overlay_is_dismissed_before_visible_menu_anchors_can_be_used(self):
        from coc_bot.accounts.navigation import AccountNavigator
        nav=AccountNavigator.__new__(AccountNavigator)
        nav.stop=lambda:False;nav.session=Mock();nav.frame=Mock();nav.button=Mock()
        order=[]
        def overlay(*args):order.append('overlay');return len(order)==1
        def find(*args):order.append('anchor');return None if args[1]=='switch_heading' else (1,1)
        with patch('coc_bot.progression.home.recover_home_overlay',side_effect=overlay),\
             patch('coc_bot.accounts.navigation.find',side_effect=find),\
             patch('coc_bot.accounts.navigation.interrupted_sleep',return_value=False):nav.menu()
        self.assertEqual(order[:3],['overlay','overlay','anchor'])
        nav.button.assert_not_called()

    def test_account_menu_waits_for_the_clan_drawer_to_finish_closing(self):
        from coc_bot.accounts.navigation import AccountNavigator
        nav=AccountNavigator.__new__(AccountNavigator)
        nav.stop=lambda:False;nav.session=Mock();nav.tap=Mock()
        from types import SimpleNamespace
        frames=[SimpleNamespace(name=n,shape=(1048,1853,3)) for n in ('chat','closing','home','menu')]
        nav.frame=Mock(side_effect=frames)
        nav.session.navigator.classifier._clan_chat_anchor_visible.return_value=True
        nav.session.navigator.classifier._open_chat_icon_visible.return_value=True
        def anchor(frame,key,*_):return (1,1) if frame.name=='menu' and key in ('my_profile','menu_close') else None
        with patch('coc_bot.progression.home.recover_home_overlay',return_value=False),\
             patch('coc_bot.accounts.navigation.find',side_effect=anchor),\
             patch('coc_bot.accounts.navigation.interrupted_sleep',return_value=False),\
             patch('coc_bot.vision.battle_menu.direct_match_button',return_value=None),\
             patch('coc_bot.vision.battle_menu.home_build_control_visible',side_effect=lambda f:f.name=='home'):
            nav.menu()
        nav.session.navigator.close_clan_chat.assert_called_once_with(frames[0])
        nav.tap.assert_called_once()

    def test_account_menu_closes_verified_upgrade_sidebar_before_avatar_input(self):
        from coc_bot.accounts.navigation import AccountNavigator
        import numpy as np
        nav=AccountNavigator.__new__(AccountNavigator)
        nav.stop=lambda:False;nav.session=Mock();nav.tap=Mock()
        side=np.zeros((1048,1853,3),np.uint8);home=side.copy();menu=side.copy()
        nav.frame=Mock(side_effect=[side,side,home,menu])
        nav.session.navigator.classifier._clan_chat_anchor_visible.return_value=False
        nav.session.navigator.classifier._open_chat_icon_visible.return_value=True
        reader=Mock();reader.menu_kind.side_effect=lambda f:'buildings' if f is side else None
        def anchor(frame,key,*_):return (1,1) if frame is menu and key in ('my_profile','menu_close') else None
        with patch('coc_bot.progression.home.recover_home_overlay',return_value=False),\
             patch('coc_bot.accounts.navigation.find',side_effect=anchor),\
             patch('coc_bot.accounts.navigation.interrupted_sleep',return_value=False),\
             patch('coc_bot.upgrades.vision.UpgradeReader',return_value=reader),\
             patch('coc_bot.progression.preparation.army_editor_close_button',return_value=None),\
             patch('coc_bot.vision.battle_menu.direct_match_button',return_value=None),\
             patch('coc_bot.vision.battle_menu.home_build_control_visible',side_effect=lambda f:f is home):
            nav.menu()
        self.assertEqual(nav.tap.call_args_list[0].args,((1823,34),))
        self.assertEqual(nav.tap.call_count,2)

    def test_account_recovery_closes_info_then_army_before_opening_avatar(self):
        from coc_bot.accounts.navigation import AccountNavigator
        import numpy as np
        nav=AccountNavigator.__new__(AccountNavigator)
        nav.stop=lambda:False;nav.session=Mock();nav.tap=Mock()
        info=np.zeros((1048,1853,3),np.uint8);army=info.copy();home=info.copy();menu=info.copy()
        nav.frame=Mock(side_effect=[info,info,army,army,home,menu])
        nav.session.navigator.classifier._clan_chat_anchor_visible.return_value=False
        nav.session.navigator.classifier._open_chat_icon_visible.return_value=True
        reader=Mock();reader.menu_kind.return_value=None
        def anchor(frame,key,*_):return (1,1) if frame is menu and key in ('my_profile','menu_close') else None
        observation={'unit_id':None,'level':1,'close':(1642,79)}
        with patch('coc_bot.progression.home.recover_home_overlay',return_value=False),\
             patch('coc_bot.accounts.navigation.find',side_effect=anchor),\
             patch('coc_bot.accounts.navigation.interrupted_sleep',return_value=False),\
             patch('coc_bot.upgrades.vision.UpgradeReader',return_value=reader),\
             patch('coc_bot.progression.troop_info.read_info',side_effect=lambda f,*_:observation if f is info else None),\
             patch('coc_bot.progression.preparation.army_editor_close_button',side_effect=lambda f,*_:(1792,95) if f is army else None),\
             patch('coc_bot.vision.battle_menu.direct_match_button',return_value=None),\
             patch('coc_bot.vision.battle_menu.home_build_control_visible',side_effect=lambda f:f is home):
            nav.menu()
        self.assertEqual([c.args[0] for c in nav.tap.call_args_list],[(1642,79),(1792,95),(100,112)])

    def test_account_recovery_closes_picker_before_army_and_avatar(self):
        from coc_bot.accounts.navigation import AccountNavigator
        import numpy as np
        nav=AccountNavigator.__new__(AccountNavigator)
        nav.stop=lambda:False;nav.session=Mock();nav.tap=Mock()
        picker=np.zeros((1048,1853,3),np.uint8);army=picker.copy();home=picker.copy();menu=picker.copy()
        nav.frame=Mock(side_effect=[picker,picker,army,army,home,menu])
        nav.session.navigator.classifier._clan_chat_anchor_visible.return_value=False
        nav.session.navigator.classifier._open_chat_icon_visible.return_value=True
        reader=Mock();reader.menu_kind.return_value=None
        def anchor(frame,key,*_):return (1,1) if frame is menu and key in ('my_profile','menu_close') else None
        with patch('coc_bot.progression.home.recover_home_overlay',return_value=False),\
             patch('coc_bot.accounts.navigation.find',side_effect=anchor),\
             patch('coc_bot.accounts.navigation.interrupted_sleep',return_value=False),\
             patch('coc_bot.upgrades.vision.UpgradeReader',return_value=reader),\
             patch('coc_bot.progression.troop_info.read_info',return_value=None),\
             patch('coc_bot.progression.preparation.picker_boxes',side_effect=lambda f:[(1,2,3,4)]*3 if f is picker else []),\
             patch('coc_bot.progression.preparation.army_page',side_effect=lambda f,*_:f is picker),\
             patch('coc_bot.progression.preparation.capacity',return_value=(0,250)),\
             patch('coc_bot.progression.preparation.army_editor_close_button',side_effect=lambda f,*_:(1792,95) if f is army else None),\
             patch('coc_bot.vision.battle_menu.direct_match_button',return_value=None),\
             patch('coc_bot.vision.battle_menu.home_build_control_visible',side_effect=lambda f:f is home):
            nav.menu()
        self.assertEqual([c.args[0] for c in nav.tap.call_args_list],[(926,178),(1792,95),(100,112)])

    def test_tag_ocr_cannot_silently_drop_visible_characters(self):
        from coc_bot.accounts.navigation import read_tag
        from types import SimpleNamespace
        fixtures=Path(__file__).parent/'fixtures/accounts'
        for name,cyan in [('tag-white.png',False),('tag-cyan.png',True)]:
            with self.subTest(name=name):
                frame=cv2.imread(str(fixtures/name))
                # Whole-line OCR drops the two 8 glyphs. Strict font evidence
                # must account for each actual character, not insert a guessed 8.
                with patch('coc_bot.runtime.processes.run_process',return_value=SimpleNamespace(stdout='#UGLRLYL',returncode=0)):
                    self.assertEqual(read_tag(frame,(0,0,1,1),cyan=cyan),'#U8GL8RLYL')

    def test_additional_glyph_shapes_survive_deleted_digits_and_unknown_single_glyph_ocr(self):
        from coc_bot.accounts.navigation import read_tag
        from types import SimpleNamespace
        for name,cyan in [('white',False),('cyan',True)]:
            frame=cv2.imread(str(Path(__file__).parent/f'fixtures/accounts/tag-varied-{name}.png'))
            with self.subTest(name=name),patch('coc_bot.runtime.processes.run_process',
                    return_value=SimpleNamespace(stdout='',returncode=0)):
                self.assertEqual(read_tag(frame,(0,0,1,1),cyan=cyan),'#P9C02GJ89')

    def test_th2_profile_glyphs_recover_when_ocr_returns_no_tag(self):
        from coc_bot.accounts.navigation import read_tag
        from types import SimpleNamespace
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/accounts/tag-th2-white.png'))
        with patch('coc_bot.runtime.processes.run_process',
                   return_value=SimpleNamespace(stdout='',returncode=0)):
            self.assertEqual(read_tag(frame,(0,0,1,1)),'#R2CLRG2VJ')

    def test_inserted_spaces_in_chooser_names_do_not_lose_scroll_overlap(self):
        from coc_bot.accounts.navigation import AccountNavigator
        self.assertEqual(AccountNavigator.card_key({'name':'Example123'}),
                         AccountNavigator.card_key({'name':'Example1 23'}))

    def test_name_reading_uses_bounded_word_ocr_when_line_ocr_is_blank(self):
        from coc_bot.accounts.navigation import read_name
        from types import SimpleNamespace
        import numpy as np
        frame=np.zeros((42,326,3),np.uint8);frame[10:30,20:40]=255
        with patch('coc_bot.accounts.navigation.text',return_value=''),\
             patch('coc_bot.runtime.processes.run_process',return_value=SimpleNamespace(stdout='Example',returncode=0)) as run:
            self.assertEqual(read_name(frame),'Example')
            self.assertEqual(run.call_args.args[0][3:5],['--psm','8'])

    def test_unknown_tag_glyph_and_stop_never_become_a_guessed_identity(self):
        from coc_bot.accounts.navigation import read_tag
        from types import SimpleNamespace
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/accounts/tag-white.png'))
        with patch('coc_bot.runtime.processes.run_process',return_value=SimpleNamespace(stdout='',returncode=0)),\
             patch('coc_bot.accounts.navigation._font_character',return_value=None):
            self.assertIsNone(read_tag(frame,(0,0,1,1)))
        with patch('coc_bot.runtime.processes.run_process') as process:
            self.assertIsNone(read_tag(frame,(0,0,1,1),stop=lambda:True))
            process.assert_not_called()

    def test_identity_requires_two_stable_reads_on_each_independent_screen(self):
        from coc_bot.accounts.navigation import AccountNavigator
        import numpy as np
        nav=AccountNavigator.__new__(AccountNavigator);nav.stop=lambda:False
        nav.menu=Mock();nav.button=Mock();nav.frame=Mock(return_value=np.zeros((1048,1853,3),np.uint8))
        a,b='#U8GL8RLYL','#PYLQG'
        for readings in ([a,b],[a,a,b],[a,a,a,b]):
            with self.subTest(readings=readings),\
                 patch('coc_bot.accounts.navigation.read_tag',side_effect=readings),\
                 patch('coc_bot.accounts.navigation.text',return_value='Example'),\
                 patch('coc_bot.accounts.navigation.find',return_value=(1,1)):
                with self.assertRaises(ValueError):nav.identity()
        with patch('coc_bot.accounts.navigation.read_tag',side_effect=[a]*4),\
             patch('coc_bot.accounts.navigation.text',return_value='Example'),\
             patch('coc_bot.accounts.navigation.find',return_value=(1,1)):
            self.assertEqual(nav.identity(),{'tag':a,'name':'Example'})

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(project_root()/'config', self.root/'config')
        (self.root/'data').mkdir()
        self.settings = self.root/'data/user_settings.yaml'
        self.settings.write_text('adb:\n  device: test-device\nfarm:\n  enabled: true\n  engine: sequence\n')
        (self.root/'data/calibrated.yaml').write_text('frame_width: 1853\nfarm_deploy_sequence:\n  taps: [[20,30]]\n')
        (self.root/'data/runtime_state.json').write_text('{"active_seconds": 123}')
        self.store = AccountStore(self.root)

    def register(self, tag='#PYLQG', name='Main', roles=None):
        return self.store.register({'tag':tag,'name':name,'selector':name},name,roles or [])

    def test_first_adoption_preserves_settings_and_verifies_backup(self):
        before = self.settings.read_bytes()
        account = self.register(roles=list(ROLES))
        self.assertEqual(self.store.profile(), self.root)
        self.assertEqual(self.settings.read_bytes(),before)
        folder = self.root/account['backup']
        manifest = json.loads((folder/'manifest.json').read_text())
        for file, digest in manifest.items():
            self.assertEqual(hashlib.sha256((folder/file).read_bytes()).hexdigest(),digest)

    def test_new_profile_does_not_inherit_army_timers_or_roles(self):
        self.register(roles=list(ROLES))
        other = self.register('#YQGRJPC2L','Test')
        root = self.store.profile(other)
        self.assertFalse((root/'data/runtime_state.json').exists())
        self.assertNotIn('farm_deploy_sequence',yaml.safe_load((root/'data/calibrated.yaml').read_text()))
        with self.store.scope():
            config = load_config()
            self.assertEqual(config.adb_device,'test-device')
            self.assertFalse(config.donation_enabled)
            self.assertFalse(config.farm_enabled)
            self.assertEqual(config.account_tag,other['tag'])
            self.assertEqual(config.data_dir,root/'data')

    def test_backup_preserves_learned_army_identities_without_full_screen_captures(self):
        progression=self.root/'data/progression'
        files={'army.json':b'{"troops":{"giant":2}}',
               'picker-references/giant.json':b'{"source":"two_info_frames"}',
               'picker-references/giant.png':b'picker artwork',
               'army-references/giant.json':b'{"source":"verified_edit"}',
               'army-references/giant.png':b'army artwork',
               'screens/army-unconfirmed.png':b'full screen'}
        for relative,value in files.items():
            path=progression/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(value)
        folder=backup(self.root);manifest=json.loads((folder/'manifest.json').read_text())
        for relative,value in files.items():
            key='progression/'+relative
            if relative.startswith('screens/'):
                self.assertNotIn(key,manifest)
            else:
                self.assertEqual((folder/key).read_bytes(),value)
                self.assertEqual(manifest[str(Path(key))],hashlib.sha256(value).hexdigest())

    def test_interrupted_switch_blocks_restart_and_wrong_identity(self):
        a=self.register(); b=self.register('#YQGRJPC2L','Test')
        self.store.begin('switch', a['id'])
        reopened=AccountStore(self.root)
        with self.assertRaises(ValueError):reopened.require_ready()
        with self.assertRaises(ValueError):reopened.complete(b['tag'])
        with self.assertRaises(ValueError):reopened.register({'tag':b['tag']},'Again',[])
        self.assertIsNotNone(reopened.load()['pending'])
        reopened.complete(a['tag'])
        self.assertEqual(reopened.require_ready()['id'],a['id'])

    def test_unfinished_native_layout_blocks_automation_and_account_handoff(self):
        from coc_bot.accounts.store import write
        a=self.register();b=self.register('#YQGRJPC2L','Other')
        path=self.store.profile(b)/'data/layouts/state.json'
        write(path,{'pending':{'phase':'opening'}})
        with self.assertRaisesRegex(ValueError,'native layout'):self.store.require_ready()
        with self.assertRaisesRegex(ValueError,'native layout'):self.store.begin('switch',a['id'])
        self.assertIsNone(self.store.load()['pending'])
        with self.assertRaisesRegex(ValueError,'native layout'):self.store.require_ready(allow_layout_recovery=True)
        write(path,{'pending':{'phase':'opening','account':b['tag']}})
        self.assertEqual(self.store.require_ready(allow_layout_recovery=True)['id'],b['id'])
        with self.assertRaisesRegex(ValueError,'native layout'):self.store.begin('switch',a['id'])
        write(path,{'last_survey':{'account':b['tag'],'payment':{'cost':100}}})
        with self.assertRaisesRegex(ValueError,'native layout'):self.store.begin('switch',a['id'])
        self.assertEqual(self.store.require_ready(allow_layout_recovery=True)['id'],b['id'])
        write(path,{'draft':{'status':'draft_needs_placement'}})
        self.assertEqual(self.store.require_ready()['id'],b['id'])

    def test_finish_switch_resumes_only_the_saved_destination(self):
        from types import SimpleNamespace
        from contextlib import nullcontext
        import threading
        target=self.register();self.register('#YQGRJPC2L','Other')
        self.store.begin('switch',target['id'])
        service=Mock();service.lock=threading.RLock()
        service.session.return_value=SimpleNamespace(config=SimpleNamespace(adb_device='test'))
        service.job.side_effect=lambda _,fn:fn(threading.Event())
        with patch('coc_bot.accounts.service.DeviceLease',side_effect=lambda _:nullcontext()),\
             patch('coc_bot.accounts.service.AccountNavigator') as nav:
            nav.return_value.switch.return_value={'tag':target['tag'],'hall':2}
            Accounts(service,self.root).action('verify')
            nav.return_value.switch.assert_called_once_with(target)
            nav.return_value.identity.assert_not_called()
        self.assertIsNone(self.store.load()['pending'])
        self.assertEqual(self.store.account()['id'],target['id'])
        self.assertEqual(self.store.account()['town_hall'],2)

    def test_role_masks_and_explicit_farm_routes(self):
        self.register(roles=['donating'])
        service=ControlService(); service.accounts=Accounts(service,self.root)
        with self.store.scope():
            config=load_config()
            self.assertTrue(config.donation_enabled)
            self.assertFalse(config.farm_enabled)
            for action in (service.farm,service.automatic_attack,lambda:service.execute_attack_preview('x','y'),lambda:service.upgrade('buildings')):
                with self.assertRaises(ValueError):action()

    def test_stale_settings_revision_cannot_cross_accounts(self):
        from coc_bot.control.settings import revision
        a=self.register()
        with self.store.scope():first=revision()
        b=self.register('#YQGRJPC2L','Test')
        shutil.copyfile(self.settings,self.store.profile(b)/'data/user_settings.yaml')
        with self.store.scope():self.assertNotEqual(first,revision())
        self.store.complete(a['tag'])
        with self.store.scope():self.assertEqual(first,revision())

    def test_invalid_ids_roles_and_registry_fail_closed(self):
        with self.assertRaises(ValueError):self.register('not-a-tag')
        with self.assertRaises(ValueError):self.register(roles=['gem_spending'])
        self.register()
        with self.assertRaises(ValueError):self.store.begin('switch','missing')
        self.store.path.write_text('')
        with self.assertRaises(ValueError):self.store.load()

    def test_role_change_cannot_mutate_running_worker_context(self):
        a=self.register(roles=['donating'])
        with self.store.scope():
            self.store.update(a['id'],'Main',['farming'])
            self.assertTrue(load_config().donation_enabled)
        with self.store.scope():self.assertFalse(load_config().donation_enabled)

    def test_stop_prevents_taps_and_tag_mismatch_prevents_automation(self):
        from coc_bot.accounts.navigation import AccountNavigator,verify_session
        session=Mock();session.config.account_tag='#PYLQG'
        with self.assertRaises(ValueError):AccountNavigator(session,lambda:True).tap((1,2))
        session.input.tap.assert_not_called()
        with patch.object(AccountNavigator,'identity',return_value={'tag':'#YQGRJPC2L'}):
            with self.assertRaises(ValueError):verify_session(session)
        session.nav_input.tap.assert_not_called()

    def test_practice_identity_check_uses_real_navigation(self):
        from types import SimpleNamespace
        from coc_bot.accounts.navigation import AccountNavigator
        donation_input, navigation_input = Mock(), Mock()
        session = SimpleNamespace(capture=Mock(), input=donation_input, nav_input=navigation_input)
        with patch('coc_bot.accounts.navigation.interrupted_sleep'):
            AccountNavigator(session).tap((12, 34))
        navigation_input.tap.assert_called_once_with(12, 34, jitter=0)
        donation_input.tap.assert_not_called()

    def test_api_registration_switch_pending_and_roles(self):
        from fastapi.testclient import TestClient
        from coc_bot.web.server import create_app
        from coc_bot.accounts.navigation import AccountNavigator
        from contextlib import nullcontext
        from types import SimpleNamespace
        service=ControlService(session_factory=lambda: SimpleNamespace(
            config=load_config(),client=Mock(),capture=Mock(),input=Mock(),navigator=Mock(),
            attack_nav=Mock(),deployer=Mock(),app=Mock()))
        app=create_app(service,scope=self.root,origins=['http://testserver'],enable_simulation=False)
        with TestClient(app) as client, patch('coc_bot.accounts.service.DeviceLease',side_effect=lambda _:nullcontext()):
            csrf=client.get('/api/session').json()['csrf']; headers={'X-CSRF-Token':csrf}
            self.assertEqual(client.post('/api/accounts/action',json={'action':'verify'}).status_code,403)
            with patch.object(AccountNavigator,'learn',return_value={'tag':'#PYLQG','name':'Main','selector':'Main'}):
                response=client.post('/api/accounts/action',headers=headers,json={'action':'register','nickname':'Main','roles':['donating']})
                self.assertEqual(response.status_code,200,response.text)
                self.assertTrue(service.controller.wait(3))
            account=client.get('/api/accounts').json()['accounts'][0]
            self.assertEqual(client.post('/api/farm',headers=headers).status_code,400)
            with patch.object(AccountNavigator,'chooser',side_effect=ValueError('Unknown layout')):
                response=client.post('/api/accounts/action',headers=headers,json={'action':'add'})
                self.assertEqual(response.status_code,200,response.text)
                self.assertTrue(service.controller.wait(3))
            self.assertEqual(client.get('/api/accounts').json()['pending']['kind'],'add')
            self.assertEqual(client.post('/api/start',headers=headers,json={}).status_code,400)
            with patch.object(AccountNavigator,'identity',return_value={'tag':'#PYLQG'}), patch.object(AccountNavigator,'button'):
                client.post('/api/accounts/action',headers=headers,json={'action':'verify'})
                self.assertTrue(service.controller.wait(3))
            self.assertIsNone(client.get('/api/accounts').json()['pending'])
            self.assertEqual(client.get('/api/status').json()['account']['id'],account['id'])
