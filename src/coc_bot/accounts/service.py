"""Accounts use the controller's ownership and cancellation, never a second bot."""
from coc_bot.accounts.store import AccountStore, roles
from coc_bot.accounts.navigation import AccountNavigator
from coc_bot.runtime.device_lease import DeviceLease


class Accounts:
    def __init__(self, service, root):
        self.service, self.store = service, AccountStore(root)

    def snapshot(self):
        state = self.store.load()
        from coc_bot.accounts.rotation import RotationStore
        rotation=RotationStore(self.store).load()
        from coc_bot.accounts.clan import membership
        import time
        from coc_bot.accounts.store import read
        accounts=[]
        for a in state['accounts']:
            maintenance=read(self.store.profile(a)/'data/upgrades/maintenance.json',{})
            accounts.append(a|{'clan_tag':membership(self.store,a,time.time()),
                               'maintenance':maintenance if maintenance.get('account')==a['tag'] else {}})
        return {k: state[k] for k in ('active', 'pending')} | {'accounts':accounts,'rotation':rotation}

    def configure_rotation(self, **values):
        from coc_bot.accounts.rotation import RotationStore
        from coc_bot.accounts.store import backup
        with self.service.mutation():
            backup(self.store.root)
            RotationStore(self.store).configure(**values)
        return self.snapshot()

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
                        pending=self.store.load().get('pending')
                        finishing=bool(pending and pending['kind']=='switch')
                        identity=(nav.switch(self.store.account(pending['target'])) if finishing else nav.identity())
                        self.store.complete(identity['tag'],hall=identity.get('hall'))
                        if not finishing:nav.button('menu_close', (.84, .02, .91, .14))
                    else:
                        self.store.begin(action, target)
                        if action == 'add':
                            nav.chooser()
                            return {'accounts': True, 'message': 'Sign in through Live view, return to the home village, and release control. Then choose tasks and press Save and verify account.'}
                        identity = nav.switch(self.store.account(target))
                        self.store.complete(identity['tag'],hall=identity.get('hall'))
                    self.service._finished_generation = -1
                    account=self.store.account()
                    message=(account['nickname']+' is saved and verified. No separate check is needed.' if action=='register'
                             else 'Loaded account confirmed: '+account['nickname']+'.')
                    return {'accounts': True, 'message': message+' The bot stays stopped until you press Start.'}
            self.service.job('accounts_'+action, execute)
