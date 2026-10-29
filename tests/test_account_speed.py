import tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import numpy as np

from coc_bot.accounts.navigation import AccountNavigator,verify_session
from coc_bot.accounts.handoff import VerifiedHandoff
from coc_bot.runtime.device_lease import DeviceLease


class AccountSpeedTests(unittest.TestCase):
    def card(self,name='Target',point=(1570,600)):
        return {'name':name,'game_name':'','hall':12,'point':point}

    def nav(self):
        session=SimpleNamespace(capture=Mock(),input=Mock())
        session.capture.screenshot.return_value=np.zeros((1048,1853,3),np.uint8)
        return AccountNavigator(session)

    def test_visible_target_uses_the_stable_viewport_without_full_discovery(self):
        n=self.nav();n.chooser=Mock();n.saved_cards=Mock();n.chooser_top=Mock();n.stable_cards=Mock()
        n._chooser_observation=(object(),[self.card()])
        self.assertEqual(n.target_card({'name':'Target'}),self.card())
        n.saved_cards.assert_not_called();n.chooser_top.assert_not_called();n.stable_cards.assert_not_called()

    def test_missing_target_relocates_after_scrolling_and_duplicate_visible_names_block(self):
        n=self.nav();n.chooser=Mock();n.chooser_top=Mock();n.scroll_cards=Mock()
        n._chooser_observation=(object(),[self.card('Other')])
        target=self.card(point=(1570,720))
        n.stable_cards=Mock(side_effect=[(object(),[self.card('Other')]),(object(),[target])])
        self.assertEqual(n.target_card({'name':'Target'}),target);n.scroll_cards.assert_called_once()
        n._chooser_observation=(object(),[self.card(),self.card(point=(1570,720))])
        with self.assertRaisesRegex(ValueError,'duplicate'):n.target_card({'name':'Target'})
        n.input.tap.assert_not_called()

    def test_identical_pixels_reuse_name_ocr_but_changed_chooser_or_resolution_does_not(self):
        n=self.nav();image=n.frame();moved=image.copy();moved[600,1500]=255
        with patch('coc_bot.accounts.navigation.find',return_value=(1,1)),\
             patch('coc_bot.accounts.navigation.picker_rows',return_value=[self.card()]) as parse:
            self.assertEqual(n._read_cards(image),n._read_cards(image.copy()))
            self.assertEqual(parse.call_count,1)
            n._read_cards(moved);self.assertEqual(parse.call_count,2)
            n._read_cards(np.zeros((720,1280,3),np.uint8));self.assertEqual(parse.call_count,3)
        with patch('coc_bot.accounts.navigation.find',return_value=None):
            with self.assertRaisesRegex(ValueError,'not visible'):n._read_cards(image)

    def test_chooser_requires_two_stable_frames_but_only_one_identical_ocr_parse(self):
        n=self.nav()
        with patch('coc_bot.accounts.navigation.find',return_value=(1,1)),\
             patch('coc_bot.accounts.navigation.picker_rows',return_value=[self.card()]) as parse,\
             patch('coc_bot.accounts.navigation.interrupted_sleep',return_value=False):
            n.chooser()
        self.assertEqual(n.capture.screenshot.call_count,2);self.assertEqual(parse.call_count,1)
        self.assertFalse(n._same_cards([self.card()],[self.card(point=(1570,620))]))
        self.assertFalse(n._same_cards([self.card()],[self.card()|{'hall':13}]))

    def test_wrong_loaded_identity_still_blocks_switch(self):
        n=self.nav();n.target_card=Mock(return_value=self.card());n.identity=Mock(return_value={'tag':'#OTHER'})
        n.tap=Mock();n.button=Mock()
        with patch('coc_bot.progression.home.recover_home_overlay',return_value=False),\
             patch('coc_bot.vision.battle_menu.home_build_control_visible',return_value=True):
            n.session.navigator=Mock()
            with self.assertRaisesRegex(ValueError,'different account'):n.switch({'selector':'Target','tag':'#PYLQG'})
        n.button.assert_not_called()

    def test_stop_prevents_cached_chooser_reads_and_cached_button_taps(self):
        n=self.nav();n.stop=lambda:True
        with self.assertRaises(ValueError):n._read_cards(np.zeros((1048,1853,3),np.uint8))
        with patch('coc_bot.accounts.navigation.find',return_value=(1,1)):
            with self.assertRaises(ValueError):n.button('menu_close',frame=object())
        n.input.tap.assert_not_called()


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.config=SimpleNamespace(account_tag='#PYLQG',data_dir=Path(self.temp.name),adb_device='offline-speed-test')

    def proof(self,lease,**kw):
        return VerifiedHandoff(self.config.account_tag,self.config.data_dir,self.config.adb_device,lease,**kw)

    def test_proof_is_one_use_and_cannot_survive_lease_release(self):
        with DeviceLease(self.config.adb_device) as lease:
            proof=self.proof(lease);self.assertTrue(proof.consume(self.config));self.assertFalse(proof.consume(self.config))
            expired=self.proof(lease,issued_at=time.monotonic()-31)
            self.assertFalse(expired.consume(self.config));released=self.proof(lease)
        self.assertFalse(released.consume(self.config))

    def test_wrong_device_profile_tag_or_thread_cannot_reuse_identity(self):
        with DeviceLease(self.config.adb_device) as lease:
            for field,value in [('adb_device','other'),('account_tag','#OTHER'),('data_dir',Path(self.temp.name)/'other')]:
                config=SimpleNamespace(**(vars(self.config)|{field:value}))
                self.assertFalse(self.proof(lease).consume(config))
            self.assertFalse(self.proof(lease,thread=-1).consume(self.config))

    def test_fresh_proof_uses_current_village_frame_instead_of_repeating_tag_navigation(self):
        session=SimpleNamespace(config=self.config,capture=Mock(),navigator=Mock(),input=Mock())
        session.navigator.classifier._open_chat_icon_visible.return_value=True
        with DeviceLease(self.config.adb_device) as lease:
            session._verified_handoff=self.proof(lease)
            with patch('coc_bot.vision.battle_menu.home_build_control_visible',return_value=True),\
                 patch.object(AccountNavigator,'identity') as identity:
                verify_session(session)
                identity.assert_not_called();session.capture.screenshot.assert_called_once()
            self.assertNotIn('_verified_handoff',session.__dict__)

    def test_changed_screen_falls_back_to_the_complete_independent_identity_check(self):
        session=SimpleNamespace(config=self.config,capture=Mock(),navigator=Mock(),input=Mock())
        session.navigator.classifier._clan_chat_anchor_visible.return_value=False
        with DeviceLease(self.config.adb_device) as lease:
            session._verified_handoff=self.proof(lease)
            with patch('coc_bot.vision.battle_menu.home_build_control_visible',return_value=False),\
                 patch.object(AccountNavigator,'identity',return_value={'tag':'#PYLQG'}) as identity,\
                 patch.object(AccountNavigator,'button') as close:
                verify_session(session)
                identity.assert_called_once();close.assert_called_once()
