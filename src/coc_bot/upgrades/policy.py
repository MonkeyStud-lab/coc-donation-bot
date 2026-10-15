"""Upgrade eligibility is independent of navigation and never uses color alone."""
from coc_bot.upgrades.vision import compact

PROTECTED = {
    'townhall','wall','walls','laboratory','barracks','darkbarracks','spellfactory',
    'darkspellfactory','workshop','herohall','pethouse','barbarianking','archerqueen',
    'grandwarden','royalchampion','minionprince','dragonduke','battlemachine','battlecopter',
}
BUILDINGS = {compact(name) for name in (
    "Blacksmith", "Builder's Hut", "Army Camp", "Gold Mine", "Elixir Collector",
    "Dark Elixir Drill", "Gold Storage", "Elixir Storage", "Dark Elixir Storage",
    "Cannon", "Archer Tower", "Mortar", "Air Defense", "Wizard Tower", "Air Sweeper",
    "Hidden Tesla", "Bomb Tower", "X-Bow", "Inferno Tower", "Eagle Artillery",
    "Scattershot", "Monolith", "Spell Tower", "Ricochet Cannon", "Multi-Archer Tower",
    "Multi-Gear Tower", "Firespitter", "Bomb", "Giant Bomb", "Air Bomb", "Seeking Air Mine",
    "Spring Trap", "Skeleton Trap", "Tornado Trap",
)}


def reason(config, kind, candidate, balances, availability):
    if kind not in ('buildings','research'):
        return 'Unsupported upgrade category'
    if availability is None:
        return 'Builder/research availability could not be verified'
    free,total=availability
    if free <= (config.upgrade_builders_reserved if kind=='buildings' else 0):
        return 'No spare builders' if kind=='buildings' else 'Research is already busy'
    if compact(candidate.name) in PROTECTED:
        return 'Excluded from automatic upgrades'
    if kind=='buildings' and compact(candidate.name) not in BUILDINGS:
        return 'Unrecognized building or excluded hero; no upgrade allowed'
    exclusions={compact(name) for name in config.upgrade_excluded_names.split(',') if name.strip()}
    if compact(candidate.name) in exclusions:
        return 'Excluded in upgrade settings'
    floors={'gold':config.upgrade_gold_reserve,'elixir':config.upgrade_elixir_reserve,
            'dark_elixir':config.upgrade_dark_elixir_reserve}
    if candidate.currency not in floors or candidate.cost<=0:
        return 'Unverified resource price; gems and items are never used'
    balance=balances.get(candidate.currency)
    maximum=2_000_000 if candidate.currency=='dark_elixir' else 100_000_000
    if type(balance) is not int or not 0<=balance<=maximum:
        return 'Resource balance could not be verified'
    if balance-candidate.cost < floors[candidate.currency]:
        return 'Would fall below the resource reserve'
    return None
