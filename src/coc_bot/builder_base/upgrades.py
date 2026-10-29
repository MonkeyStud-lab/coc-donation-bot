"""Reuse the durable upgrade transaction with Builder Base-specific guards."""
from dataclasses import replace

from coc_bot.upgrades.runner import UpgradeRunner
from coc_bot.upgrades.vision import compact
from coc_bot.builder_base.vision import BuilderReader

BUILDINGS = {compact(name) for name in (
    'Star Laboratory', 'Builder Barracks',
    'Elixir Collector', 'Gold Mine', 'Gold Storage', 'Elixir Storage',
    'Cannon', 'Double Cannon', 'Archer Tower', 'Hidden Tesla', 'Firecrackers',
    'Crusher', 'Guard Post', 'Air Bombs', 'Multi Mortar', 'Roaster',
    'Giant Cannon', 'Mega Tesla', 'Lava Launcher', 'X-Bow', 'Push Trap',
    'Spring Trap', 'Mine', 'Mega Mine',
)}


def supported_building(candidate):
    return compact(candidate.name) in BUILDINGS and candidate.currency in ('gold', 'elixir')


def eligibility(config, candidate, balances, availability):
    if compact(candidate.name) not in BUILDINGS:
        return 'Only recognized existing Builder Base defenses and resource buildings are supported'
    excluded = {compact(n) for n in config.upgrade_excluded_names.split(',')}
    if compact(candidate.name) in excluded:
        return 'Excluded in settings'
    if candidate.currency not in ('gold', 'elixir'):
        return 'Only Builder Gold and Builder Elixir building confirmations are supported'
    if (availability is None or not 1 <= availability[1] <= 3
            or not 0 <= availability[0] <= availability[1]
            or availability[0] <= config.builder_base_builders_reserved):
        return 'No verified spare Builder Base builder'
    if type(candidate.cost) is not int or candidate.cost <= 0:
        return 'Unknown price; gems and items are excluded'
    floor=getattr(config,'builder_base_'+candidate.currency+'_reserve',None)
    if type(floor) is not int or floor<0:
        return 'Builder resource reserve is unverified'
    balance = balances.get(candidate.currency)
    if type(balance) is not int or not 0 <= balance <= 20_000_000:
        return 'Builder resource balance is unverified'
    if balance-candidate.cost < floor:
        return 'Would fall below the Builder Base reserve'
    return None


class BuilderUpgradeRunner(UpgradeRunner):
    def __init__(self, config, capture, input_ctrl, navigator, stop=None):
        # The common transaction only uses this setting to stop list exploration.
        super().__init__(replace(config, upgrade_builders_reserved=config.builder_base_builders_reserved),
                         capture, input_ctrl, navigator, stop)
        self.reader = BuilderReader(stop)
        self.path = config.data_dir/'builder_base/upgrades.json'

    def eligibility(self, kind, candidate, balances, availability):
        if kind == 'research':
            if compact(candidate.name)!='nightwitch' or candidate.currency!='elixir':
                return 'Only the verified Night Witch research dialog is supported'
            if compact(candidate.name) in {compact(n) for n in self.config.upgrade_excluded_names.split(',')}:
                return 'Excluded in settings'
            if availability != (1,1):
                return 'No verified free Star Laboratory'
            balance=balances.get('elixir')
            if type(candidate.cost) is not int or candidate.cost<=0 or type(balance) is not int:
                return 'Research price or balance is unverified'
            if not 0 <= balance <= 20_000_000 or balance-candidate.cost < self.config.builder_base_elixir_reserve:
                return 'Would fall below the Builder Elixir reserve'
            return None
        if kind != 'buildings':
            return 'Unsupported Builder Base upgrade category'
        return eligibility(self.config, candidate, balances, availability)

    def open_menu(self, kind):
        if kind not in ('buildings','research'):
            raise ValueError('Unsupported Builder Base upgrade category')
        frame = self.capture.screenshot()
        if self.stopped():
            return None
        close=self.reader.detail_close(frame)
        if close:
            if self.stopped(): return None
            self.input.tap(*close,jitter=0)
            if self.wait(): return None
            frame=self.capture.screenshot()
        if self.reader.menu_kind(frame) == kind:
            return frame
        if self.reader.menu_kind(frame) is None:
            if not self.reader.home(frame):
                raise ValueError('Builder Base home controls are not verified')
            if self.stopped(): return None
            self.input.tap(round(frame.shape[1]*.935), round(frame.shape[0]*.895), jitter=0)
            if self.wait(): return None
            frame = self.capture.screenshot()
        if self.reader.menu_kind(frame) not in ('buildings','research'):
            raise ValueError('Builder Base upgrade menu did not open')
        if self.reader.menu_kind(frame) != kind:
            if self.stopped(): return None
            self.input.tap(round(frame.shape[1]*(.93 if kind=='research' else .795)),
                           round(frame.shape[0]*.94),jitter=0)
            if self.wait(): return None
            frame=self.capture.screenshot()
        if self.reader.menu_kind(frame) != kind:
            raise ValueError('Builder Base building tab did not open')
        return frame

    def close(self):
        for _ in range(3):
            if self.stopped():return
            frame=self.capture.screenshot()
            sorting=self.reader.research_sorting(frame) is True
            point=(round(frame.shape[1]*.40),round(frame.shape[0]*.60)) if sorting else self.reader.detail_close(frame)
            if sorting:
                if self.reader.research_sorting(self.capture.screenshot()) is not True:return
            elif point is not None:
                if self.reader.detail_close(self.capture.screenshot())!=point:return
            elif self.reader.menu_kind(frame):
                point=(round(frame.shape[1]*.984),round(frame.shape[0]*.032))
            else:return
            if self.stopped():return
            self.input.tap(*point,jitter=0)
            if self.wait():return
