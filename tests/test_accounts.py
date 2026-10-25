"""Account isolation, role boundaries and interrupted-switch recovery; no device."""
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch
import hashlib
import json
import shutil
import tempfile
import yaml

from coc_bot.accounts.store import AccountStore, backup, apply_roles, ROLES
from coc_bot.config import load_config, project_root
from coc_bot.control.service import ControlService
from coc_bot.accounts.service import Accounts


class AccountsTests(TestCase):
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
                self.assertEqual(manifest[key],hashlib.sha256(value).hexdigest())

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
