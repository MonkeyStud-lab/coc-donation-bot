"""Goal-based, restartable visits shared by single-account and fleet runs."""
import time
import math
from coc_bot.accounts.store import read, write

STEPS = ('farm', 'requests', 'upgrades', 'builder_base', 'layouts')
VERSION = 1


class Visit:
    def __init__(self, config, clock=time.time):
        from coc_bot.runtime.resource_farming import thresholds
        thresholds(getattr(config,'farm_resource_start_percent',75),getattr(config,'farm_resource_target_percent',95))
        self.config, self.clock = config, clock
        self.path = config.data_dir/'visits/state.json'

    def load(self):
        state = read(self.path, {})
        if state and (state.get('account') != self.config.account_tag or state.get('version') != VERSION):
            raise ValueError('Visit identity/version changed; review the saved visit before continuing')
        if state:
            if (type(state.get('step')) is not int or not 0<=state['step']<=len(STEPS)
                or not isinstance(state.get('outcomes'),dict) or not isinstance(state.get('deferred'),dict)):
                raise ValueError('Visit journal is invalid; review it before continuing')
            for name in ('started_at','finished_at','next_check_at'):
                value=state.get(name)
                if value is not None and (type(value) not in (int,float) or not math.isfinite(value) or value<0):
                    raise ValueError('Visit timing is invalid; review it before continuing')
            for name,value in state['deferred'].items():
                if (name not in STEPS or not isinstance(value,dict) or type(value.get('retry_at')) not in (int,float)
                    or not math.isfinite(value['retry_at']) or value['retry_at']<0):
                    raise ValueError('Deferred visit step is invalid; review it before continuing')
        return state or {'version': VERSION, 'account': self.config.account_tag, 'step': 0,
                         'started_at': self.clock(), 'outcomes': {}, 'deferred': {}}

    def order(self):
        state = self.load()
        if 'finished_at' in state:
            if self.clock() < state.get('next_check_at', 0):return ()
            state = {'version': VERSION, 'account': self.config.account_tag, 'step': 0,
                     'started_at': self.clock(), 'outcomes': {}, 'deferred': state.get('deferred', {})}
            write(self.path, state)
        index = state['step']
        return STEPS[index:index+1]

    def finish_step(self, name, *, repeat=False, reason=None, retry_at=None):
        state = self.load()
        if state['step'] >= len(STEPS) or STEPS[state['step']] != name:return
        state['outcomes'][name] = {'at': self.clock(), 'status': 'working' if repeat else 'checked', 'reason': reason}
        if repeat:
            write(self.path, state);return
        if retry_at:
            state['deferred'][name] = {'retry_at': retry_at, 'reason': reason}
            state['outcomes'][name]['status'] = 'deferred'
        else:state['deferred'].pop(name, None)
        state['step'] += 1
        if state['step'] == len(STEPS):
            state['finished_at'] = self.clock()
            state['next_check_at'] = self.clock()+300
        write(self.path, state)

    def complete(self):
        return 'finished_at' in self.load()

    def deferred(self, name):
        value = self.load().get('deferred', {}).get(name, {})
        return value if self.clock() < value.get('retry_at', 0) else None
