"""Recognize remembered villages before constructing their automation worker."""
from dataclasses import asdict
import threading
from loguru import logger
from coc_bot.accounts.store import read


def unresolved(config):
    from coc_bot.attack.recovery import pending
    from coc_bot.builder_base.runner import pending as builder_pending
    layout = read(config.data_dir/'layouts/state.json', {})
    return (pending(config) or builder_pending(config)
            or read(config.data_dir/'upgrades/state.json', {}).get('pending')
            or layout.get('pending') or layout.get('last_survey', {}).get('payment'))


def recognize_loaded(store, session, lease, stop):
    """Never register/guess an identity, abandon a receipt, or reuse old settings."""
    from coc_bot.accounts.navigation import AccountNavigator
    from coc_bot.accounts.handoff import VerifiedHandoff
    from coc_bot.config import load_config
    before = store.require_ready(allow_layout_recovery=True)
    if before is None or unresolved(session.config):
        return None  # Existing account-specific recovery owns this startup.
    nav = AccountNavigator(session, stop)
    identity = nav.identity()  # Two stable reads on each independent native tab.
    nav.check()
    state = store.load()
    if state.get('pending') or state['active'] != before['id']:
        raise ValueError('Account selection changed during startup; retry after verification')
    actual = next((a for a in state['accounts'] if a['tag'] == identity['tag']), None)
    if actual is None:
        raise ValueError('Loaded village is not saved. Add it in Accounts before starting automation.')
    if not actual['roles']:
        raise ValueError('Choose tasks for the loaded saved account before starting automation')
    if stop():raise ValueError('Account startup stopped before selecting the verified profile')
    if actual['id'] != before['id']:
        with store.scope(actual['id']):
            target_config=load_config()
            if target_config.adb_device!=session.config.adb_device:
                raise ValueError('Saved accounts must use the same Android device before automatic startup')
            if unresolved(target_config):
                raise ValueError('Loaded account has an unresolved action; verify and recover it first')
        # Re-read under the registry lock before committing the independently read tag.
        with store.lock:
            current = store.load()
            if current.get('pending') or current['active'] != before['id']:
                raise ValueError('Account selection changed during startup')
            store.complete(identity['tag'], hall=identity.get('hall'))
        logger.info('Recognized saved account {} — loading its own settings and calibration', actual['nickname'])
    nav.button('menu_close', (.84, .02, .91, .14))
    return VerifiedHandoff(identity['tag'], store.profile(actual)/'data', session.config.adb_device, lease)


class ManagedAccountRun:
    """Single-account equivalent of the fleet's verified startup, including practice."""
    def __init__(self, store, options):
        self.store, self.options = store, options
        self.current = None
        self.cancel = threading.Event()
        self.finish_action = False

    def __getattr__(self, name):
        current = self.__dict__.get('current')
        if current is None:raise AttributeError(name)
        return getattr(current, name)

    def request_stop(self):
        self.cancel.set()
        if self.current:self.current.request_stop()

    def request_stop_after_action(self):
        self.finish_action = True
        if self.current:self.current.request_stop_after_action()

    def request_farm_attack(self):
        if self.current is None:raise ValueError('Wait for account recognition to finish')
        self.current.request_farm_attack()

    def run(self):
        from coc_bot.control.diagnostics import DebugSession
        from coc_bot.runtime.device_lease import DeviceLease
        from coc_bot.bot import DonationBot
        with self.store.scope():session = DebugSession()
        with DeviceLease(session.config.adb_device) as lease:
            proof = recognize_loaded(self.store, session, lease, self.cancel.is_set)
            if self.cancel.is_set() or self.finish_action:return
            with self.store.scope():
                self.current = DonationBot(**asdict(self.options))
                if self.cancel.is_set():
                    self.current.request_stop()
                    return
                if self.finish_action:return
                if proof:self.current._verified_handoff = proof
                self.current.run_owned()
