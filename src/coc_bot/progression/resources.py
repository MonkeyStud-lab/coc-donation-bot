"""Home storage readings from native counters and Max/Production tooltips.

    No Town Hall capacity table, full-looking bars, purchase icons, or gems.
"""
from coc_bot.builder_base.vision import BuilderReader
from coc_bot.progression.reader import balance_amount
from coc_bot.upgrades.vision import crop, currency
from coc_bot.vision.battle_menu import home_build_control_visible


HUD = {'gold': (.855, .034, .958, .071), 'elixir': (.855, .102, .958, .140),
       'dark_elixir': (.865, .171, .958, .209)}
Y = {'gold': .055, 'elixir': .12, 'dark_elixir': .19}


class HomeResources(BuilderReader):
    def __init__(self, navigator):
        self.nav = navigator
        super().__init__(navigator._stopping)

    def home(self, frame):
        return bool(home_build_control_visible(frame) and self.nav.classifier._open_chat_icon_visible(frame))

    def balances(self, frame):
        if not self.home(frame):return {}
        return {resource: balance_amount(crop(frame, box), self.stop) for resource, box in HUD.items()}

    def storage_capacity(self, frame, resource):
        if resource not in Y or not self.home(frame):return None
        top = Y[resource]+.03
        # Max labels for adjacent resources are only ~70px apart. A broad
        # search can mistake an already-open elixir tooltip for gold.
        box = (.68, top, .99, top+.075)
        maximum = self.find(frame, 'storage_max', box, threshold=.95)
        production = self.find(frame, 'storage_production', (.68, top+.02, .99, top+.13), threshold=.94)
        if maximum is None or production is None:return None
        scale = frame.shape[1]/1853
        x, y = maximum
        region = frame[round(y-19*scale):round(y+20*scale), round(x+32*scale):round(frame.shape[1]*.978)]
        value = balance_amount(region, self.stop)
        return value if type(value) is int and 0 < value <= 100_000_000 else None

    def observe(self, config):
        from coc_bot.progression.home import ensure_home
        from coc_bot.stop import interrupted_sleep
        if not ensure_home(self.nav):return {}
        def frame():
            if self.stop():raise InterruptedError('Resource check stopped')
            result = self.nav.capture.screenshot()
            if not self.home(result):raise ValueError('Home controls lost during resource check')
            return result
        current = frame()
        resources = ['gold', 'elixir']
        # A saved verified early Hall and absence of the DE icon establish that
        # the third counter is gems. Later Halls require the actual dark icon.
        dark = currency(crop(current, (.963, .158, .998, .225))) == 'dark_elixir'
        hall = getattr(config, 'account_town_hall', None)
        if dark:resources.append('dark_elixir')
        elif type(hall) is not int or hall >= 7:return {}
        capacities = {}
        try:
            for resource in resources:
                current = frame()
                if self.storage_capacity(current, resource) is None:
                    self.nav.input.tap(round(current.shape[1]*.87), round(current.shape[0]*Y[resource]), jitter=0)
                    interrupted_sleep(.3, self.stop)
                first = self.storage_capacity(frame(), resource)
                second = self.storage_capacity(frame(), resource)
                if first is not None and first == second:capacities[resource] = first
                # Close only the tooltip that is independently visible.
                current = frame()
                if self.storage_capacity(current, resource) is not None:
                    self.nav.input.tap(round(current.shape[1]*.87), round(current.shape[0]*Y[resource]), jitter=0)
                    interrupted_sleep(.2, self.stop)
            first, second = self.balances(frame()), self.balances(frame())
            balances = {r: second.get(r) for r in resources if first.get(r) == second.get(r)}
            return {'resources': resources, 'balances': balances, 'capacities': capacities}
        finally:
            if not self.stop():self.nav.ensure_clan_chat()
