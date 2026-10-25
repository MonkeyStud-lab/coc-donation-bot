"""Accounts use the controller's ownership and cancellation, never a second bot."""
from coc_bot.accounts.store import AccountStore, roles
from coc_bot.accounts.navigation import AccountNavigator
from coc_bot.runtime.device_lease import DeviceLease


class Accounts:
    def __init__(self, service, root):
        self.service, self.store = service, AccountStore(root)

    def snapshot(self):
        state = self.store.load()
        return {k: state[k] for k in ('accounts', 'active', 'pending')}

    def update(self, ident, nickname, selected_roles):
        with self.service.mutation():
            self.store.require_ready()
            self.store.update(ident, nickname, selected_roles)
            self.service._finished_generation = -1
        return self.snapshot()

    def action(self, action, nickname='', selected_roles=None, target=None):
        if action not in ('register', 'add', 'verify', 'switch'):
            raise ValueError('Unknown account action')
        selected_roles = roles(selected_roles or [])
        with self.service.lock:
            self.service.idle()
            if action == 'add' and not self.store.account():
                raise ValueError('Save your current account first')
            if action == 'switch' and not self.store.account(target):
                raise ValueError('Unknown saved account')
            def execute(cancel):
                session = self.service.session(cancel)
                with DeviceLease(session.config.adb_device):
                    nav = AccountNavigator(session, cancel.is_set)
                    if action == 'register':
                        if not self.store.load().get('pending'):
                            self.store.begin('add')
                        identity = nav.learn()
                        self.store.register(identity, nickname or identity['name'], selected_roles)
                    elif action == 'verify':
                        identity = nav.identity()
                        self.store.complete(identity['tag'])
                        nav.button('menu_close', (.84, .02, .91, .14))
                    else:
                        self.store.begin(action, target)
                        if action == 'add':
                            nav.chooser()
                            return {'accounts': True, 'message': 'In Live view, choose Log in to Supercell ID. Sign in, return to the village, then Save loaded account.'}
                        identity = nav.switch(self.store.account(target))
                        self.store.complete(identity['tag'])
                    self.service._finished_generation = -1
                    return {'accounts': True, 'message': 'Account verified. Settings now belong to '+self.store.account()['nickname']}
            self.service.job('accounts_'+action, execute)
